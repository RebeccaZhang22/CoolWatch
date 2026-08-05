import asyncio
import json
import threading
from dataclasses import dataclass
from time import perf_counter

from backend.config import Settings


@dataclass(frozen=True)
class LlamaPromptGuardAssessment:
    label: str | None
    probability: float | None
    threshold: float
    raw_output: str
    latency_ms: int
    error: str | None = None

    @property
    def risky(self) -> bool | None:
        if self.probability is None:
            return None
        return self.probability >= self.threshold

    @property
    def blocked(self) -> bool:
        return self.risky is True


class LlamaPromptGuardClient:
    """Lazy local inference client for Meta Llama Prompt Guard 2."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._load_lock = threading.Lock()
        self._predict_lock = threading.Lock()
        self._tokenizer = None
        self._model = None

    async def close(self) -> None:
        return None

    async def moderate_prompt(self, prompt: str) -> LlamaPromptGuardAssessment:
        started = perf_counter()
        threshold = self.settings.llama_prompt_guard_threshold
        try:
            label, probability, raw_output = await asyncio.to_thread(self._predict, prompt)
            return LlamaPromptGuardAssessment(
                label=label,
                probability=probability,
                threshold=threshold,
                raw_output=raw_output,
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except Exception as error:
            return LlamaPromptGuardAssessment(
                label=None,
                probability=None,
                threshold=threshold,
                raw_output="",
                latency_ms=round((perf_counter() - started) * 1000),
                error=str(error),
            )

    def _predict(self, prompt: str) -> tuple[str, float, str]:
        self._ensure_model()
        with self._predict_lock:
            import torch

            inputs = self._tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=self.settings.llama_prompt_guard_max_length,
            ).to(self._model_device())
            with torch.no_grad():
                logits = self._model(**inputs).logits[0]
                probabilities = torch.softmax(logits.float(), dim=-1).cpu().tolist()

        # Prompt Guard 2 is a binary classifier: class 0 is benign and class 1 is malicious.
        malicious_probability = float(probabilities[1])
        label = "MALICIOUS" if malicious_probability >= self.settings.llama_prompt_guard_threshold else "BENIGN"
        raw_output = json.dumps(
            {
                "label": label,
                "malicious_probability": malicious_probability,
                "threshold": self.settings.llama_prompt_guard_threshold,
                "probabilities": probabilities,
            },
            ensure_ascii=False,
        )
        return label, malicious_probability, raw_output

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return

            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import torch

            model_path = self.settings.llama_prompt_guard_model
            self._tokenizer = AutoTokenizer.from_pretrained(model_path)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                model_path,
                torch_dtype="auto",
            )
            configured_device = self.settings.llama_prompt_guard_device.strip().lower()
            device = ("cuda" if torch.cuda.is_available() else "cpu") if configured_device == "auto" else configured_device
            self._model.to(device)
            self._model.eval()

    def _model_device(self):
        return getattr(self._model, "device", None) or next(self._model.parameters()).device
