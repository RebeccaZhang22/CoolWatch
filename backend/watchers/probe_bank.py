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
        self._client = httpx.AsyncClient(timeout=min(settings.activation_probe_timeout_seconds, 65.0),
                                        limits=httpx.Limits(max_connections=128, max_keepalive_connections=64))

    async def close(self):
        await self._client.aclose()

    async def get_model_info(self):
        response = await self._client.get(self.settings.probe_bank_base_url.rstrip('/') + '/bank')
        response.raise_for_status()
        return response.json()

    async def moderate(self, messages, tools=None):
        start = perf_counter()
        try:
            response = await self._client.post(self.settings.probe_bank_base_url.rstrip('/') + '/detect',
                                               json={'messages': messages, 'tools': tools})
            response.raise_for_status()
            payload = response.json()
            if payload.get('detector_model') != self.settings.customer_agent_shadow_model:
                raise ValueError('Shadow model and probe bank do not match')
            if set(payload.get('per_risk', {})) != set(self.enabled_risks):
                raise ValueError('Probe results do not match enabled risks')
            if payload.get('enabled_risks') is not None and set(payload['enabled_risks']) != set(self.enabled_risks):
                raise ValueError('Probe bank risk configuration mismatch')
            for result in payload['per_risk'].values():
                if type(result.get('flagged')) is not bool:
                    raise ValueError('Invalid probe verdict')
                for key in ('score', 'threshold'):
                    if not math.isfinite(result[key]) or not 0 <= result[key] <= 1:
                        raise ValueError('Invalid probe score/threshold')
            if not payload.get('bank_version') or payload.get('input_tokens', 0) <= 0:
                raise ValueError('Missing bank identity or token usage')
            return BankAssessment(payload, round((perf_counter()-start)*1000))
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            return BankAssessment({}, round((perf_counter()-start)*1000),
                                  f'Probe service rejected request ({status})',
                                  status if status in (400, 413, 429, 504) else 503)
        except Exception as error:
            return BankAssessment({}, round((perf_counter()-start)*1000), str(error))
