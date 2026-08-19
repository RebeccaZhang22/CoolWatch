from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from backend.config import Settings
from backend.watchers.inline_probing.client import (
    InlineProbingAssessment,
    build_inline_probing_request,
    parse_inline_probing_response,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACTIVATION_VLLM_ROUTES = {
    ("qwen3-8b", "finvault"): PROJECT_ROOT
    / "recipe/activation_probing/qwen3-8b-finvault/recipe.json",
    ("qwen3-8b", "prompt"): PROJECT_ROOT
    / "recipe/activation_probing/qwen3-8b-theft-unified-v16-multilayer-mlp/recipe.json",
    ("qwen3-32b", "finvault"): PROJECT_ROOT
    / "recipe/activation_probing/qwen3-32b-finvault/recipe.json",
    ("qwen3-32b", "prompt"): PROJECT_ROOT
    / "recipe/activation_probing/qwen3-32b-prompt-extraction/recipe.json",
}


class ActivationProbeGuard:
    """Run Activation Probe through a standalone model or patched vLLM."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=settings.activation_probe_timeout_seconds
        )

    async def close(self) -> None:
        await self._client.aclose()

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
        try:
            if backend == "vllm":
                return await self._moderate_messages_vllm(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    scenario_category=scenario_category,
                    model=model,
                    threshold=threshold,
                    base_url=base_url,
                    started=started,
                )
            if backend != "standalone":
                raise ValueError(
                    "ACTIVATION_PROBE_BACKEND must be one of: standalone, vllm"
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
                protocol=(
                    "activation_probe.vllm.v1"
                    if backend == "vllm"
                    else "activation_probe.runtime.v1"
                ),
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

    async def _moderate_messages_vllm(
        self,
        *,
        system_prompt: str,
        user_message: str,
        scenario_category: str,
        model: str,
        threshold: float | None,
        base_url: str | None,
        started: float,
    ) -> InlineProbingAssessment:
        route = load_activation_vllm_route(model, scenario_category)
        request_base_url = (
            self.settings.activation_probe_vllm_base_url.strip()
            or base_url
            or self.settings.vllm_base_url
        ).rstrip("/")
        if not request_base_url:
            raise RuntimeError("Activation Probe vLLM base URL is not configured")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 1,
            "stream": False,
            "n": 1,
            "best_of": 1,
            "return_token_ids": True,
            "add_generation_prompt": True,
            "add_special_tokens": scenario_category == "prompt",
            "truncate_prompt_tokens": int(route.get("max_length", 4096)),
            "truncation_side": "left",
            "chat_template_kwargs": {"enable_thinking": False},
            "cache_salt": f"prospect-watch-activation-{uuid.uuid4()}",
        }
        payload["inline_probing_request"] = build_inline_probing_request(
            payload,
            expected_checkpoint_id=route["checkpoint_id"],
            timeout_seconds=self.settings.activation_probe_timeout_seconds,
            probe_id=route["probe_id"],
        )
        response = await self._client.post(
            f"{request_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.vllm_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        result = parse_inline_probing_response(
            response.json(),
            expected_checkpoint_id=route["checkpoint_id"],
            expected_probe_id=route["probe_id"],
        )
        if int(result.get("layer", -1)) != route["layer"]:
            raise RuntimeError("Activation Probe vLLM result layer mismatch")
        result_layers = [int(value) for value in result.get("layers", [result["layer"]])]
        if result_layers != route["layers"]:
            raise RuntimeError("Activation Probe vLLM result layers mismatch")
        if result.get("classifier_type", "linear") != route["classifier_type"]:
            raise RuntimeError("Activation Probe vLLM result classifier mismatch")
        if result.get("task") != route["task"]:
            raise RuntimeError("Activation Probe vLLM result task mismatch")
        checkpoint_threshold = float(route["probability_threshold"])
        resolved_threshold = (
            checkpoint_threshold if threshold is None else float(threshold)
        )
        return InlineProbingAssessment(
            score=float(result["score"]),
            logit=float(result["logit"]),
            threshold=resolved_threshold,
            checkpoint_id=str(result["checkpoint_id"]),
            layer=int(result["layer"]),
            effective_position=int(result.get("effective_position", -1)),
            protocol="activation_probe.vllm.v1",
            raw_output=json.dumps(result, ensure_ascii=False, sort_keys=True),
            latency_ms=round((perf_counter() - started) * 1000),
        )

    async def get_model_info(self) -> dict[str, Any]:
        if self.settings.activation_probe_backend.strip().lower() == "vllm":
            return {
                "backend": "vllm",
                "base_url": (
                    self.settings.activation_probe_vllm_base_url.strip()
                    or self.settings.vllm_base_url
                ),
                "routes": [
                    load_activation_vllm_route(model, category)
                    for model, category in ACTIVATION_VLLM_ROUTES
                ],
            }
        base_url = self.settings.activation_probe_base_url.rstrip("/")
        response = await self._client.get(f"{base_url}/health")
        response.raise_for_status()
        return response.json()


@lru_cache(maxsize=None)
def load_activation_vllm_route(model: str, scenario_category: str) -> dict[str, Any]:
    model_name = _canonical_model_name(model)
    key = (model_name, scenario_category)
    if key not in ACTIVATION_VLLM_ROUTES:
        raise ValueError(
            f"No Activation Probe vLLM route for model={model_name!r}, "
            f"scenario_category={scenario_category!r}"
        )
    recipe_path = ACTIVATION_VLLM_ROUTES[key]
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    probe = recipe["probe"]
    recipe_model = recipe["model"]
    task = recipe["task"]
    checkpoint_path = (recipe_path.parent / probe["path"]).resolve()
    if _canonical_model_name(str(recipe_model["model_revision"])) != model_name:
        raise ValueError(f"Activation Probe recipe model mismatch: {recipe_path}")
    if task.get("activation_kind") != "residual_stream_block_output":
        raise ValueError(
            f"Activation Probe recipe is not residual-compatible: {recipe_path}"
        )
    expected_sha256 = str(probe["sha256"])
    if _sha256_file(checkpoint_path) != expected_sha256:
        raise ValueError(
            f"Activation Probe checkpoint SHA-256 mismatch: {checkpoint_path}"
        )
    logit_threshold = float(probe["logit_threshold"])
    probability_threshold = float(probe["probability_threshold"])
    if not math.isclose(
        probability_threshold,
        _sigmoid(logit_threshold),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(f"Activation Probe recipe threshold mismatch: {recipe_path}")
    return {
        "model": model_name,
        "scenario_category": scenario_category,
        "probe_id": str(probe["id"]),
        "task": str(task["id"]),
        "recipe_path": recipe_path.relative_to(PROJECT_ROOT).as_posix(),
        "checkpoint_path": checkpoint_path.relative_to(PROJECT_ROOT).as_posix(),
        "checkpoint_id": f"sha256:{expected_sha256}",
        "layer": int(probe["checkpoint_layer"]),
        "layers": [
            int(value)
            for value in probe.get("checkpoint_layers", [probe["checkpoint_layer"]])
        ],
        "classifier_type": str(probe.get("classifier_type", "linear")),
        "max_length": int(probe.get("max_length", 4096)),
        "logit_threshold": logit_threshold,
        "probability_threshold": probability_threshold,
    }


def _canonical_model_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", Path(value.rstrip("/")).name.lower())
    aliases = {"qwen38b": "qwen3-8b", "qwen332b": "qwen3-32b"}
    if normalized not in aliases:
        raise ValueError(f"Unsupported Activation Probe vLLM model: {value!r}")
    return aliases[normalized]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
