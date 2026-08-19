"""Core SafeGauge detector used directly by the ProspectMonitor backend."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from openai import OpenAI
from transformers import AutoTokenizer


REASONING_PREFIX = {
    "deepseek_r1": "<think>\n</think>",
    "qwen3": "</think>\n\n",
    "none": "",
}


class BinaryMlp(nn.Module):
    """Small binary classifier used by a trained SafeGauge model."""

    def __init__(
        self,
        input_dim: int,
        hidden_dims: tuple[int, ...] = (16,),
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dims = tuple(int(dim) for dim in hidden_dims)
        self.dropout = float(dropout)
        layers: list[nn.Module] = []
        previous_dim = input_dim
        for hidden_dim in self.hidden_dims:
            layers.extend((nn.Linear(previous_dim, hidden_dim), nn.ReLU()))
            if self.dropout:
                layers.append(nn.Dropout(self.dropout))
            previous_dim = hidden_dim
        layers.append(nn.Linear(previous_dim, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.net(inputs)

    @classmethod
    def load(cls, path: str | Path, map_location: str) -> "BinaryMlp":
        checkpoint = torch.load(path, map_location=map_location)
        model = cls(
            input_dim=int(checkpoint["input_dim"]),
            hidden_dims=tuple(checkpoint.get("hidden_dims", (16,))),
            dropout=float(checkpoint.get("dropout", 0.0)),
        )
        model.load_state_dict(checkpoint["state_dict"])
        model.to(map_location)
        model.eval()
        return model


def _as_token_ids(value: Any) -> list[int]:
    if hasattr(value, "get"):
        value = value["input_ids"]
    if value and isinstance(value[0], list):
        value = value[0]
    return list(value)


@dataclass(frozen=True)
class SafeGaugePrefillPlan:
    prompt_tokens: list[int]
    prefill_length: int
    target_token_index: int
    request_payload: dict[str, Any]


class LogProbsPrompt:
    """Extract log probabilities for a metadata-defined assistant suffix."""

    def __init__(
        self,
        reasoning_prefix: str,
        base_url: str | None = None,
        api_key: str = "none",
        model: str | None = None,
        tokenizer_path: str | None = None,
        llm: Any = None,
        timeout: float = 120.0,
    ) -> None:
        self.reasoning_prefix = reasoning_prefix
        self.model = model
        self.model_root: str | None = None
        self.client: OpenAI | None = None
        self.llm = llm

        if base_url:
            self.mode = "server"
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            self._load_server_info()
        elif llm is not None:
            self.mode = "offline"
            self.model_root = llm.llm_engine.model_config.model
        else:
            raise ValueError("Must provide either --base-url or --model-dir")

        resolved_tokenizer = tokenizer_path or self.model_root
        if not resolved_tokenizer:
            raise ValueError(
                "Could not determine tokenizer path from the model server; "
                "pass --tokenizer-path explicitly"
            )
        self.tokenizer = AutoTokenizer.from_pretrained(
            resolved_tokenizer,
            trust_remote_code=True,
        )

    def _load_server_info(self) -> None:
        assert self.client is not None
        models = self.client.models.list()
        if not models.data:
            raise RuntimeError("The vLLM server returned an empty model list")

        server_model = models.data[0]
        self.model = self.model or server_model.id
        self.model_root = getattr(server_model, "root", None)

        permissions = getattr(server_model, "permission", []) or []
        if permissions:
            permission = permissions[0]
            if not isinstance(permission, dict):
                permission = vars(permission)
            if permission.get("allow_logprobs") is False:
                raise PermissionError(f"Model {self.model!r} does not allow logprobs")

    def apply_prefill(self, messages: list[dict[str, str]], suffix: str) -> list[dict[str, str]]:
        suffix_tokens = self.tokenizer.encode(suffix, add_special_tokens=False)
        result = copy.deepcopy(messages)
        result.append(
            {
                "role": "assistant",
                "content": self.reasoning_prefix + self.tokenizer.decode(suffix_tokens),
            }
        )
        return result

    def get_logprobs(self, messages: list[dict[str, str]], logprobs_num: int = 2) -> list[float]:
        context_tokens, prefill_tokens = self._build_prompt_tokens(messages)
        prompt_tokens = context_tokens + prefill_tokens

        if self.mode == "server":
            return self._get_server_logprobs(prompt_tokens, len(prefill_tokens), logprobs_num)
        return self._get_offline_logprobs(prompt_tokens, len(prefill_tokens), logprobs_num)

    def prepare_fused_request(
        self,
        messages: list[dict[str, str]],
        *,
        logprobs_num: int,
    ) -> SafeGaugePrefillPlan:
        if self.mode != "server" or self.client is None or self.model is None:
            raise RuntimeError("fused SafeGauge/Inline Probing requires server mode")
        context_tokens, prefill_tokens = self._build_prompt_tokens(messages)
        if not context_tokens or not prefill_tokens:
            raise RuntimeError("fused prefill requires non-empty context and suffix tokens")
        prompt_tokens = context_tokens + prefill_tokens
        request_payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt_tokens,
            "max_tokens": 1,
            "temperature": 0,
            "top_p": 0.95,
            "prompt_logprobs": int(logprobs_num),
            "return_token_ids": True,
            "add_special_tokens": False,
            # A unique salt prevents the target activation from being skipped by
            # prefix caching. The target can be earlier than the suffix tail.
            "cache_salt": f"perspective-watch-fused-{uuid.uuid4()}",
        }
        return SafeGaugePrefillPlan(
            prompt_tokens=prompt_tokens,
            prefill_length=len(prefill_tokens),
            target_token_index=len(context_tokens) - 1,
            request_payload=request_payload,
        )

    def execute_fused_request(
        self,
        plan: SafeGaugePrefillPlan,
        request_payload: dict[str, Any],
    ) -> tuple[list[float], dict[str, Any]]:
        assert self.client is not None
        inline_request = request_payload.get("inline_probing_request")
        if not isinstance(inline_request, dict):
            raise ValueError("fused request is missing inline_probing_request")
        response = self.client.completions.create(
            model=str(request_payload["model"]),
            prompt=list(request_payload["prompt"]),
            max_tokens=int(request_payload["max_tokens"]),
            temperature=float(request_payload["temperature"]),
            top_p=float(request_payload["top_p"]),
            extra_body={
                "prompt_logprobs": int(request_payload["prompt_logprobs"]),
                "return_token_ids": True,
                "add_special_tokens": False,
                "cache_salt": str(request_payload["cache_salt"]),
                "inline_probing_request": inline_request,
            },
        )
        choice = response.choices[0]
        prompt_token_ids = getattr(choice, "prompt_token_ids", None)
        if prompt_token_ids is None or list(prompt_token_ids) != plan.prompt_tokens:
            raise RuntimeError("vLLM fused prefill token IDs do not match SafeGauge input")
        token_entries = getattr(choice, "prompt_logprobs", None)
        if token_entries is None:
            raise RuntimeError("vLLM fused prefill did not return prompt_logprobs")
        raw_logprobs = [
            _first_logprob(entry)
            for entry in token_entries[-plan.prefill_length :]
        ]
        return raw_logprobs, response.model_dump(mode="json")

    def _build_prompt_tokens(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[list[int], list[int]]:
        context_tokens = self.tokenizer.apply_chat_template(
            messages[:-1],
            tokenize=True,
            add_generation_prompt=True,
        )
        prefill_tokens = self.tokenizer.encode(
            messages[-1]["content"],
            add_special_tokens=False,
        )
        return _as_token_ids(context_tokens), _as_token_ids(prefill_tokens)

    def _get_server_logprobs(
        self,
        prompt_tokens: list[int],
        prefill_length: int,
        logprobs_num: int,
    ) -> list[float]:
        assert self.client is not None and self.model is not None
        response = self.client.completions.create(
            model=self.model,
            prompt=prompt_tokens,
            max_tokens=1,
            temperature=0,
            top_p=0.95,
            extra_body={"prompt_logprobs": logprobs_num},
        )
        token_entries = response.choices[0].prompt_logprobs[-prefill_length:]
        return [_first_logprob(entry) for entry in token_entries]

    def _get_offline_logprobs(
        self,
        prompt_tokens: list[int],
        prefill_length: int,
        logprobs_num: int,
    ) -> list[float]:
        from vllm import SamplingParams

        output = self.llm.generate(
            prompts=[prompt_tokens],
            sampling_params=SamplingParams(
                temperature=0,
                max_tokens=1,
                prompt_logprobs=logprobs_num,
                logprobs=logprobs_num,
            ),
        )[0]
        token_entries = output.prompt_logprobs[-prefill_length:]
        return [_first_logprob(entry) for entry in token_entries]


def _first_logprob(entry: Any) -> float:
    if entry is None:
        return -10.0
    token_info = next(iter(entry.values()))
    if isinstance(token_info, dict):
        value = token_info.get("logprob")
    else:
        value = getattr(token_info, "logprob", None)
    return float(value) if value is not None else -10.0


class SafeGaugeDetector:
    """Metadata-driven prefill logprobs and binary-model inference pipeline."""

    def __init__(
        self,
        processor_path: str,
        base_url: str | None = None,
        api_key: str = "none",
        model: str | None = None,
        tokenizer_path: str | None = None,
        llm: Any = None,
        device: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        checkpoint_path = Path(processor_path)
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"Processor checkpoint not found: {checkpoint_path}")

        meta_path = checkpoint_path.with_suffix(".meta.json")
        if not meta_path.is_file():
            raise FileNotFoundError(f"Processor metadata not found: {meta_path}")

        self.meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._validate_meta(meta_path)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.mlp_model = BinaryMlp.load(checkpoint_path, map_location=self.device)
        meta_input_dim = int(self.meta["input_dim"])
        if meta_input_dim != self.mlp_model.input_dim:
            raise ValueError(
                f"Metadata input_dim={meta_input_dim} does not match checkpoint "
                f"input_dim={self.mlp_model.input_dim}"
            )
        self.logprobs_extractor = LogProbsPrompt(
            reasoning_prefix=resolve_reasoning_prefix(self.meta),
            base_url=base_url,
            api_key=api_key,
            model=model,
            tokenizer_path=tokenizer_path,
            llm=llm,
            timeout=timeout,
        )

    def _validate_meta(self, meta_path: Path) -> None:
        required_fields = ("task", "suffix", "input_dim")
        missing = [field for field in required_fields if self.meta.get(field) in (None, "")]
        if missing:
            raise ValueError(f"Missing required metadata fields in {meta_path}: {', '.join(missing)}")
        if not isinstance(self.meta["suffix"], str):
            raise ValueError(f"Metadata suffix must be a string: {meta_path}")

    def detect(
        self,
        messages: list[dict[str, str]],
        threshold_override: float | None = None,
    ) -> dict[str, Any]:
        if not messages:
            raise ValueError("messages must not be empty")

        prefilled_messages = self.logprobs_extractor.apply_prefill(messages, self.meta["suffix"])
        raw_logprobs = self.logprobs_extractor.get_logprobs(
            prefilled_messages,
            logprobs_num=int(self.meta.get("logprobs_num", 2)),
        )

        return self._score_logprobs(raw_logprobs, threshold_override)

    def prepare_fused_request(
        self,
        messages: list[dict[str, str]],
    ) -> SafeGaugePrefillPlan:
        if not messages:
            raise ValueError("messages must not be empty")
        prefilled_messages = self.logprobs_extractor.apply_prefill(
            messages, self.meta["suffix"]
        )
        return self.logprobs_extractor.prepare_fused_request(
            prefilled_messages,
            logprobs_num=int(self.meta.get("logprobs_num", 2)),
        )

    def detect_fused(
        self,
        plan: SafeGaugePrefillPlan,
        request_payload: dict[str, Any],
        threshold_override: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raw_logprobs, response = self.logprobs_extractor.execute_fused_request(
            plan, request_payload
        )
        return self._score_logprobs(raw_logprobs, threshold_override), response

    def _score_logprobs(
        self,
        raw_logprobs: list[float],
        threshold_override: float | None,
    ) -> dict[str, Any]:

        input_dim = int(self.meta.get("input_dim", 20))
        values = np.asarray(raw_logprobs[:input_dim], dtype=np.float32)
        if len(values) < input_dim:
            pad_value = float(self.meta.get("pad_value", -10.0))
            values = np.pad(values, (0, input_dim - len(values)), constant_values=pad_value)
        features = torch.from_numpy(values).unsqueeze(0).to(self.device)

        with torch.inference_mode():
            probability = torch.sigmoid(self.mlp_model(features)).item()

        threshold = float(
            threshold_override if threshold_override is not None else self.meta.get("best_threshold", 0.5)
        )
        positive_label = str(self.meta.get("positive_label", "positive"))
        negative_label = str(self.meta.get("negative_label", "negative"))
        positive = probability > threshold
        positive_is_risk = bool(self.meta.get("positive_is_risk", True))
        return {
            "task": str(self.meta["task"]),
            "label": positive_label if positive else negative_label,
            "probability": round(probability, 6),
            "threshold": threshold,
            "positive": positive,
            "risky": positive if positive_is_risk else not positive,
            "logprobs": [float(value) for value in raw_logprobs[:input_dim]],
        }

    def get_model_info(self) -> dict[str, Any]:
        extractor = self.logprobs_extractor
        return {
            "model_name": extractor.model or extractor.model_root,
            "mode": extractor.mode,
            "device": self.device,
            "meta": self.meta,
        }


def resolve_reasoning_prefix(meta: dict[str, Any]) -> str:
    explicit_prefix = meta.get("reasoning_prefix")
    if explicit_prefix is not None:
        if not isinstance(explicit_prefix, str):
            raise ValueError("Metadata reasoning_prefix must be a string")
        return explicit_prefix

    reasoning_parser = str(meta.get("reasoning_parser", "none"))
    prefix = REASONING_PREFIX.get(reasoning_parser)
    if prefix is None:
        raise ValueError(f"Unknown reasoning_parser in metadata: {reasoning_parser}")
    return prefix
