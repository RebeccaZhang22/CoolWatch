"""HTTP adapter for the private Qwen3 shadow probe bank."""
import json
import math
from dataclasses import dataclass
from time import perf_counter

import httpx

from backend.probe_risks import RISK_NAMES, DEFAULT_ENABLED_RISKS, parse_enabled_risks


@dataclass
class BankAssessment:
    payload: dict
    latency_ms: int
    error: str | None = None
    status_code: int = 503

    @property
    def risky(self):
        return None if self.error else any(r['flagged'] for r in self.payload['per_risk'].values())

    @property
    def raw_output(self):
        return json.dumps(self.payload, ensure_ascii=False)


class ProbeBankGuard:
    def __init__(self, settings):
        self.settings = settings
        self.enabled_risks = parse_enabled_risks(getattr(settings, "probe_bank_enabled_risks", DEFAULT_ENABLED_RISKS))
        # Probe service requires Bearer auth on every non-liveness path.
        # Missing key fails closed at request time instead of sending an anonymous call.
        self._api_key = (getattr(settings, "probe_bank_api_key", "") or "").strip()
        self._client = httpx.AsyncClient(timeout=min(settings.activation_probe_timeout_seconds, 65.0),
                                        limits=httpx.Limits(max_connections=128, max_keepalive_connections=64))

    async def close(self):
        await self._client.aclose()

    def _auth_headers(self):
        if not self._api_key:
            raise ValueError("PROBE_BANK_API_KEY is not configured")
        return {'Authorization': f'Bearer {self._api_key}'}

    async def get_model_info(self):
        # Probe service exposes /info (auth required); /bank does not exist there.
        response = await self._client.get(self.settings.probe_bank_base_url.rstrip('/') + '/info',
                                          headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

    async def moderate(self, messages, tools=None):
        """Ask the probe service, then narrow its answer to the risks we enabled.

        The service may load more risks than this deployment enables; extras are not
        an error, they are simply dropped so the UI only ever shows enabled rows.
        A risk we enabled that comes back unevaluated IS an error (fail closed).
        """
        start = perf_counter()
        try:
            # Request only the risks we need; the probe service may serve more.
            response = await self._client.post(self.settings.probe_bank_base_url.rstrip('/') + '/detect',
                                               headers=self._auth_headers(),
                                               json={'messages': messages, 'tools': tools,
                                                     'enabled_risks': list(self.enabled_risks)})
            response.raise_for_status()
            payload = response.json()
            # The probe service owns which model it runs. We only need to know it
            # reported one; it must not have to match our own shadow model setting.
            if not payload.get('detector_model'):
                raise ValueError('Probe service did not report a detector model')
            served = payload.get('per_risk')
            missing = [risk for risk in self.enabled_risks if not (served or {}).get(risk)]
            if missing:
                raise ValueError('Probe service did not evaluate enabled risks: ' + ','.join(missing))
            for result in served.values():
                if type(result.get('flagged')) is not bool:
                    raise ValueError('Invalid probe verdict')
                for key in ('score', 'threshold'):
                    if not math.isfinite(result[key]) or not 0 <= result[key] <= 1:
                        raise ValueError('Invalid probe score/threshold')
            if not payload.get('bank_version') or payload.get('input_tokens', 0) <= 0:
                raise ValueError('Missing bank identity or token usage')
            # Narrow to the risks we enabled: downstream UI only knows those. Extra
            # risks the probe service happens to load are not an error.
            payload['enabled_risks'] = list(self.enabled_risks)
            payload['disabled_risks'] = [risk for risk in RISK_NAMES if risk not in self.enabled_risks]
            payload['per_risk'] = {risk: row for risk, row in served.items()
                                   if risk in self.enabled_risks}
            payload['per_entry'] = {risk: score for risk, score in (payload.get('per_entry') or {}).items()
                                    if risk in self.enabled_risks}
            payload['triggered_entries'] = [risk for risk in (payload.get('triggered_entries') or [])
                                            if risk in self.enabled_risks]
            return BankAssessment(payload, round((perf_counter()-start)*1000))
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            return BankAssessment({}, round((perf_counter()-start)*1000),
                                  f'Probe service rejected request ({status})',
                                  status if status in (400, 413, 429, 504) else 503)
        except Exception as error:
            return BankAssessment({}, round((perf_counter()-start)*1000), str(error))
