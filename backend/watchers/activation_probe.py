from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import httpx

from backend.config import Settings
from backend.watchers.probe_bank import ProbeBankGuard
from backend.watchers.inline_probing.client import (
    InlineProbingAssessment,
)

class ActivationProbeGuard:
    """Run activation detection through Probe Bank or the standalone service."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bank_guard = ProbeBankGuard(settings)
        self._client = httpx.AsyncClient(
            timeout=settings.activation_probe_timeout_seconds
        )

    async def close(self) -> None:
        await self._client.aclose()
        await self.bank_guard.close()

    async def moderate_messages(
        self,
        *,
        system_prompt: str,
        user_message: str,
        scenario_category: str,
        model: str,
        threshold: float | None = None,
        base_url: str | None = None,
    ) -> InlineProbingAssessment:
        started = perf_counter()
        backend = self.settings.activation_probe_backend.strip().lower()
        if backend == "probe_bank":
            return await self.bank_guard.moderate([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ])
        try:
            if backend != "standalone":
                raise ValueError(
                    "ACTIVATION_PROBE_BACKEND must be one of: probe_bank, standalone; the legacy vllm recipe backend has been removed"
                )
            return await self._moderate_messages_standalone(
                system_prompt=system_prompt,
                user_message=user_message,
                scenario_category=scenario_category,
                model=model,
                threshold=threshold,
                started=started,
            )
        except Exception as error:
            return InlineProbingAssessment(
                score=None,
                logit=None,
                threshold=float(threshold if threshold is not None else 0.5),
                checkpoint_id=None,
                layer=None,
                effective_position=None,
                protocol="activation_probe.runtime.v1",
                raw_output="",
                latency_ms=round((perf_counter() - started) * 1000),
                error=str(error),
            )

    async def _moderate_messages_standalone(
        self,
        *,
        system_prompt: str,
        user_message: str,
        scenario_category: str,
        model: str,
        threshold: float | None,
        started: float,
    ) -> InlineProbingAssessment:
        base_url = self.settings.activation_probe_base_url.rstrip("/")
        if not base_url:
            raise RuntimeError("ACTIVATION_PROBE_BASE_URL is not configured")
        response = await self._client.post(
            f"{base_url}/detect",
            json={
                "system_prompt": system_prompt,
                "user_message": user_message,
                "scenario_category": scenario_category,
                "model": model,
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        checkpoint_threshold = float(payload["threshold"])
        resolved_threshold = (
            checkpoint_threshold if threshold is None else float(threshold)
        )
        return InlineProbingAssessment(
            score=float(payload["score"]),
            logit=float(payload["logit"]),
            threshold=resolved_threshold,
            checkpoint_id=str(payload.get("checkpoint_id") or ""),
            layer=_optional_int(payload.get("layer")),
            effective_position=-1,
            protocol=str(payload.get("protocol") or "activation_probe.runtime.v1"),
            raw_output=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            latency_ms=round((perf_counter() - started) * 1000),
        )

    async def get_model_info(self) -> dict[str, Any]:
        backend = self.settings.activation_probe_backend.strip().lower()
        if backend == "probe_bank":
            return await self.bank_guard.get_model_info()
        if backend != "standalone":
            raise ValueError("Unsupported Activation Probe backend; use probe_bank or standalone")
        base_url = self.settings.activation_probe_base_url.rstrip("/")
        response = await self._client.get(f"{base_url}/health")
        response.raise_for_status()
        return response.json()


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
