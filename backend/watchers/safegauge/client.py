from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from backend.config import Settings
from backend.watchers.safegauge.detector import SafeGaugeDetector


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = PROJECT_ROOT / "results" / "suffix_probe"
TASK_CHECKPOINTS = {
    "system_prompt_leakage_intent": {
        "qwen38b": RESULTS_DIR / "prompt-extraction-qwen3-8b-system-prompt-leakage" / "probe" / "model.pt",
        "qwen332b": RESULTS_DIR / "prompt-extraction-qwen3-32b-system-prompt-leakage" / "probe" / "model.pt",
    },
    "financially_malicious_action": {
        "qwen38b": RESULTS_DIR / "finvault-qwen3-8b-financially-malicious-action" / "probe" / "model.pt",
        "qwen332b": RESULTS_DIR / "finvault-qwen3-32b-financially-malicious-action" / "probe" / "model.pt",
    },
}


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


class SafeGaugeGuard:
    """In-process SafeGauge MLP that reuses Perspective Watch's existing vLLM API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._detectors: dict[tuple[str, str, str], SafeGaugeDetector] = {}
        self._load_lock = asyncio.Lock()

    async def close(self) -> None:
        for detector in self._detectors.values():
            client = detector.logprobs_extractor.client
            if client is not None:
                await asyncio.to_thread(client.close)
        self._detectors.clear()

    async def moderate_messages(
        self,
        messages: list[dict[str, str]],
        threshold: float | None = None,
        *,
        task: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> SafeGaugeAssessment:
        started = perf_counter()
        try:
            detector = await self._get_detector(task=task, model=model, base_url=base_url)
            payload = await asyncio.to_thread(detector.detect, messages, threshold)
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
            return self._error_assessment(str(error), started)

    async def get_model_info(
        self,
        *,
        task: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict:
        detector = await self._get_detector(task=task, model=model, base_url=base_url)
        return detector.get_model_info()

    async def _get_detector(
        self,
        *,
        task: str | None,
        model: str | None,
        base_url: str | None,
    ) -> SafeGaugeDetector:
        selected_model = model or self.settings.vllm_model
        selected_base_url = (base_url or self.settings.vllm_base_url).rstrip("/")
        processor_path = resolve_processor_path(
            self.settings.safegauge_processor_path,
            selected_model,
            task=task,
        )
        cache_key = (str(processor_path), selected_model, selected_base_url)
        detector = self._detectors.get(cache_key)
        if detector is not None:
            return detector
        async with self._load_lock:
            detector = self._detectors.get(cache_key)
            if detector is None:
                detector = await asyncio.to_thread(
                    self._build_detector,
                    processor_path,
                    selected_model,
                    selected_base_url,
                )
                self._detectors[cache_key] = detector
        return detector

    def _build_detector(self, processor_path: Path, model: str, base_url: str) -> SafeGaugeDetector:
        device = self.settings.safegauge_device.strip().lower()
        if device == "auto":
            device = None
        elif device not in {"cpu", "cuda"}:
            raise ValueError("SAFEGAUGE_DEVICE must be one of: auto, cpu, cuda")

        return SafeGaugeDetector(
            processor_path=str(processor_path),
            base_url=base_url,
            api_key=self.settings.vllm_api_key,
            model=model,
            tokenizer_path=self.settings.safegauge_tokenizer_path.strip() or None,
            device=device,
            timeout=self.settings.safegauge_timeout_seconds,
        )

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


def resolve_processor_path(configured_path: str, model_name: str, *, task: str | None = None) -> Path:
    if task:
        task_routes = TASK_CHECKPOINTS.get(task)
        if task_routes is None:
            raise ValueError(f"Unsupported SafeGauge task: {task}")
        checkpoint = task_routes.get(normalize_model_name(Path(model_name.rstrip("/")).name))
        if checkpoint is None:
            raise FileNotFoundError(
                f"No SafeGauge checkpoint route for task={task!r}, model={model_name!r}"
            )
        if not checkpoint.is_file():
            raise FileNotFoundError(
                f"SafeGauge checkpoint is not trained for task={task!r}, model={model_name!r}: {checkpoint}"
            )
        return checkpoint

    if configured_path.strip():
        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            raise FileNotFoundError(f"SafeGauge processor checkpoint not found: {path}")
        return path

    raise ValueError(
        "SafeGauge requires a task route or SAFEGAUGE_PROCESSOR_PATH; "
        f"no checkpoint was selected for VLLM_MODEL={model_name!r}"
    )


def normalize_model_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
