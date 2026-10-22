from dataclasses import dataclass
from pathlib import Path
import json
import math
import os

from .composer import ComposerConfig

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_SHA256 = "10f79d9c7acab62a1640e1397449f47e8bf392bb6b8c9bc0b55f67274cb2e3e0"
INSCOPE_COMMIT = "d504843f44ae733e1970e70ab6bbbd9ab044e353"

DEFAULT_MODELS_DIR = str(ROOT / "checkpoints/blend")
DEFAULT_PROBE_PREFIX = "Are there risks of indirect prompt injection?"

# A5_n2097152 blend（Linear + N1024，alpha=0.5）。阈值只标定过不合并配置，
# 来自 pooled validation FPR<=1%；换 seed 或换 composer 都必须在固定 val 上重评，
# 不能继承这里的数字。
BLEND_ARMS = {
    "linear": "L_wd0.1_d0_s{seed}/best.pt",
    "mlp": "N1024_wd0.01_d0.1_s{seed}/best.pt",
}
THRESHOLD_LOGIT = {
    42: 2.3247954845428467,
    43: 1.7843475341796875,
    44: 2.0362582206726074,
}
THRESHOLD_SIGMOID = {
    42: 0.9109098766012635,
    43: 0.8562328685767427,
    44: 0.8845517069831247,
}


def blend_arms(seed):
    return {arm: template.format(seed=seed) for arm, template in BLEND_ARMS.items()}


def _flag(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class Settings:
    model_path: str
    api_key: str
    composer: ComposerConfig = ComposerConfig()
    models_dir: str = DEFAULT_MODELS_DIR
    detector_seed: int = 42
    threshold_logit: float | None = None
    backend_url: str = "http://127.0.0.1:30000"
    backend_api_key: str = ""
    max_tokens: int = 40959
    max_inflight: int = 16
    timeout: float = 60.0
    max_body_bytes: int = 2 * 1024 * 1024

    def __post_init__(self):
        if not self.model_path or not self.api_key:
            raise ValueError("MODEL_PATH and SHADOW_API_KEY are required")
        if not 4 <= self.max_tokens <= 40959 or self.max_inflight < 1:
            raise ValueError("max_tokens must be 4..40959; max_inflight must be positive")
        if not math.isfinite(self.timeout) or self.timeout <= 0 or self.max_body_bytes < 1:
            raise ValueError("Invalid timeout/body limit")
        if self.threshold_logit is not None and not math.isfinite(self.threshold_logit):
            raise ValueError("threshold_logit must be finite")
        if self.threshold_logit is None and self.detector_seed not in THRESHOLD_LOGIT:
            raise ValueError("No calibrated threshold for seed %d" % self.detector_seed)
        if not self.backend_url.startswith(("http://", "https://")):
            raise ValueError("BACKEND_URL must be an HTTP URL")

    @classmethod
    def from_env(cls):
        threshold = os.getenv("PROBE_THRESHOLD_LOGIT", "")
        return cls(
            model_path=os.environ.get("MODEL_PATH", ""),
            api_key=os.environ.get("SHADOW_API_KEY", ""),
            composer=ComposerConfig(
                discard_cots=_flag("PROBE_DISCARD_COTS", True),
                retain_n_assistant_turns=int(os.getenv("PROBE_RETAIN_ASSISTANT_TURNS", "1")),
                merge_consecutive_assistants=_flag("PROBE_MERGE_CONSECUTIVE_ASSISTANTS", False),
                drop_final_tool_result=_flag("PROBE_DROP_FINAL_TOOL_RESULT", False),
                probe_prefix=os.getenv("PROBE_PREFIX", DEFAULT_PROBE_PREFIX),
                enable_thinking=_flag("PROBE_ENABLE_THINKING", True),
                selected_positions=(-1,),
            ),
            models_dir=os.getenv("DETECTOR_DIR", DEFAULT_MODELS_DIR),
            detector_seed=int(os.getenv("DETECTOR_SEED", "42")),
            threshold_logit=float(threshold) if threshold else None,
            backend_url=os.getenv("BACKEND_URL", "http://127.0.0.1:30000").rstrip("/"),
            backend_api_key=os.getenv("SGLANG_API_KEY", ""),
            max_tokens=int(os.getenv("MAX_INPUT_TOKENS", "40959")),
            max_inflight=int(os.getenv("MAX_INFLIGHT", "16")),
            timeout=float(os.getenv("REQUEST_TIMEOUT", "60")),
        )


def validate_model(path: str):
    """Require local, pre-quantized Qwen FP8 weights; no silent BF16 fallback."""
    config = json.loads((Path(path) / "config.json").read_text())
    expected = {"model_type": "qwen3", "hidden_size": 4096, "num_hidden_layers": 36,
                "num_attention_heads": 32, "num_key_value_heads": 8, "vocab_size": 151936}
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError("Expected Qwen3-8B architecture")
    q = config.get("quantization_config", {})
    if (q.get("quant_method") != "fp8" or q.get("fmt") != "e4m3"
            or q.get("activation_scheme") != "dynamic" or q.get("weight_block_size") != [128, 128]):
        raise ValueError("Expected Qwen3-8B-FP8 blockwise FP8 quantization config")
    if not list(Path(path).glob("*.safetensors")):
        raise ValueError("No model safetensors found in MODEL_PATH")
    return config
