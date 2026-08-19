# SPDX-License-Identifier: Apache-2.0
"""Runtime contracts and probe scoring for vLLM inline_probing."""

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
ACTIVATION_CHECKPOINT_SCHEMA = "perspective_watch.activation_probe.checkpoint.v1"
ACTIVATION_MULTILAYER_CHECKPOINT_SCHEMA = (
    "perspective_watch.activation_probe_checkpoint.v2"
)
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
    probe_id: str = "default"
    task: str = ""
    decision_threshold: float | None = None
    target_layers: tuple[int, ...] | list[int] | None = None

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
        if config.checkpoint_schema not in {
            CHECKPOINT_SCHEMA,
            ACTIVATION_CHECKPOINT_SCHEMA,
            ACTIVATION_MULTILAYER_CHECKPOINT_SCHEMA,
        }:
            raise InlineProbingError("incompatible", "unsupported checkpoint schema")
        if config.scorer_contract_version != SCORER_CONTRACT:
            raise InlineProbingError("incompatible", "unsupported scorer contract")
        if not config.probe_id.strip():
            raise InlineProbingError("incompatible", "probe_id must be non-empty")
        if config.decision_threshold is not None and not (
            0.0 <= config.decision_threshold <= 1.0
        ):
            raise InlineProbingError(
                "incompatible", "decision_threshold must be between 0 and 1"
            )
        if config.target_layers is not None:
            layers = tuple(int(value) for value in config.target_layers)
            if not layers or tuple(sorted(set(layers))) != layers:
                raise InlineProbingError(
                    "incompatible", "target_layers must be sorted and unique"
                )
            if layers[-1] != config.target_layer:
                raise InlineProbingError(
                    "incompatible", "target_layer must be the final target_layers entry"
                )
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

    @property
    def aux_hidden_state_layers(self) -> tuple[int, ...]:
        """Return every vLLM auxiliary layer required by this checkpoint."""
        layers = self.target_layers or (self.target_layer,)
        return tuple(int(layer) + 1 for layer in layers)


@dataclass(frozen=True)
class InlineProbingRequest:
    schema: str
    required: bool
    logical_request_id: str
    attempt_id: str
    expected_checkpoint_id: str
    input_attempt_fingerprint: str
    deadline_ms: int
    target_token_index: int | None = None
    probe_id: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InlineProbingRequest":
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
                f"probe request fields mismatch; missing={sorted(missing)}, "
                f"unknown={sorted(unknown)}",
            )
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
        if request.target_token_index is not None and (
            isinstance(request.target_token_index, bool)
            or not isinstance(request.target_token_index, int)
            or request.target_token_index < 0
        ):
            raise InlineProbingError(
                "incompatible", "target_token_index must be a non-negative integer"
            )
        if request.probe_id is not None and not request.probe_id.strip():
            raise InlineProbingError("incompatible", "probe_id must be non-empty")
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
    probe_id: str = "default"
    aux_hidden_state_layer: int = -1


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
    layers: tuple[int, ...] | list[int] | None = None
    classifier_type: str = "linear"
    requested_position: int = -1
    effective_position: int = -1
    feature_dtype: str = "model"
    accumulation_dtype: str = "float32"
    normalization: str = "checkpoint"
    scoring_latency_ms: float = 0.0
    probe_id: str = "default"
    task: str = ""
    threshold: float | None = None
    risky: bool | None = None

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
    mean: torch.Tensor
    inv_std: torch.Tensor
    layer_indices: tuple[int, ...]
    classifier_type: str
    weight: torch.Tensor | None = None
    bias: torch.Tensor | None = None
    architecture: Mapping[str, Any] | None = None
    state_dict: Mapping[str, torch.Tensor] | None = None


