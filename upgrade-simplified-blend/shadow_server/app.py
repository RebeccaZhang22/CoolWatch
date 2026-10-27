import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .backend import BackendError, InScopeBackend
from .composer import ComposerConfig
from .config import INSCOPE_COMMIT, Settings, validate_model
from .probe import Probe
from .rendering import render_ids
from .normalization import normalize_payload

log = logging.getLogger(__name__)


class DetectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=128)
    tools: list[dict[str, Any]] | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, messages):
        for m in messages:
            if m.get("role") not in ("system", "developer", "user", "assistant", "tool"):
                raise ValueError("Unsupported message role")
            if not isinstance(m.get("content"), str):
                if not (m.get("role") == "assistant" and m.get("content") is None and m.get("tool_calls")):
                    raise ValueError("Text content is required (multimodal input is unsupported)")
            if "tool_calls" in m:
                if not isinstance(m["tool_calls"], list):
                    raise ValueError("tool_calls must be a list")
                for call in m["tool_calls"]:
                    if not isinstance(call, dict):
                        raise ValueError("Invalid tool call")
                    f = call.get("function", call)
                    if not isinstance(f, dict) or not isinstance(f.get("name"), str):
                        raise ValueError("Tool function name is required")
        return messages


def create_app(settings=None, *, tokenizer=None, probe=None, backend=None):
    """Dependencies can be injected for CPU-only protocol tests."""
    settings = settings or Settings.from_env()
    composer = settings.composer

    @asynccontextmanager
    async def lifespan(app):
        nonlocal tokenizer, probe, backend
        if tokenizer is None:
            validate_model(settings.model_path)
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(settings.model_path, local_files_only=True,
                                                     trust_remote_code=False)
        # setup 一次加载两支权重与阈值；不逐请求加载。
        probe = probe or Probe(settings.models_dir, settings.detector_seed, settings.threshold_logit)
        backend = backend or InScopeBackend(settings)
        try:
            yield
        finally:
            await backend.close()

    app = FastAPI(title="CoolWatch-server Qwen3-8B-FP8 detector", version="0.3.0", lifespan=lifespan)
    inflight = 0

    def authenticate(request):
        auth = request.headers.get("authorization", "")
        if not hmac.compare_digest(auth.encode(), ("Bearer " + settings.api_key).encode()):
            raise HTTPException(401, "Invalid API key", headers={"WWW-Authenticate": "Bearer"})

    async def capture(messages, tools=None):
        try:
            ids = await asyncio.to_thread(render_ids, tokenizer, messages, tools, composer)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            raise HTTPException(422, "Invalid conversation or tool template input") from exc
        if len(ids) > settings.max_tokens:
            raise HTTPException(413, f"Input exceeds {settings.max_tokens} tokens; no truncation applied")
        try:
            hidden = await backend.capture(ids, probe.capture_layers)
        except TimeoutError as exc:
            raise HTTPException(504, "SGLang request timed out") from exc
        except BackendError as exc:
            log.warning("Shadow backend failed: %s", type(exc).__name__)
            raise HTTPException(503, "Shadow feature backend unavailable") from exc
        try:
            score = probe.score(hidden)
        except ValueError as exc:
            raise HTTPException(503, "Invalid shadow features or score") from exc
        return score, len(ids)

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready(request: Request):
        # A real prefill checks capture support and tensor shape, not just a live socket.
        authenticate(request)
        nonlocal inflight
        if inflight >= settings.max_inflight:
            raise HTTPException(429, "Detector busy")
        inflight += 1
        try:
            async with asyncio.timeout(settings.timeout):
                await capture([{"role": "user", "content": "Hello"}])
            return {"status": "ready", "model": "Qwen3-8B-FP8", "capture_layers": list(probe.capture_layers)}
        except TimeoutError as exc:
            raise HTTPException(504, "Readiness deadline exceeded") from exc
        finally:
            inflight -= 1

    @app.get("/info")
    async def info(request: Request):
        authenticate(request)
        return {"model": "Qwen3-8B-FP8", "quantization": "fp8", "risk": "indirect_prompt_injection",
                "detector": "a5_blend_linear_n1024", "detector_seed": probe.seed,
                "blend_alpha": probe.blend_alpha,
                "checkpoint_sha256": probe.linear_sha256,
                "linear_sha256": probe.linear_sha256, "mlp_sha256": probe.mlp_sha256,
                "threshold": probe.threshold, "threshold_unit": "sigmoid",
                "threshold_logit": probe.threshold_logit, "threshold_logit_unit": "logit",
                "setting": "simplified", "composer": composer.describe(),
                "block_indices": list(probe.block_indices),
                "capture_layers": list(probe.capture_layers),
                "selected_positions": list(probe.selected_positions),
                "feature_shape": list(probe.feature_shape), "input_dim": probe.input_dim,
                "feature_quantization": "float8_e5m2", "labeling_protocol": "risk_faced",
                "enable_thinking": composer.enable_thinking, "max_input_tokens": settings.max_tokens,
                "inscope_commit": INSCOPE_COMMIT,
                "fp8_probe_calibration": "source_A6_validated_runtime_parity_pending",
                "threshold_calibration": "frozen_A5_cell_seed_thresholds_non_merged_config",
                "threshold_calibration_note": (
                    "阈值取自冻结的 A5 cell results；未合并配置。"
                    "实测 FPR 随 split 变化（validation 2.37% / test 1.06% / extra80k 1.86%），"
                    "不要假定 1% 或跨配置等效。")}

    @app.post("/detect")
    async def detect(request: Request):
        authenticate(request)
        nonlocal inflight
        if inflight >= settings.max_inflight:
            raise HTTPException(429, "Too many in-flight requests", headers={"Retry-After": "1"})
        inflight += 1
        start = time.perf_counter()
        request_id = str(uuid.uuid4())
        try:
            async with asyncio.timeout(settings.timeout):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > settings.max_body_bytes:
                        raise HTTPException(413, "Request exceeds body size limit")
                    body.extend(chunk)
                try:
                    payload = json.loads(body)
                    normalized, changes = normalize_payload(payload)
                    parsed = DetectionInput.model_validate(normalized)
                except (ValueError, UnicodeError, ValidationError) as exc:
                    raise HTTPException(422, "Expected messages list or {messages: [...], tools?: [...]}") from exc
                result, tokens = await capture(parsed.messages, parsed.tools)
                return {**result, "risk": "indirect_prompt_injection", "model": "Qwen3-8B-FP8",
                        "setting": "simplified", "detector_seed": probe.seed,
                        "composer": composer.describe(),
                        "normalization": {"applied": bool(changes), "changes": changes},
                        "checkpoint_sha256": probe.linear_sha256, "input_tokens": tokens,
                        "request_id": request_id, "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
        except TimeoutError as exc:
            raise HTTPException(504, "Detection deadline exceeded") from exc
        finally:
            inflight -= 1
    return app
