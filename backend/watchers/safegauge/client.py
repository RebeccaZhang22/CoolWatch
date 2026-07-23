from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter

import httpx

from backend.config import Settings


@dataclass(frozen=True)
class SafeGaugeAssessment:
    task: str
    label: str
    probability: float | None
    threshold: float | None
    logprobs: list[float]
    risky: bool | None
    raw_output: str
    latency_ms: int
    error: str | None = None

    @property
    def blocked(self) -> bool:
        return self.risky is True


class SafeGaugeClient:
    """Async client for the standalone SafeGauge detection service."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.safegauge_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def moderate_messages(
        self,
        messages: list[dict[str, str]],
        threshold: float | None = None,
    ) -> SafeGaugeAssessment:
        started = perf_counter()
        base_url = self.settings.safegauge_base_url.rstrip("/")
        if not base_url:
            return self._error_assessment("未配置 SAFEGAUGE_BASE_URL", started)

        try:
            request_payload: dict[str, object] = {"messages": messages}
            if threshold is not None:
                request_payload["threshold"] = threshold
            response = await self._client.post(f"{base_url}/detect", json=request_payload)
            response.raise_for_status()
            payload = response.json()
            return SafeGaugeAssessment(
                task=str(payload.get("task") or ""),
                label=str(payload.get("label") or ""),
                probability=optional_float(payload.get("probability")),
                threshold=optional_float(payload.get("threshold")),
                logprobs=[float(value) for value in payload.get("logprobs", [])],
                risky=payload.get("risky") if isinstance(payload.get("risky"), bool) else None,
                raw_output=json.dumps(payload, ensure_ascii=False),
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except Exception as error:
            return self._error_assessment(describe_http_error(error), started)

    async def get_model_info(self) -> dict:
        base_url = self.settings.safegauge_base_url.rstrip("/")
        if not base_url:
            raise RuntimeError("未配置 SAFEGAUGE_BASE_URL")
        response = await self._client.get(f"{base_url}/model/info")
        response.raise_for_status()
        return response.json()

    def _error_assessment(self, error: str, started: float) -> SafeGaugeAssessment:
        return SafeGaugeAssessment(
            task="",
            label="",
            probability=None,
            threshold=None,
            logprobs=[],
            risky=None,
            raw_output="",
            latency_ms=round((perf_counter() - started) * 1000),
            error=error,
        )


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def describe_http_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        try:
            payload = error.response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if detail:
                return f"HTTP {error.response.status_code}: {detail}"
        except ValueError:
            pass
    return str(error)
