#!/usr/bin/env python3
"""Serve the trained FinVault and prompt-extraction Activation Probes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "qwen3-32b"
MODEL_SPECS = {
    "qwen3-8b": {
        "hidden_size": 4096,
        "finvault_checkpoint": ROOT / "results/activation_probe/finvault-qwen3-8b/best_probe.pt",
        "prompt_checkpoint": (
            ROOT / "results/activation_probe/prompt-extraction-qwen3-8b/probe/best_probe.pt"
        ),
    },
    "qwen3-32b": {
        "hidden_size": 5120,
        "finvault_checkpoint": ROOT / "results/activation_probe/finvault-qwen3-32b/best_probe.pt",
        "prompt_checkpoint": (
            ROOT / "results/activation_probe/prompt-extraction-qwen3-32b/probe/best_probe.pt"
        ),
    },
}


class DetectRequest(BaseModel):
    system_prompt: str = Field(min_length=1)
    user_message: str = Field(min_length=1)
    scenario_category: Literal["finvault", "prompt"]
    model: str = "qwen3-32b"


class ActivationProbeRuntime:
    def __init__(
        self,
        *,
        finvault_checkpoint: Path,
        prompt_checkpoint: Path,
        model_path: Path,
        model_name: str,
        device_map: str,
        max_length: int,
    ) -> None:
        self.model_name = _canonical_model_name(model_name)
        self.finvault_checkpoint_path = finvault_checkpoint.resolve()
        self.prompt_checkpoint_path = prompt_checkpoint.resolve()
        self.device_map = device_map
        self.max_length = max_length
        self.finvault_checkpoint = torch.load(
            self.finvault_checkpoint_path,
            map_location="cpu",
            weights_only=False,
        )
        self.prompt_checkpoint = torch.load(
            self.prompt_checkpoint_path,
            map_location="cpu",
            weights_only=False,
        )
        self._validate_checkpoint_dimensions()
        self.model_path = self._resolve_model_path(model_path)
        self.checkpoint_ids = {
            "finvault": f"sha256:{_sha256_file(self.finvault_checkpoint_path)}",
            "prompt": f"sha256:{_sha256_file(self.prompt_checkpoint_path)}",
        }
        self._model = None
        self._tokenizer = None
        self._input_device = None
        self._load_lock = threading.Lock()
        self._predict_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    def load(self) -> None:
        if self.loaded:
            return
        with self._load_lock:
            if self.loaded:
                return
            tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                local_files_only=True,
                trust_remote_code=True,
            )
            if tokenizer.pad_token_id is None:
                tokenizer.pad_token = tokenizer.eos_token
            model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                local_files_only=True,
                trust_remote_code=True,
                dtype=torch.bfloat16,
                device_map=self.device_map,
                low_cpu_mem_usage=True,
            )
            model.eval()
            model.config.use_cache = False
            self._tokenizer = tokenizer
            self._model = model
            self._input_device = model.model.embed_tokens.weight.device

    def detect(self, request: DetectRequest) -> dict[str, Any]:
        if _canonical_model_name(request.model) != self.model_name:
            raise ValueError(
                f"Activation Probe service loaded {self.model_name} checkpoints, "
                f"got model={request.model!r}"
            )
        self.load()
        with self._predict_lock:
            if request.scenario_category == "finvault":
                return self._detect_finvault(request)
            return self._detect_prompt_extraction(request)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready" if self.loaded else "loading",
            "loaded": self.loaded,
            "model": self.model_name,
            "model_path": _project_relative(self.model_path),
            "device_map": self.device_map,
            "checkpoints": {
                "finvault": {
                    "path": _project_relative(self.finvault_checkpoint_path),
                    "checkpoint_id": self.checkpoint_ids["finvault"],
                    "layer": int(self.finvault_checkpoint["layer"]),
                },
                "prompt": {
                    "path": _project_relative(self.prompt_checkpoint_path),
                    "checkpoint_id": self.checkpoint_ids["prompt"],
                    "layers": [
                        int(self.prompt_checkpoint["start_layer"]),
                        int(self.prompt_checkpoint["end_layer"]),
                    ],
                    "feature_type": str(self.prompt_checkpoint["feature_type"]),
                },
            },
        }

    def _detect_finvault(self, request: DetectRequest) -> dict[str, Any]:
        checkpoint = self.finvault_checkpoint
        layer_index = int(checkpoint["layer"])
        captured: torch.Tensor | None = None

        def capture(_module: Any, _inputs: Any, output: Any) -> None:
            nonlocal captured
            tensor = output[0] if isinstance(output, (tuple, list)) else output
            captured = tensor[:, -1, :].detach().float().cpu()

        handle = self._model.model.layers[layer_index].register_forward_hook(capture)
        try:
            self._forward(request)
        finally:
            handle.remove()
        if captured is None:
            raise RuntimeError("FinVault activation hook did not capture a feature")

        mean = checkpoint["mean"].float().reshape(1, -1)
        std = checkpoint["std"].float().clamp_min(1e-5).reshape(1, -1)
        weight = checkpoint["weight"].float().reshape(-1)
        bias = checkpoint["bias"].float()
        normalized = (captured - mean) / std
        logit = float((normalized @ weight + bias).item())
        return self._response(
            category="finvault",
            logit=logit,
            logit_threshold=float(checkpoint["threshold"]),
            layer=layer_index,
            detail={"feature_type": "residual_stream", "layers": [layer_index]},
        )

    def _detect_prompt_extraction(self, request: DetectRequest) -> dict[str, Any]:
        checkpoint = self.prompt_checkpoint
        feature_type = str(checkpoint["feature_type"])
        start_layer = int(checkpoint["start_layer"])
        end_layer = int(checkpoint["end_layer"])
        captured: dict[int, torch.Tensor] = {}
        handles = []

        def make_hook(layer_index: int):
            def capture(_module: Any, _inputs: Any, output: Any) -> None:
                tensor = output[0] if isinstance(output, (tuple, list)) else output
                captured[layer_index] = tensor[:, -1, :].detach().float().cpu()

            return capture

        for layer_index in range(start_layer, end_layer + 1):
            layer = self._model.model.layers[layer_index]
            module = layer.self_attn if feature_type == "attn" else layer.mlp
            handles.append(module.register_forward_hook(make_hook(layer_index)))
        try:
            self._forward(request)
        finally:
            for handle in handles:
                handle.remove()

        missing = [index for index in range(start_layer, end_layer + 1) if index not in captured]
        if missing:
            raise RuntimeError(f"Prompt-extraction activation hooks missed layers: {missing}")
        activations = torch.stack(
            [captured[index] for index in range(start_layer, end_layer + 1)],
            dim=1,
        )
        normalized = (
            activations - checkpoint["mean"].float()
        ) / checkpoint["std"].float().clamp_min(1e-5)
        weight = checkpoint["weight"].float().reshape(-1)
        bias = checkpoint["bias"].float()
        logit = float((normalized.flatten(1) @ weight + bias).item())
        return self._response(
            category="prompt",
            logit=logit,
            logit_threshold=float(checkpoint["threshold"]),
            layer=end_layer,
            detail={
                "feature_type": feature_type,
                "layers": list(range(start_layer, end_layer + 1)),
            },
        )

    def _forward(self, request: DetectRequest) -> None:
        text = self._tokenizer.apply_chat_template(
            [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_message},
            ],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        encoded = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
            # The published FinVault checkpoint was trained on already-templated
            # actual traces, while prompt extraction used the tokenizer default.
            add_special_tokens=request.scenario_category == "prompt",
        )
        sequence_length = int(encoded["attention_mask"].sum().item())
        if sequence_length >= self.max_length:
            raise ValueError(f"Activation Probe input reached max_length={self.max_length}")
        inputs = {key: value.to(self._input_device) for key, value in encoded.items()}
        with torch.inference_mode():
            self._model(**inputs, use_cache=False)

    def _response(
        self,
        *,
        category: str,
        logit: float,
        logit_threshold: float,
        layer: int,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        score = _sigmoid(logit)
        threshold = _sigmoid(logit_threshold)
        return {
            "schema": "perspective_watch.activation_probe.result.v1",
            "protocol": "activation_probe.runtime.v1",
            "task": "high_risk_task" if category == "finvault" else "system_prompt_extraction",
            "score": score,
            "logit": logit,
            "threshold": threshold,
            "logit_threshold": logit_threshold,
            "risky": logit >= logit_threshold,
            "checkpoint_id": self.checkpoint_ids[category],
            "layer": layer,
            **detail,
        }

    def _resolve_model_path(self, configured_path: Path) -> Path:
        model_path = configured_path.expanduser().resolve()
        config_path = model_path / "config.json"
        if not config_path.is_file():
            raise FileNotFoundError(f"Activation Probe model snapshot not found: {model_path}")
        model_config = json.loads(config_path.read_text(encoding="utf-8"))
        expected = int(MODEL_SPECS[self.model_name]["hidden_size"])
        actual = int(model_config.get("hidden_size") or 0)
        if actual != expected:
            raise ValueError(
                f"Activation Probe model width mismatch for {self.model_name}: "
                f"expected={expected}, model_config={actual}"
            )
        return model_path

    def _validate_checkpoint_dimensions(self) -> None:
        expected = int(MODEL_SPECS[self.model_name]["hidden_size"])
        finvault_width = int(self.finvault_checkpoint["mean"].numel())
        prompt_width = int(self.prompt_checkpoint["mean"].shape[-1])
        if finvault_width != expected or prompt_width != expected:
            raise ValueError(
                f"Activation Probe checkpoint width mismatch for {self.model_name}: "
                f"expected={expected}, finvault={finvault_width}, prompt={prompt_width}"
            )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _normalize_model_name(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _canonical_model_name(value: str) -> str:
    normalized = _normalize_model_name(Path(value.rstrip("/")).name)
    aliases = {
        "qwen38b": "qwen3-8b",
        "qwen332b": "qwen3-32b",
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        raise ValueError(
            f"Unsupported Activation Probe model {value!r}; "
            f"expected one of: {', '.join(MODEL_SPECS)}"
        ) from error


def build_app(runtime: ActivationProbeRuntime, *, eager_load: bool) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if eager_load:
            await asyncio.to_thread(runtime.load)
        yield

    app = FastAPI(title="Perspective Watch Activation Probe", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return runtime.health()

    @app.post("/detect")
    async def detect(request: DetectRequest):
        try:
            return await asyncio.to_thread(runtime.detect, request)
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=tuple(MODEL_SPECS), default=DEFAULT_MODEL)
    parser.add_argument("--finvault-checkpoint", type=Path)
    parser.add_argument("--prompt-checkpoint", type=Path)
    parser.add_argument(
        "--model-path",
        type=Path,
        required=True,
        help="Local Qwen3 model directory (runtime configuration, never read from checkpoint metadata).",
    )
    parser.add_argument("--device-map", default="balanced")
    parser.add_argument("--max-length", type=int, default=8192)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument("--lazy-load", action="store_true")
    return parser.parse_args()


def main() -> None:
    import uvicorn

    args = parse_args()
    model_spec = MODEL_SPECS[args.model]
    runtime = ActivationProbeRuntime(
        finvault_checkpoint=args.finvault_checkpoint or model_spec["finvault_checkpoint"],
        prompt_checkpoint=args.prompt_checkpoint or model_spec["prompt_checkpoint"],
        model_path=args.model_path,
        model_name=args.model,
        device_map=args.device_map,
        max_length=args.max_length,
    )
    uvicorn.run(build_app(runtime, eager_load=not args.lazy_load), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
