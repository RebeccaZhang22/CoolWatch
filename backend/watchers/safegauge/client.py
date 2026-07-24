from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from backend.config import Settings
from backend.watchers.safegauge.detector import SafeGaugeDetector


MODELS_DIR = Path(__file__).resolve().parent / "models"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    """In-process SafeGauge MLP that reuses CoolWatch's existing vLLM API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._detector: SafeGaugeDetector | None = None
        self._load_lock = asyncio.Lock()

    async def close(self) -> None:
        detector = self._detector
        if detector is None:
            return
        client = detector.logprobs_extractor.client
        if client is not None:
            await asyncio.to_thread(client.close)

    async def moderate_messages(
        self,
        messages: list[dict[str, str]],
        threshold: float | None = None,
    ) -> SafeGaugeAssessment:
        started = perf_counter()
        try:
            detector = await self._get_detector()
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

    async def get_model_info(self) -> dict:
        detector = await self._get_detector()
        return detector.get_model_info()

    async def _get_detector(self) -> SafeGaugeDetector:
        if self._detector is not None:
            return self._detector

        async with self._load_lock:
            if self._detector is None:
                self._detector = await asyncio.to_thread(self._build_detector)
        return self._detector

    def _build_detector(self) -> SafeGaugeDetector:
        processor_path = resolve_processor_path(
            self.settings.safegauge_processor_path,
            self.settings.vllm_model,
        )
        device = self.settings.safegauge_device.strip().lower()
        if device == "auto":
            device = None
        elif device not in {"cpu", "cuda"}:
            raise ValueError("SAFEGAUGE_DEVICE must be one of: auto, cpu, cuda")

        return SafeGaugeDetector(
            processor_path=str(processor_path),
            base_url=self.settings.vllm_base_url,
            api_key=self.settings.vllm_api_key,
            model=self.settings.vllm_model,
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


def resolve_processor_path(configured_path: str, model_name: str) -> Path:
    if configured_path.strip():
        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            raise FileNotFoundError(f"SafeGauge processor checkpoint not found: {path}")
        return path

    normalized_model = normalize_model_name(Path(model_name.rstrip("/")).name)
    matching_groups = [
        group
        for group in MODELS_DIR.iterdir()
        if group.is_dir() and normalize_model_name(group.name) == normalized_model
    ]
    checkpoints = [checkpoint for group in matching_groups for checkpoint in group.rglob("best_model.pt")]
    if len(checkpoints) == 1:
        return checkpoints[0]
    if not checkpoints:
        raise FileNotFoundError(
            f"No SafeGauge checkpoint matches VLLM_MODEL={model_name!r}; "
            "set SAFEGAUGE_PROCESSOR_PATH explicitly"
        )
    raise RuntimeError(
        f"Multiple SafeGauge checkpoints match VLLM_MODEL={model_name!r}; "
        "set SAFEGAUGE_PROCESSOR_PATH explicitly"
    )


def normalize_model_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
