"""HTTP adapter for InScope detection services.

Each enabled risk is served by its own InScope instance (one risk per instance,
see the design note in ``inscope/README.md``): an instance answers for exactly
one risk and advertises it on ``/info`` and in every ``/detect`` result, so the
adapter can prove it asked the right detector before trusting a verdict.
"""
import asyncio
import json
import math
from dataclasses import dataclass, field
from time import perf_counter

import httpx

from backend.probe_risks import DEFAULT_ENABLED_RISKS, parse_enabled_risks

LABELS = ("attack", "benign")

# CoolWatch 的风险 id 与训练侧 checkpoint 的风险名不同（风险语义相同）。
# 检测器在 /detect 里声明自己答哪个风险，这里是两侧标识的唯一映射点。
DETECTOR_RISK_NAMES = {"ipi": "indirect_prompt_injection"}


def detector_risk_name(risk):
    return DETECTOR_RISK_NAMES.get(risk, risk)


def parse_risk_endpoints(raw, enabled, fallback):
    """``risk=url`` pairs; without the variable one instance serves every risk."""
    if not raw:
        return {risk: fallback for risk in enabled}
    pairs = {}
    for chunk in raw.split(","):
        risk, _, url = chunk.partition("=")
        risk, url = risk.strip(), url.strip().rstrip("/")
        if not risk or not url:
            raise ValueError("Risk endpoints must look like risk=url")
        if risk not in enabled:
            raise ValueError("Risk endpoint %r is not in the enabled risks" % risk)
        pairs[risk] = url
    missing = [risk for risk in enabled if risk not in pairs]
    if missing:
        raise ValueError("Missing a detection endpoint for: " + ",".join(missing))
    return pairs


@dataclass
class RiskResult:
    risk: str
    flagged: bool
    score: float
    logit: float
    threshold: float
    probe: str
    checkpoint_sha256: str
    input_tokens: int
    latency_ms: int
    blocks: list = field(default_factory=list)
    coordinate_system: str | None = None
    importance_semantics: str | None = None

    def summary(self):
        result = {"flagged": self.flagged, "score": self.score, "logit": self.logit,
                  "threshold": self.threshold, "input_tokens": self.input_tokens,
                  "latency_ms": self.latency_ms}
        if self.blocks:
            result["blocks"] = self.blocks
            result["coordinate_system"] = self.coordinate_system
            result["importance_semantics"] = self.importance_semantics
        return result


@dataclass
class BankAssessment:
    risks: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str | None = None
    status_code: int = 503

    @property
    def risky(self):
        return None if self.error else any(result.flagged for result in self.risks.values())

    @property
    def payload(self):
        return {"per_risk": {risk: result.summary() for risk, result in self.risks.items()},
                "latency_ms": {risk: result.latency_ms for risk, result in self.risks.items()},
                "probes": {risk: {"probe": result.probe,
                                  "checkpoint_sha256": result.checkpoint_sha256}
                           for risk, result in self.risks.items()},
                "input_tokens": max((result.input_tokens for result in self.risks.values()),
                                    default=0)}

    @property
    def raw_output(self):
        return json.dumps(self.payload, ensure_ascii=False, default=list)