class InlineLinearProbe:
    def __init__(self, checkpoint: ResolvedProbeCheckpoint, device: torch.device):
        self.checkpoint = checkpoint
        if checkpoint.weight is None or checkpoint.bias is None:
            raise InlineProbingError(
                "incompatible", "linear checkpoint is missing weight or bias"
            )
        self.weight = checkpoint.weight.to(device=device, dtype=torch.float32)
        self.bias = checkpoint.bias.to(device=device, dtype=torch.float32)
        self.mean = checkpoint.mean.to(device=device, dtype=torch.float32)
        self.inv_std = checkpoint.inv_std.to(device=device, dtype=torch.float32)

    def score_batch(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = features.to(dtype=torch.float32)
        x = (x - self.mean) * self.inv_std
        logits = torch.nn.functional.linear(x, self.weight, self.bias).flatten()
        return logits, torch.sigmoid(logits)


class InlineMultilayerMLPProbe:
    """Score concatenated, standardized residuals with the v16 MLP."""

    def __init__(self, checkpoint: ResolvedProbeCheckpoint, device: torch.device):
        if checkpoint.architecture is None or checkpoint.state_dict is None:
            raise InlineProbingError(
                "incompatible", "MLP checkpoint is missing architecture or state_dict"
            )
        self.checkpoint = checkpoint
        self.mean = checkpoint.mean.to(device=device, dtype=torch.float32)
        self.inv_std = checkpoint.inv_std.to(device=device, dtype=torch.float32)
        architecture = checkpoint.architecture
        input_size = int(architecture.get("input_size", 0))
        hidden_sizes = [int(value) for value in architecture.get("hidden_sizes", [])]
        if input_size <= 0 or not hidden_sizes:
            raise InlineProbingError("incompatible", "invalid MLP architecture")
        modules: list[torch.nn.Module] = [
            torch.nn.LayerNorm(input_size, elementwise_affine=False)
        ]
        previous = input_size
        for hidden_size in hidden_sizes:
            modules.extend(
                [
                    torch.nn.Linear(previous, hidden_size),
                    torch.nn.GELU(),
                    torch.nn.Dropout(float(architecture.get("dropout", 0.0))),
                ]
            )
            previous = hidden_size
        modules.append(torch.nn.Linear(previous, 1))
        self.network = torch.nn.Sequential(*modules).to(device=device)
        network_state = {
            key.removeprefix("network."): value
            for key, value in checkpoint.state_dict.items()
        }
        self.network.load_state_dict(network_state)
        self.network.eval()

    def score_batch(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = features.to(dtype=torch.float32)
        expected = (len(self.checkpoint.layer_indices), self.mean.shape[-1])
        if x.ndim != 3 or tuple(x.shape[1:]) != expected:
            raise InlineProbingError(
                "incompatible",
                f"multilayer feature shape mismatch: expected [batch,{expected[0]},{expected[1]}]",
            )
        x = ((x - self.mean) * self.inv_std).flatten(1)
        with torch.inference_mode():
            logits = self.network(x).flatten()
        return logits, torch.sigmoid(logits)


def build_probe_scorer(
    checkpoint: ResolvedProbeCheckpoint, device: torch.device
) -> InlineLinearProbe | InlineMultilayerMLPProbe:
    if checkpoint.classifier_type == "linear":
        return InlineLinearProbe(checkpoint, device)
    if checkpoint.classifier_type == "multilayer_mlp":
        return InlineMultilayerMLPProbe(checkpoint, device)
    raise InlineProbingError(
        "incompatible", f"unsupported classifier_type={checkpoint.classifier_type}"
    )


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


def load_configs_from_env() -> dict[str, InlineProbingConfig]:
    """Load either the legacy single config or a multi-probe registry."""

    raw = os.environ.get("INLINE_PROBING_CONFIGS")
    if not raw:
        config = load_config_from_env()
        return {} if config is None else {config.probe_id: config}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InlineProbingError(
            "incompatible", "INLINE_PROBING_CONFIGS is not JSON"
        ) from exc
    if isinstance(value, Mapping):
        value = value.get("probes")
    if not isinstance(value, list) or not value:
        raise InlineProbingError(
            "incompatible", "INLINE_PROBING_CONFIGS must be a non-empty list"
        )

    configs: dict[str, InlineProbingConfig] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise InlineProbingError(
                "incompatible", "each probe config must be an object"
            )
        config = InlineProbingConfig.from_mapping(item)
        if config.probe_id in configs:
            raise InlineProbingError(
                "incompatible", f"duplicate probe_id={config.probe_id}"
            )
        configs[config.probe_id] = config

    compatibility = {
        (
            config.model_family,
            config.model_revision,
            config.hidden_width,
            config.tensor_parallel_size,
            config.pipeline_parallel_size,
        )
        for config in configs.values()
    }
    if len(compatibility) != 1:
        raise InlineProbingError(
            "incompatible", "all registered probes must target the same model runtime"
        )
    return configs


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

    payload = _load_checkpoint_payload(config)
    if config.checkpoint_schema == ACTIVATION_MULTILAYER_CHECKPOINT_SCHEMA:
        return _load_multilayer_activation_checkpoint(payload, config)
    if config.checkpoint_schema == ACTIVATION_CHECKPOINT_SCHEMA:
        weight, bias, mean, std = _load_activation_probe_tensors(payload, config)
    else:
        if payload.get("schema") not in {
            config.checkpoint_schema,
            LEGACY_CHECKPOINT_SCHEMA,
        }:
            raise InlineProbingError("incompatible", "checkpoint schema mismatch")
        state = payload.get("model_state_dict")
        if not isinstance(state, Mapping):
            raise InlineProbingError(
                "incompatible", "checkpoint missing model_state_dict"
            )
        weight = _get_tensor(state, "probe.weight").to(dtype=torch.float32)
        bias = _get_tensor(state, "probe.bias").to(dtype=torch.float32)
        mean = _get_tensor(state, "input_mean").to(dtype=torch.float32)
        std = _get_tensor(state, "input_std").to(dtype=torch.float32)
    if (
        weight.numel() != config.hidden_width
        or weight.ndim not in {1, 2}
        or (weight.ndim == 2 and tuple(weight.shape) != (1, config.hidden_width))
    ):
        raise InlineProbingError("incompatible", "probe weight shape mismatch")
    if mean.numel() != config.hidden_width or std.numel() != config.hidden_width:
        raise InlineProbingError("incompatible", "normalizer shape mismatch")
    if torch.any(std <= 0):
        raise InlineProbingError("incompatible", "normalizer std must be positive")
    return ResolvedProbeCheckpoint(
        config=config,
        mean=mean.reshape(1, config.hidden_width),
        inv_std=std.reshape(1, config.hidden_width).reciprocal(),
        layer_indices=(config.target_layer,),
        classifier_type="linear",
        weight=weight.reshape(1, config.hidden_width),
        bias=bias.reshape(1),
    )


def make_capture_spec(
    *,
    request_id: str,
    request_payload: Mapping[str, Any],
    prompt_token_ids: list[int] | None,
    scheduled_start: int,
    scheduled_count: int,
    scheduler_step: int,
    config: InlineProbingConfig | None = None,
    configs: Mapping[str, InlineProbingConfig] | None = None,
) -> InlineProbingCaptureSpec | InlineProbingFailure | None:
    try:
        request = InlineProbingRequest.from_mapping(request_payload)
        selected_config = select_request_config(
            request,
            config=config,
            configs=configs,
        )
        validate_expected_checkpoint_id(request, selected_config)
        if prompt_token_ids is None:
            raise InlineProbingError("incompatible", "inline probing requires token-id prompts")
        target = (
            request.target_token_index
            if request.target_token_index is not None
            else len(prompt_token_ids) + selected_config.effective_position
        )
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
            probe_id=selected_config.probe_id,
            aux_hidden_state_layer=selected_config.aux_hidden_state_layers[-1],
        )
    except Exception as exc:
        return failure_from_exception(request_payload.get("attempt_id", ""), exc)


def score_capture(
    *,
    scorer: InlineLinearProbe | InlineMultilayerMLPProbe,
    config: InlineProbingConfig,
    spec: InlineProbingCaptureSpec,
    hidden_state: torch.Tensor,
    captured_token_id: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    features = (
        hidden_state.unsqueeze(0)
        if isinstance(scorer, InlineMultilayerMLPProbe)
        else hidden_state.reshape(1, -1)
    )
    logits, scores = scorer.score_batch(features)
    latency_ms = (time.perf_counter() - start) * 1000.0
    logit = float(logits[0].detach().cpu())
    score = float(scores[0].detach().cpu())
    if not math.isfinite(logit) or not math.isfinite(score):
        raise InlineProbingError("internal_error", "non-finite probe score")
    threshold = config.decision_threshold
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
        layers=list(scorer.checkpoint.layer_indices),
        classifier_type=scorer.checkpoint.classifier_type,
        requested_position=config.requested_position,
        effective_position=config.effective_position,
        feature_dtype=str(hidden_state.dtype).replace("torch.", ""),
        scoring_latency_ms=latency_ms,
        probe_id=config.probe_id,
        task=config.task,
        threshold=threshold,
        risky=None if threshold is None else score >= threshold,
    ).as_dict()


def select_request_config(
    request: InlineProbingRequest,
    *,
    config: InlineProbingConfig | None,
    configs: Mapping[str, InlineProbingConfig] | None,
) -> InlineProbingConfig:
    registry = dict(configs or {})
    if config is not None:
        registry.setdefault(config.probe_id, config)
    if not registry:
        raise InlineProbingError("not_configured", "no probe is configured")
    if request.probe_id is not None:
        selected = registry.get(request.probe_id)
        if selected is None:
            raise InlineProbingError(
                "unknown_probe", f"probe_id={request.probe_id} is not loaded"
            )
        return selected

    checkpoint_matches = [
        candidate
        for candidate in registry.values()
        if candidate.checkpoint_id == request.expected_checkpoint_id
    ]
    if len(checkpoint_matches) == 1:
        return checkpoint_matches[0]
    if len(registry) == 1:
        return next(iter(registry.values()))
    raise InlineProbingError(
        "probe_id_required", "probe_id is required when multiple probes are loaded"
    )


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


def _load_checkpoint_payload(config: InlineProbingConfig) -> Mapping[str, Any]:
    payload = torch.load(config.checkpoint_path, map_location="cpu", weights_only=True)
    if not isinstance(payload, Mapping):
        raise InlineProbingError("incompatible", "checkpoint root must be a mapping")
    return payload


def _activation_checkpoint_layers(payload: Mapping[str, Any]) -> tuple[int, ...]:
    values = payload.get("selected_layers") or payload.get("feature_layer_indices")
    if not isinstance(values, (list, tuple)) or not values:
        raise InlineProbingError(
            "incompatible", "multilayer checkpoint is missing selected_layers"
        )
    layers = tuple(int(value) for value in values)
    if tuple(sorted(set(layers))) != layers:
        raise InlineProbingError(
            "incompatible", "multilayer checkpoint layers must be sorted and unique"
        )
    return layers


def _load_multilayer_activation_checkpoint(
    payload: Mapping[str, Any], config: InlineProbingConfig
) -> ResolvedProbeCheckpoint:
    if payload.get("schema") != ACTIVATION_MULTILAYER_CHECKPOINT_SCHEMA:
        raise InlineProbingError("incompatible", "activation checkpoint schema mismatch")
    if payload.get("feature_type") != "residual":
        raise InlineProbingError(
            "incompatible", "multilayer adapter requires residual activations"
        )
    if payload.get("feature_transform", "raw") != "raw":
        raise InlineProbingError(
            "incompatible", "multilayer adapter requires raw features"
        )
    if payload.get("classifier_type") != "multilayer_mlp":
        raise InlineProbingError(
            "incompatible", "v2 activation checkpoint must use multilayer_mlp"
        )
    layers = _activation_checkpoint_layers(payload)
    if layers[-1] != config.target_layer:
        raise InlineProbingError(
            "incompatible",
            f"activation checkpoint final layer={layers[-1]} does not match config layer={config.target_layer}",
        )
    mean = _get_tensor(payload, "mean").to(dtype=torch.float32)
    std = _get_tensor(payload, "std").to(dtype=torch.float32)
    expected_shape = (len(layers), config.hidden_width)
    if tuple(mean.shape) != expected_shape or tuple(std.shape) != expected_shape:
        raise InlineProbingError("incompatible", "multilayer normalizer shape mismatch")
    if torch.any(std <= 0):
        raise InlineProbingError("incompatible", "normalizer std must be positive")
    architecture = payload.get("architecture")
    state_dict = payload.get("state_dict")
    if not isinstance(architecture, Mapping) or not isinstance(state_dict, Mapping):
        raise InlineProbingError(
            "incompatible", "multilayer checkpoint is missing model state"
        )
    if int(architecture.get("input_size", 0)) != len(layers) * config.hidden_width:
        raise InlineProbingError("incompatible", "MLP input size mismatch")
    tensors = {
        str(key): value.to(dtype=torch.float32)
        for key, value in state_dict.items()
        if isinstance(value, torch.Tensor)
    }
    if len(tensors) != len(state_dict):
        raise InlineProbingError("incompatible", "MLP state_dict contains non-tensors")
    return ResolvedProbeCheckpoint(
        config=config,
        mean=mean.unsqueeze(0),
        inv_std=std.clamp_min(1e-5).reciprocal().unsqueeze(0),
        layer_indices=layers,
        classifier_type="multilayer_mlp",
        architecture=dict(architecture),
        state_dict=tensors,
    )


def _load_activation_probe_tensors(
    payload: Mapping[str, Any],
    config: InlineProbingConfig,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    feature_type = str(payload.get("feature_type") or "residual")
    mode = str(payload.get("mode") or "single")
    # New training bundles preserve both a relative candidate-window index and
    # the absolute Transformer block index. Runtime capture always needs the
    # absolute index; legacy checkpoints continue to use start_layer/end_layer.
    start_layer = int(
        payload.get(
            "absolute_start_layer",
            payload.get("start_layer", payload.get("layer", -1)),
        )
    )
    end_layer = int(
        payload.get("absolute_end_layer", payload.get("end_layer", start_layer))
    )
    if feature_type != "residual" or mode != "single" or start_layer != end_layer:
        raise InlineProbingError(
            "incompatible",
            "vLLM Activation Probe adapter requires a single residual layer",
        )
    if start_layer != config.target_layer:
        raise InlineProbingError(
            "incompatible",
            f"activation checkpoint layer={start_layer} does not match "
            f"config layer={config.target_layer}",
        )
    return (
        _get_tensor(payload, "weight").to(dtype=torch.float32),
        _get_tensor(payload, "bias").to(dtype=torch.float32),
        _get_tensor(payload, "mean").to(dtype=torch.float32),
        _get_tensor(payload, "std").to(dtype=torch.float32),
    )
