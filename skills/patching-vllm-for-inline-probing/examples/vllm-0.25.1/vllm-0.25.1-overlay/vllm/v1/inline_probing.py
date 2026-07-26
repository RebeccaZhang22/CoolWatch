# SPDX-License-Identifier: Apache-2.0
"""Runtime contracts and linear-probe scoring for vLLM inline_probing."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import MISSING, asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import torch


REQUEST_SCHEMA = "inline_probing.request.v1"
RESULT_SCHEMA = "inline_probing.result.v1"
CONFIG_SCHEMA = "inline_probing.probe_config.v1"
CHECKPOINT_SCHEMA = "inline_probing.probe_checkpoint.v2"
LEGACY_CHECKPOINT_SCHEMA = "fyh.probe_checkpoint.v2"
SCORER_CONTRACT = "inline_probing.linear_probe.v1"
SUPPORTED_FAMILY_POSITIONS = {
    "qwen3": -1,
    "qwen3.5": -3,
    "oai-oss": -1,
    "gemma4": -1,
}


class InlineProbingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class InlineProbingConfig:
    schema: str
    checkpoint_schema: str
    scorer_contract_version: str
    checkpoint_path: str
    checkpoint_sha256: str
    model_family: str
    model_revision: str
    target_layer: int
    requested_position: int
    effective_position: int
    activation_kind: str
    hidden_width: int
    normalization: str
    tensor_parallel_size: int
    pipeline_parallel_size: int
    required: bool = True
    transport: str = "inline"
    disable_ubatching: bool = True
    disable_speculative_decoding: bool = True
    disable_async_scheduling: bool = True
    disable_pipeline_batch_queues: bool = True
    max_deadline_ms: int = 120_000

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InlineProbingConfig":
        fields = cls.__dataclass_fields__
        unknown = set(value) - set(fields)
        missing = {
            name
            for name, field in fields.items()
            if field.default is MISSING
            and field.default_factory is MISSING
            and name not in value
        }
        if unknown or missing:
            raise InlineProbingError(
                "incompatible",
                f"probe config fields mismatch; missing={sorted(missing)}, "
                f"unknown={sorted(unknown)}",
            )
        try:
            config = cls(**dict(value))
        except (TypeError, ValueError) as exc:
            raise InlineProbingError("incompatible", "malformed probe config") from exc
        if config.schema != CONFIG_SCHEMA:
            raise InlineProbingError("incompatible", "unsupported probe config schema")
        if config.checkpoint_schema != CHECKPOINT_SCHEMA:
            raise InlineProbingError("incompatible", "unsupported checkpoint schema")
        if config.scorer_contract_version != SCORER_CONTRACT:
            raise InlineProbingError("incompatible", "unsupported scorer contract")
        return config

    @property
    def checkpoint_id(self) -> str:
        return f"sha256:{self.checkpoint_sha256}"

    @property
    def aux_hidden_state_layer(self) -> int:
        """Translate FYH block-output numbering to vLLM aux numbering.

        FYH records the residual-stream output after zero-based block N as
        layer N. vLLM's Eagle auxiliary interface labels that same boundary
        N + 1, reserving auxiliary layer 0 for the embedding output.
        """
        return self.target_layer + 1


@dataclass(frozen=True)
class InlineProbingRequest:
    schema: str
    required: bool
    logical_request_id: str
    attempt_id: str
    expected_checkpoint_id: str
    input_attempt_fingerprint: str
    deadline_ms: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InlineProbingRequest":
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != expected:
            raise InlineProbingError("incompatible", "probe request fields mismatch")
        try:
            request = cls(**dict(value))
        except (TypeError, ValueError) as exc:
            raise InlineProbingError("incompatible", "malformed probe request") from exc
        if request.schema != REQUEST_SCHEMA or request.required is not True:
            raise InlineProbingError("incompatible", "unsupported request contract")
        for name in ("logical_request_id", "attempt_id"):
            if not getattr(request, name):
                raise InlineProbingError("incompatible", f"{name} must be non-empty")
        for name in ("expected_checkpoint_id", "input_attempt_fingerprint"):
            value = getattr(request, name)
            if not _valid_sha256_id(value):
                raise InlineProbingError("incompatible", f"{name} must be sha256:<hex>")
        if not isinstance(request.deadline_ms, int) or request.deadline_ms <= 0:
            raise InlineProbingError("incompatible", "deadline_ms must be positive")
        return request

    def effective_deadline_ms(self, server_max_ms: int) -> int:
        return min(self.deadline_ms, server_max_ms)


@dataclass(frozen=True)
class InlineProbingCaptureSpec:
    request_id: str
    attempt_id: str
    target_token_index: int
    scheduled_start: int
    scheduled_count: int
    scheduler_step: int
    input_attempt_fingerprint: str
    prompt_token_count: int
    native_prompt_token_fingerprint: str


@dataclass(frozen=True)
class InlineProbingResult:
    schema: str
    status: str
    request_id: str
    attempt_id: str
    score: float
    logit: float
    captured_token_index: int
    scheduler_step: int
    chunk_start: int
    chunk_end: int
    captured_token_id: int = -1
    checkpoint_id: str = ""
    input_attempt_fingerprint: str = ""
    native_prompt_token_fingerprint: str = ""
    prompt_token_count: int = 0
    model_family: str = "oai-oss"
    model_revision: str = ""
    layer: int = 4
    requested_position: int = -1
    effective_position: int = -1
    feature_dtype: str = "model"
    accumulation_dtype: str = "float32"
    normalization: str = "checkpoint"
    scoring_latency_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InlineProbingFailure:
    code: str
    message: str
    attempt_id: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedProbeCheckpoint:
    config: InlineProbingConfig
    weight: torch.Tensor
    bias: torch.Tensor
    mean: torch.Tensor
    inv_std: torch.Tensor


class InlineLinearProbe:
    def __init__(self, checkpoint: ResolvedProbeCheckpoint, device: torch.device):
        self.checkpoint = checkpoint
        self.weight = checkpoint.weight.to(device=device, dtype=torch.float32)
        self.bias = checkpoint.bias.to(device=device, dtype=torch.float32)
        self.mean = checkpoint.mean.to(device=device, dtype=torch.float32)
        self.inv_std = checkpoint.inv_std.to(device=device, dtype=torch.float32)

    def score_batch(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = features.to(dtype=torch.float32)
        x = (x - self.mean) * self.inv_std
        logits = torch.nn.functional.linear(x, self.weight, self.bias).flatten()
        return logits, torch.sigmoid(logits)


def load_config_from_env() -> InlineProbingConfig | None:
    raw = os.environ.get("INLINE_PROBING_CONFIG")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InlineProbingError("incompatible", "INLINE_PROBING_CONFIG is not JSON") from exc
    if not isinstance(value, Mapping):
        raise InlineProbingError("incompatible", "INLINE_PROBING_CONFIG must be an object")
    return InlineProbingConfig.from_mapping(value)


def load_resolved_checkpoint(config: InlineProbingConfig) -> ResolvedProbeCheckpoint:
    path = Path(config.checkpoint_path)
    if not path.is_file():
        raise InlineProbingError("missing_checkpoint", f"checkpoint not found: {path}")
    actual_sha = sha256_file(path)
    if actual_sha != config.checkpoint_sha256:
        raise InlineProbingError(
            "checkpoint_mismatch",
            f"checkpoint sha mismatch: expected={config.checkpoint_sha256}, actual={actual_sha}",
        )
    if config.model_family not in SUPPORTED_FAMILY_POSITIONS:
        raise InlineProbingError("incompatible", f"unsupported model_family={config.model_family}")
    if config.effective_position != SUPPORTED_FAMILY_POSITIONS[config.model_family]:
        raise InlineProbingError("incompatible", "effective_position does not match model family")
    if config.pipeline_parallel_size != 1:
        raise InlineProbingError("incompatible", "pipeline parallel inline probing is not supported")

    payload = torch.load(path, map_location="cpu", weights_only=True)
    if payload.get("schema") not in {
        config.checkpoint_schema,
        LEGACY_CHECKPOINT_SCHEMA,
    }:
        raise InlineProbingError("incompatible", "checkpoint schema mismatch")
    state = payload.get("model_state_dict")
    if not isinstance(state, Mapping):
        raise InlineProbingError("incompatible", "checkpoint missing model_state_dict")
    weight = _get_tensor(state, "probe.weight").to(dtype=torch.float32)
    bias = _get_tensor(state, "probe.bias").to(dtype=torch.float32)
    mean = _get_tensor(state, "input_mean").to(dtype=torch.float32)
    std = _get_tensor(state, "input_std").to(dtype=torch.float32)
    if weight.ndim != 2 or weight.shape[0] != 1 or weight.shape[1] != config.hidden_width:
        raise InlineProbingError("incompatible", "probe weight shape mismatch")
    if mean.numel() != config.hidden_width or std.numel() != config.hidden_width:
        raise InlineProbingError("incompatible", "normalizer shape mismatch")
    if torch.any(std <= 0):
        raise InlineProbingError("incompatible", "normalizer std must be positive")
    return ResolvedProbeCheckpoint(
        config=config,
        weight=weight.reshape(1, config.hidden_width),
        bias=bias.reshape(1),
        mean=mean.reshape(1, config.hidden_width),
        inv_std=std.reshape(1, config.hidden_width).reciprocal(),
    )


def make_capture_spec(
    *,
    request_id: str,
    request_payload: Mapping[str, Any],
    prompt_token_ids: list[int] | None,
    scheduled_start: int,
    scheduled_count: int,
    scheduler_step: int,
    config: InlineProbingConfig,
) -> InlineProbingCaptureSpec | InlineProbingFailure | None:
    try:
        request = InlineProbingRequest.from_mapping(request_payload)
        validate_expected_checkpoint_id(request, config)
        if prompt_token_ids is None:
            raise InlineProbingError("incompatible", "inline probing requires token-id prompts")
        target = len(prompt_token_ids) + config.effective_position
        if target < 0 or target >= len(prompt_token_ids):
            raise InlineProbingError("incompatible", "effective target position outside prompt")
        if not (scheduled_start <= target < scheduled_start + scheduled_count):
            return None
        return InlineProbingCaptureSpec(
            request_id=request_id,
            attempt_id=request.attempt_id,
            target_token_index=target,
            scheduled_start=scheduled_start,
            scheduled_count=scheduled_count,
            scheduler_step=scheduler_step,
            input_attempt_fingerprint=request.input_attempt_fingerprint,
            prompt_token_count=len(prompt_token_ids),
            native_prompt_token_fingerprint=native_prompt_token_fingerprint(prompt_token_ids),
        )
    except Exception as exc:
        return failure_from_exception(request_payload.get("attempt_id", ""), exc)


def score_capture(
    *,
    scorer: InlineLinearProbe,
    config: InlineProbingConfig,
    spec: InlineProbingCaptureSpec,
    hidden_state: torch.Tensor,
    captured_token_id: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    logits, scores = scorer.score_batch(hidden_state.reshape(1, -1))
    latency_ms = (time.perf_counter() - start) * 1000.0
    logit = float(logits[0].detach().cpu())
    score = float(scores[0].detach().cpu())
    if not math.isfinite(logit) or not math.isfinite(score):
        raise InlineProbingError("internal_error", "non-finite probe score")
    return InlineProbingResult(
        schema=RESULT_SCHEMA,
        status="ok",
        request_id=spec.request_id,
        attempt_id=spec.attempt_id,
        score=score,
        logit=logit,
        captured_token_index=spec.target_token_index,
        scheduler_step=spec.scheduler_step,
        chunk_start=spec.scheduled_start,
        chunk_end=spec.scheduled_start + spec.scheduled_count,
        captured_token_id=int(captured_token_id),
        checkpoint_id=config.checkpoint_id,
        input_attempt_fingerprint=spec.input_attempt_fingerprint,
        native_prompt_token_fingerprint=spec.native_prompt_token_fingerprint,
        prompt_token_count=spec.prompt_token_count,
        model_family=config.model_family,
        model_revision=config.model_revision,
        layer=config.target_layer,
        requested_position=config.requested_position,
        effective_position=config.effective_position,
        feature_dtype=str(hidden_state.dtype).replace("torch.", ""),
        scoring_latency_ms=latency_ms,
    ).as_dict()


def failure_from_exception(attempt_id: str, exc: Exception) -> InlineProbingFailure:
    code = exc.code if isinstance(exc, InlineProbingError) else "internal_error"
    return InlineProbingFailure(code=code, message=str(exc), attempt_id=attempt_id)


def validate_expected_checkpoint_id(
    request: InlineProbingRequest, config: InlineProbingConfig
) -> None:
    if request.expected_checkpoint_id != config.checkpoint_id:
        raise InlineProbingError("checkpoint_mismatch", "expected checkpoint does not match server")


def native_prompt_token_fingerprint(token_ids: list[int]) -> str:
    h = hashlib.sha256()
    for token_id in token_ids:
        h.update(int(token_id).to_bytes(8, byteorder="little", signed=True))
    return f"sha256:{h.hexdigest()}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _valid_sha256_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(c in "0123456789abcdef" for c in value[7:])
    )


def _get_tensor(state: Mapping[str, Any], key: str) -> torch.Tensor:
    value = state.get(key)
    if not isinstance(value, torch.Tensor):
        raise InlineProbingError("incompatible", f"checkpoint missing tensor {key}")
    return value
