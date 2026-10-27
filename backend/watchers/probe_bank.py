"""HTTP adapter for one-or-more single-risk InScope probe services.

部署约定（方案 A，不是服务端能力上限）：**Coolwatch 让一个 inscope-service 实例只负责一类风险**。
多类风险 = 多个实例、多个端口，由本适配层并发调用后合并成 `per_risk`。
外部服务自己也可以在一个进程里加载多探针；本层不使用那条路径，也不把顶层分数
当成“配置里的风险”。顶层 `probability` 始终是该实例的主探针，顶层 `risk` 还保留历史固定值。

因此每次检测前先读 `/info`：`risks` 必须恰好声明本端点配置的那一类，且与主探针一致。
身份不符、多风险实例、或 `/info` 不可用，都按失败关闭，不会把别的风险的分数标成本类。

失败语义（与旧版一致，不做静默降级）：
* 任一**已启用**风险的检测失败 → 整体判定为不可用，返回 error。已成功的那几类仍留在
  payload 里供排查，但调用方不应把它当成“其余风险通过”。
* 未启用的风险不会被打分，也不会出现在 `per_risk` 中；它们只出现在 `disabled_risks`。
"""
import asyncio
import json
import math
from dataclasses import dataclass
from time import perf_counter

import httpx

from backend.probe_risks import (
    RISK_NAMES,
    DEFAULT_ENABLED_RISKS,
    DEFAULT_RISK_PORT,
    parse_enabled_risks,
    parse_risk_endpoints,
)


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


@dataclass
class _RiskProbe:
    """One risk class and the single-risk service instance that evaluates it."""

    risk: str
    base_url: str


def _resolve_endpoints(settings, enabled_risks):
    """Map each enabled risk to exactly one service instance.

    `PROBE_BANK_RISK_ENDPOINTS` is authoritative. The legacy single
    `PROBE_BANK_BASE_URL` is only an implicit fallback for the one risk it can
    sensibly cover: a single-risk deployment. Pointing several risks at one
    `base_url` is rejected at startup instead of silently sending every risk to an
    instance that only evaluates one of them.
    """
    explicit = parse_risk_endpoints(getattr(settings, 'probe_bank_risk_endpoints', ''))
    legacy = (getattr(settings, 'probe_bank_base_url', '') or '').strip().rstrip('/')
    unknown = [risk for risk in explicit if risk not in enabled_risks]
    if unknown:
        # A configured endpoint for a risk this deployment does not enable is a
        # configuration smell: either the list or the endpoint set is wrong.
        raise ValueError('PROBE_BANK_RISK_ENDPOINTS configures risks that are not enabled: '
                         + ','.join(unknown))
    # The legacy URL alone cannot serve several risks. Leaving it set is harmless
    # though: it is ignored once every enabled risk has an explicit endpoint.
    uncovered = [risk for risk in enabled_risks if risk not in explicit]
    if legacy and len(enabled_risks) > 1 and uncovered:
        raise ValueError(
            'PROBE_BANK_ENABLED_RISKS enables ' + ','.join(enabled_risks)
            + ' but only PROBE_BANK_BASE_URL covers ' + ','.join(uncovered)
            + '; one probe service instance evaluates exactly one risk. Set '
            'PROBE_BANK_RISK_ENDPOINTS=' + ','.join(f'{risk}=http://host:port' for risk in enabled_risks)
        )
    endpoints = {}
    for risk in enabled_risks:
        if risk in explicit:
            endpoints[risk] = explicit[risk]
        elif legacy:
            endpoints[risk] = legacy
        elif risk in DEFAULT_RISK_PORT:
            endpoints[risk] = f'http://127.0.0.1:{DEFAULT_RISK_PORT[risk]}'
        else:
            raise ValueError(
                f'No probe service configured for enabled risk {risk!r}; '
                'set PROBE_BANK_RISK_ENDPOINTS (risk=url,...)'
            )
    return tuple(_RiskProbe(risk=risk, base_url=endpoints[risk]) for risk in enabled_risks)


