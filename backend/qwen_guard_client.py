import asyncio
import re
import threading
from dataclasses import dataclass
from time import perf_counter

import httpx

from backend.config import Settings


SAFETY_PATTERN = re.compile(r"Safety:\s*(Safe|Unsafe|Controversial)", re.IGNORECASE)
CATEGORY_PATTERN = re.compile(
    r"(Violent|Non-violent Illegal Acts|Sexual Content or Sexual Acts|PII|Suicide & Self-Harm|"
    r"Unethical Acts|Politically Sensitive Topics|Copyright Violation|Jailbreak|None)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QwenGuardAssessment:
    safety_label: str | None
    categories: list[str]
    raw_output: str
    backend: str
    latency_ms: int
    error: str | None = None

    @property
    def risky(self) -> bool | None:
        if self.safety_label is None:
            return None
        return self.safety_label in {"Unsafe", "Controversial"}

    @property
    def blocked(self) -> bool:
        return self.safety_label == "Unsafe"


class Qwen3GuardClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.qwen3_guard_timeout_seconds)
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self._tokenizer = None
        self._model = None

    async def close(self) -> None:
        await self._client.aclose()

    async def moderate_prompt(self, prompt: str) -> QwenGuardAssessment:
        started = perf_counter()
        backend = self._resolve_backend()

        try:
            if backend == "openai":
                raw_output = await self._moderate_prompt_openai(prompt)
            elif backend == "transformers":
                raw_output = await asyncio.to_thread(self._moderate_prompt_transformers, prompt)
            else:
                raise RuntimeError(f"Unsupported Qwen3Guard backend: {backend}")
        except Exception as error:
            return QwenGuardAssessment(
                safety_label=None,
                categories=[],
                raw_output="",
                backend=backend,
                latency_ms=round((perf_counter() - started) * 1000),
                error=str(error),
            )

        safety_label, categories = parse_qwen_guard_output(raw_output)
        return QwenGuardAssessment(
            safety_label=safety_label,
            categories=categories,
            raw_output=raw_output,
            backend=backend,
            latency_ms=round((perf_counter() - started) * 1000),
        )

    def _resolve_backend(self) -> str:
        backend = self.settings.qwen3_guard_backend.strip().lower()
        if backend == "auto":
            return "openai" if self.settings.qwen3_guard_base_url.strip() else "transformers"
        return backend

    async def _moderate_prompt_openai(self, prompt: str) -> str:
        base_url = self.settings.qwen3_guard_base_url.rstrip("/")
        if not base_url:
            raise RuntimeError("QWEN3_GUARD_BASE_URL is required when QWEN3_GUARD_BACKEND=openai")

        response = await self._client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.qwen3_guard_api_key}"},
            json={
                "model": self.settings.qwen3_guard_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": self.settings.qwen3_guard_max_new_tokens,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        return message.get("content") or message.get("reasoning") or ""

    def _moderate_prompt_transformers(self, prompt: str) -> str:
        self._ensure_transformers_model()
        with self._generate_lock:
            import torch

            messages = [{"role": "user", "content": prompt}]
            text = self._tokenizer.apply_chat_template(messages, tokenize=False)
            model_inputs = self._tokenizer([text], return_tensors="pt").to(self._model_device())
            with torch.no_grad():
                generated_ids = self._model.generate(
                    **model_inputs,
                    max_new_tokens=self.settings.qwen3_guard_max_new_tokens,
                    do_sample=False,
                )
            output_ids = generated_ids[0][len(model_inputs.input_ids[0]) :].tolist()
            return self._tokenizer.decode(output_ids, skip_special_tokens=True).strip()

    def _ensure_transformers_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return

            from transformers import AutoModelForCausalLM, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.settings.qwen3_guard_model)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.settings.qwen3_guard_model,
                torch_dtype="auto",
                device_map="auto",
            )
            self._model.eval()

    def _model_device(self):
        return getattr(self._model, "device", None) or next(self._model.parameters()).device


def parse_qwen_guard_output(content: str) -> tuple[str | None, list[str]]:
    safety_match = SAFETY_PATTERN.search(content)
    safety_label = normalize_safety_label(safety_match.group(1)) if safety_match else None
    categories = [normalize_category(match) for match in CATEGORY_PATTERN.findall(content)]
    categories = [category for category in categories if category != "None"]
    return safety_label, dedupe(categories)


def normalize_safety_label(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "safe":
        return "Safe"
    if normalized == "unsafe":
        return "Unsafe"
    return "Controversial"


def normalize_category(value: str) -> str:
    known = {
        "violent": "Violent",
        "non-violent illegal acts": "Non-violent Illegal Acts",
        "sexual content or sexual acts": "Sexual Content or Sexual Acts",
        "pii": "PII",
        "suicide & self-harm": "Suicide & Self-Harm",
        "unethical acts": "Unethical Acts",
        "politically sensitive topics": "Politically Sensitive Topics",
        "copyright violation": "Copyright Violation",
        "jailbreak": "Jailbreak",
        "none": "None",
    }
    return known.get(value.strip().lower(), value.strip())


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
