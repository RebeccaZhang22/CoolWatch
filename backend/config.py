from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ENV_FILE = Path(__file__).resolve().with_name(".env")
PROJECT_ROOT = BACKEND_ENV_FILE.parents[1]


class Settings(BaseSettings):
    # Keep all local credentials and model settings in backend/.env. The
    # project-level file remains an optional compatibility fallback.
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ENV_FILE, PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ProspectMonitor"
    admin_email: str = Field(default="admin@admin.com", alias="PROSPECTMONITOR_ADMIN_EMAIL")
    admin_password: str = Field(default="", alias="PROSPECTMONITOR_ADMIN_PASSWORD")
    probe_bank_base_url: str = Field(default="http://127.0.0.1:8302", alias="PROBE_BANK_BASE_URL")
    vllm_base_url: str = Field(default="http://127.0.0.1:8013/v1", alias="VLLM_BASE_URL")
    vllm_api_key: str = Field(default="EMPTY", alias="VLLM_API_KEY")
    vllm_model: str = Field(default="qwen3-8b", alias="VLLM_MODEL")
    llm_timeout_seconds: float = Field(default=120.0, alias="LLM_TIMEOUT_SECONDS")
    customer_agent_vllm_base_url: str = Field(
        default="http://127.0.0.1:8013/v1",
        alias="CUSTOMER_AGENT_VLLM_BASE_URL",
    )
    # Public business endpoint. Kept separate from the probe-capable shadow
    # endpoint so user requests never need to talk to the modified vLLM.
    customer_agent_business_vllm_base_url: str = Field(
        default="",
        alias="CUSTOMER_AGENT_BUSINESS_VLLM_BASE_URL",
    )
    customer_agent_shadow_vllm_base_url: str = Field(
        default="http://127.0.0.1:8013/v1",
        alias="CUSTOMER_AGENT_SHADOW_VLLM_BASE_URL",
    )
    customer_agent_model: str = Field(
        default="qwen3-8b",
        alias="CUSTOMER_AGENT_MODEL",
    )
    customer_agent_shadow_model: str = Field(
        default="qwen3-8b",
        alias="CUSTOMER_AGENT_SHADOW_MODEL",
    )
    customer_agent_enable_runtime_probes: bool = Field(
        default=True,
        alias="CUSTOMER_AGENT_ENABLE_RUNTIME_PROBES",
    )
    customer_agent_data_root: str = Field(default="", alias="CUSTOMER_AGENT_DATA_ROOT")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    financial_tool_model: str = Field(default="gpt-4.1-mini", alias="FINANCIAL_TOOL_MODEL")
    financial_tool_timeout_seconds: float = Field(
        default=180.0,
        alias="FINANCIAL_TOOL_TIMEOUT_SECONDS",
    )
    qwen3_guard_backend: str = Field(default="auto", alias="QWEN3_GUARD_BACKEND")
    qwen3_guard_base_url: str = Field(default="", alias="QWEN3_GUARD_BASE_URL")
    qwen3_guard_api_key: str = Field(default="EMPTY", alias="QWEN3_GUARD_API_KEY")
    qwen3_guard_model: str = Field(
        default="Qwen/Qwen3Guard-Gen-8B",
        alias="QWEN3_GUARD_MODEL",
    )
    qwen3_guard_timeout_seconds: float = Field(default=120.0, alias="QWEN3_GUARD_TIMEOUT_SECONDS")
    qwen3_guard_max_new_tokens: int = Field(default=128, alias="QWEN3_GUARD_MAX_NEW_TOKENS")
    llama_prompt_guard_model: str = Field(
        default="meta-llama/Llama-Prompt-Guard-2-86M",
        alias="LLAMA_PROMPT_GUARD_MODEL",
    )
    llama_prompt_guard_threshold: float = Field(default=0.5, ge=0, le=1, alias="LLAMA_PROMPT_GUARD_THRESHOLD")
    llama_prompt_guard_max_length: int = Field(default=512, ge=1, le=512, alias="LLAMA_PROMPT_GUARD_MAX_LENGTH")
    llama_prompt_guard_device: str = Field(default="auto", alias="LLAMA_PROMPT_GUARD_DEVICE")
    safegauge_processor_path: str = Field(default="", alias="SAFEGAUGE_PROCESSOR_PATH")
    safegauge_tokenizer_path: str = Field(default="", alias="SAFEGAUGE_TOKENIZER_PATH")
    safegauge_device: str = Field(default="cpu", alias="SAFEGAUGE_DEVICE")
    safegauge_timeout_seconds: float = Field(default=120.0, alias="SAFEGAUGE_TIMEOUT_SECONDS")
    inline_probing_protocol: str = Field(default="inline_probing", alias="INLINE_PROBING_PROTOCOL")
    inline_probing_task: str = Field(
        default="indirect_prompt_injection",
        alias="INLINE_PROBING_TASK",
    )
    inline_probing_probe_id: str = Field(
        default="qwen3-8b-indirect-prompt-injection-assistant-prefix-probing",
        alias="INLINE_PROBING_PROBE_ID",
    )
    inline_probing_expected_checkpoint_id: str = Field(
        default="sha256:41f1433346caebc8b2e9ff5640b44e3d162050d6ef7ffee45285badba4798b45",
        alias="INLINE_PROBING_EXPECTED_CHECKPOINT_ID",
    )
    inline_probing_threshold: float = Field(default=0.5, ge=0, le=1, alias="INLINE_PROBING_THRESHOLD")
    inline_probing_timeout_seconds: float = Field(default=120.0, alias="INLINE_PROBING_TIMEOUT_SECONDS")
    activation_probe_base_url: str = Field(
        default="http://127.0.0.1:8910",
        alias="ACTIVATION_PROBE_BASE_URL",
    )
    activation_probe_timeout_seconds: float = Field(
        default=300.0,
        alias="ACTIVATION_PROBE_TIMEOUT_SECONDS",
    )
    activation_probe_backend: str = Field(
        default="vllm",
        alias="ACTIVATION_PROBE_BACKEND",
    )
    activation_probe_vllm_base_url: str = Field(
        default="",
        alias="ACTIVATION_PROBE_VLLM_BASE_URL",
    )
    netease_yidun_api_url: str = Field(default="https://as.dun.163.com/v5/text/check", alias="NETEASE_YIDUN_API_URL")
    netease_yidun_secret_id: str = Field(default="", alias="NETEASE_YIDUN_SECRET_ID")
    netease_yidun_secret_key: str = Field(default="", alias="NETEASE_YIDUN_SECRET_KEY")
    netease_yidun_business_id: str = Field(default="", alias="NETEASE_YIDUN_BUSINESS_ID")
    netease_yidun_version: str = Field(default="v5.2", alias="NETEASE_YIDUN_VERSION")
    netease_yidun_signature_method: str = Field(default="", alias="NETEASE_YIDUN_SIGNATURE_METHOD")
    netease_yidun_timeout_seconds: float = Field(default=2.0, alias="NETEASE_YIDUN_TIMEOUT_SECONDS")
    netease_yidun_check_labels: str = Field(default="", alias="NETEASE_YIDUN_CHECK_LABELS")
    fangcun_api_key: str = Field(default="", alias="FANGCUN_API_KEY")
    fangcun_base_url: str = Field(
        default="https://guard.fangcunleap.com",
        alias="FANGCUN_BASE_URL",
    )
    fangcun_timeout_seconds: float = Field(default=15.0, alias="FANGCUN_TIMEOUT_SECONDS")
    cors_allow_origins: str = Field(default="*", alias="CORS_ALLOW_ORIGINS")

    @property
    def frontend_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "frontend"

    @property
    def allowed_origins(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def customer_agent_business_base_url(self) -> str:
        """The only endpoint used for user-visible Agent generation."""
        return (
            self.customer_agent_business_vllm_base_url.strip()
            or self.customer_agent_vllm_base_url.strip()
        ).rstrip("/")

    @property
    def customer_agent_shadow_base_url(self) -> str:
        """Server-side-only hidden-state/logprob prefill endpoint."""
        return self.customer_agent_shadow_vllm_base_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