class ProbeBankGuard:
    def __init__(self, settings):
        self.settings = settings
        self.enabled_risks = parse_enabled_risks(getattr(settings, "probe_bank_enabled_risks", DEFAULT_ENABLED_RISKS))
        self.probes = _resolve_endpoints(settings, self.enabled_risks)
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

    @property
    def endpoints(self):
        return {probe.risk: probe.base_url for probe in self.probes}

    async def _fetch_info(self, probe):
        response = await self._client.get(probe.base_url + '/info', headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _advertised_risks(info):
        """Risks this instance actually loaded, from `/info`, not from our config.

        `risks[].risk` is the registry. Top-level `risk` on `/detect` is a historical
        constant and must not be used as identity. A missing or malformed registry is
        not "trust the URL": it is an identity we cannot verify.
        """
        rows = info.get('risks') if isinstance(info, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError('probe service /info did not advertise a risk registry')
        advertised = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('risk'), str) or not row['risk']:
                raise ValueError('probe service /info has a malformed risk registry')
            advertised.append(row['risk'])
        if len(set(advertised)) != len(advertised):
            raise ValueError('probe service /info repeats a risk: ' + ','.join(advertised))
        return tuple(advertised)

    def _require_single_risk(self, probe, info):
        """Option A: this URL must serve exactly the risk we configured for it."""
        advertised = self._advertised_risks(info)
        if advertised != (probe.risk,):
            raise ValueError(
                f'{probe.base_url} is configured as {probe.risk} but advertises '
                + ','.join(advertised)
                + '; one endpoint must serve exactly that risk'
            )
        return info

    async def get_model_info(self):
        """Report what each enabled risk is actually served by.

        The composite shape is additive: `enabled_risks` / `disabled_risks` /
        `per_risk` mirror the detection payload, and the legacy top-level fields
        (model, threshold, layers, ...) describe the first enabled risk so existing
        single-risk consumers keep working.
        """
        infos = await asyncio.gather(*(self._fetch_info(probe) for probe in self.probes),
                                     return_exceptions=True)
        per_risk, failures = {}, []
        for probe, info in zip(self.probes, infos):
            if isinstance(info, BaseException):
                failures.append({'risk': probe.risk, 'base_url': probe.base_url, 'error': str(info)})
                continue
            try:
                self._require_single_risk(probe, info)
            except ValueError as error:
                failures.append({'risk': probe.risk, 'base_url': probe.base_url, 'error': str(error)})
                continue
            per_risk[probe.risk] = {'base_url': probe.base_url, **info}
        # Transport failures of every instance stay an exception: there is no
        # service to describe. An identity mismatch is a reply we understood, so
        # it stays in `unavailable` and health can report degraded instead of down.
        transport_failures = [item for item in failures if 'advertises' not in item['error']]
        if transport_failures and len(transport_failures) == len(self.probes):
            raise ValueError('; '.join(f"{item['risk']}@{item['base_url']}: {item['error']}"
                                       for item in transport_failures))
        primary_key = next((probe.risk for probe in self.probes if probe.risk in per_risk), None)
        payload = dict(per_risk.get(primary_key) or {}) if primary_key else {}
        payload.update(
            enabled_risks=list(self.enabled_risks),
            disabled_risks=[risk for risk in RISK_NAMES if risk not in self.enabled_risks],
            per_risk=per_risk,
            unavailable=failures,
        )
        return payload

    async def _detect_one(self, probe, messages, tools, *, response_payload=None):
        """Score one risk on its own instance and normalise it to a per_risk row.

        `response_payload` is only for CPU tests: it replaces the HTTP round trip
        while keeping every score validation below in the path under test.
        Those tests also skip the `/info` identity check; production always runs it.
        """
        if response_payload is None:
            # Identity before score. A reachable instance that loaded another risk
            # must not have its primary probability labelled as this configured risk.
            info = await self._fetch_info(probe)
            self._require_single_risk(probe, info)
            response = await self._client.post(probe.base_url + '/detect',
                                               headers=self._auth_headers(),
                                               json={'messages': messages, 'tools': tools})
            response.raise_for_status()
            payload = response.json()
        else:
            payload = response_payload
        # The service owns which model it runs; it only has to report one.
        detector_model = payload.get('detector_model') or payload.get('model')
        if not detector_model:
            raise ValueError(f'{probe.risk}: probe service did not report a detector model')
        probability, threshold = payload.get('probability'), payload.get('threshold')
        if probability is None or threshold is None:
            raise ValueError(f'{probe.risk}: probe service returned no probability/threshold')
        if (not math.isfinite(float(probability)) or not 0 <= float(probability) <= 1
                or not math.isfinite(float(threshold)) or not 0 <= float(threshold) <= 1):
            raise ValueError(f'{probe.risk}: invalid probe score/threshold')
        # Prefer the service's own verdict; recomputing keeps one source of truth
        # when a service only returns the label without a threshold comparison.
        label = payload.get('label')
        if label in ('attack', 'benign'):
            flagged = label == 'attack'
        elif type(payload.get('flagged')) is bool:
            flagged = payload['flagged']
        else:
            flagged = float(probability) >= float(threshold)
        if flagged != (float(probability) >= float(threshold)):
            raise ValueError(f'{probe.risk}: label is inconsistent with probability and threshold')
        return {
            'risk': probe.risk,
            'base_url': probe.base_url,
            'detector_model': detector_model,
            'row': {'score': float(probability), 'threshold': float(threshold), 'flagged': flagged},
            'detail': {
                'logit': payload.get('logit'),
                'label': label,
                'probability': float(probability),
                'threshold': float(threshold),
                'composer_profile': payload.get('composer_profile'),
                'checkpoint_sha256': payload.get('checkpoint_sha256'),
                'input_tokens': payload.get('input_tokens'),
                'latency_ms': payload.get('latency_ms'),
                'request_id': payload.get('request_id'),
                'risk': payload.get('risk'),
            },
        }

    async def moderate(self, messages, tools=None):
        """Fan out one request per enabled risk, then merge into one verdict.

        Each instance is single-risk, so this is N HTTP calls, run concurrently.
        A failure on any enabled risk makes the whole assessment an error: fold
        "some risks failed" into "passed" would be exactly the silent downgrade
        the guards elsewhere in this codebase are written to avoid.
        """
        start = perf_counter()
        try:
            results = await asyncio.gather(
                *(self._detect_one(probe, messages, tools) for probe in self.probes),
                return_exceptions=True,
            )
            per_risk, per_entry, details, triggered = {}, {}, {}, []
            for probe, result in zip(self.probes, results):
                if isinstance(result, BaseException):
                    raise _RiskFailure(probe, result) from result
                per_risk[probe.risk] = result['row']
                per_entry[probe.risk] = result['row']['score']
                details[probe.risk] = result['detail']
                if result['row']['flagged']:
                    triggered.append(probe.risk)
            detector_models = sorted({item['detector_model'] for item in results})
            payload = {
                **risk_selection_payload(self.enabled_risks),
                'overall': bool(triggered),
                'profile': 'balanced',
                'per_risk': per_risk,
                'per_entry': per_entry,
                'triggered_entries': triggered,
                'detector_model': detector_models[0] if len(detector_models) == 1
                else 'multiple:' + '+'.join(detector_models),
                # There is no single bank identity any more: each risk is its own
                # service instance with its own checkpoint.
                'bank_version': '; '.join(f"{risk}@{details[risk]['checkpoint_sha256'] or 'unknown'}"
                                          for risk in per_risk),
                'input_tokens': max(details[risk]['input_tokens'] or 0 for risk in details),
                'per_risk_detail': details,
                # Same scalar shape as BankAssessment.latency_ms so callers do
                # not have to guess whether a payload field is a number or a
                # mapping. Product-side timing is added by the API route.
                'latency_ms': round((perf_counter() - start) * 1000),
            }
            return BankAssessment(payload, round((perf_counter() - start) * 1000))
        except _RiskFailure as failure:
            # Name the failing risk: with one instance per risk, "which one" is
            # the whole point of the error.
            return BankAssessment({}, round((perf_counter() - start) * 1000),
                                  f'Probe service for {failure.risk} failed: {failure.cause}',
                                  failure.status_code)
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            return BankAssessment({}, round((perf_counter() - start) * 1000),
                                  f'Probe service rejected request ({status})',
                                  status if status in (400, 413, 429, 504) else 503)
        except Exception as error:
            return BankAssessment({}, round((perf_counter() - start) * 1000), str(error))


def risk_selection_payload(enabled):
    """enabled/disabled risk lists, kept in the historical field names."""
    return dict(enabled_risks=list(enabled),
                disabled_risks=[risk for risk in RISK_NAMES if risk not in enabled])


class _RiskFailure(Exception):
    """Carry which risk's instance failed so the error names the culprit."""

    def __init__(self, probe, cause):
        self.risk = probe.risk
        self.cause = cause
        status = getattr(getattr(cause, 'response', None), 'status_code', None)
        self.status_code = status if status in (400, 413, 429, 504) else 503
        super().__init__(f'{probe.risk}@{probe.base_url}: {cause}')