class ProbeBankGuard:
    def __init__(self, settings):
        self.settings = settings
        self.enabled_risks = parse_enabled_risks(
            getattr(settings, "probe_bank_enabled_risks", DEFAULT_ENABLED_RISKS))
        self.endpoints = parse_risk_endpoints(
            getattr(settings, "probe_bank_risk_endpoints", ""), self.enabled_risks,
            settings.probe_bank_base_url.rstrip("/"))
        api_key = getattr(settings, "probe_bank_api_key", "")
        self._client = httpx.AsyncClient(
            timeout=min(settings.activation_probe_timeout_seconds, 65.0),
            headers={"Authorization": "Bearer " + api_key} if api_key else {},
            limits=httpx.Limits(max_connections=128, max_keepalive_connections=64))

    async def close(self):
        await self._client.aclose()

    async def get_model_info(self):
        responses = await asyncio.gather(
            *(self._client.get(url + "/info") for url in self.endpoints.values()),
            return_exceptions=True)
        info, errors = {}, {}
        for risk, response in zip(self.endpoints, responses):
            if isinstance(response, Exception):
                errors[risk] = str(response)
                continue
            try:
                response.raise_for_status()
                info[risk] = response.json()
            except Exception as error:  # noqa: BLE001 - reported per risk, never raised
                errors[risk] = str(error)
        return {"instances": info, "errors": errors,
                "enabled_risks": list(self.enabled_risks)}

    async def _detect(self, risk, url, messages, tools):
        start = perf_counter()
        body = {"messages": messages}
        if tools:
            body["tools"] = tools
        # explain 与打分共用同一次前向；有块级探针时才会多出 blocks。
        body["explain"] = True
        response = await self._client.post(url + "/detect", json=body)
        response.raise_for_status()
        return self._validate(risk, response.json(), round((perf_counter() - start) * 1000))

    def _validate(self, risk, payload, latency_ms):
        if not isinstance(payload, dict):
            raise ValueError("Detector returned a non-object response")
        expected = detector_risk_name(risk)
        if payload.get("risk") != expected:
            # 一个实例只答一个风险，答错就是接错了地址。
            raise ValueError("Detector at this endpoint answers for %r, expected %r"
                             % (payload.get("risk"), expected))
        model = self.settings.customer_agent_shadow_model
        if model and payload.get("model") != model:
            raise ValueError("Shadow model and detector do not match")
        score, logit, threshold = payload.get("probability"), payload.get("logit"), payload.get("threshold")
        for name, value in (("score", score), ("logit", logit), ("threshold", threshold)):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Invalid detector %s" % name)
        if not 0 <= score <= 1 or not 0 <= threshold <= 1:
            raise ValueError("Detector score/threshold outside [0, 1]")
        label = payload.get("label")
        if label not in LABELS:
            raise ValueError("Detector label must be attack/benign")
        if (label == "attack") != (score >= threshold):
            raise ValueError("Detector label contradicts its own score")
        # 探针身份取自 composer.probe_id：实例用哪个 profile 就必须答对应探针。
        probe = (payload.get("composer") or {}).get("probe_id")
        sha256 = payload.get("checkpoint_sha256")
        if not probe or not sha256:
            raise ValueError("Missing detector identity (composer.probe_id/checkpoint_sha256)")
        if not payload.get("input_tokens", 0) > 0:
            raise ValueError("Missing token usage")
        blocks = payload.get("blocks") or []
        if blocks:
            for block in blocks:
                for key in ("message_index", "kind", "start", "end"):
                    if key not in block:
                        raise ValueError("Block is missing %r" % key)
        return RiskResult(risk=risk, flagged=(label == "attack"), score=score, logit=logit,
                          threshold=threshold, probe=probe, checkpoint_sha256=sha256,
                          input_tokens=payload["input_tokens"], latency_ms=latency_ms,
                          blocks=list(blocks), coordinate_system=payload.get("coordinate_system"),
                          importance_semantics=payload.get("importance_semantics"))

    async def moderate(self, messages, tools=None):
        start = perf_counter()
        pending = {risk: asyncio.create_task(self._detect(risk, url, messages, tools))
                   for risk, url in self.endpoints.items()}
        results, failure = {}, None
        for risk, task in pending.items():
            try:
                results[risk] = await task
            except httpx.HTTPStatusError as error:
                failure = failure or (error, error.response.status_code)
            except Exception as error:  # noqa: BLE001 - normalized into one assessment
                failure = failure or (error, 503)
        elapsed = round((perf_counter() - start) * 1000)
        if failure is not None:
            error, status = failure
            if isinstance(error, httpx.HTTPStatusError):
                status = status if status in (400, 413, 429, 504) else 503
                message = "Detector rejected request (%d)" % error.response.status_code
            else:
                status, message = 503, str(error)
            return BankAssessment({}, elapsed, message, status)
        return BankAssessment(results, elapsed)
