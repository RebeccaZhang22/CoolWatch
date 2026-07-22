from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ENV_FILE = Path(__file__).resolve().with_name(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CoolWatch"
    vllm_base_url: str = Field(default="http://127.0.0.1:8767/v1", alias="VLLM_BASE_URL")
    vllm_api_key: str = Field(default="EMPTY", alias="VLLM_API_KEY")
    vllm_model: str = Field(default="qwen3.5-27b", alias="VLLM_MODEL")
    llm_timeout_seconds: float = Field(default=120.0, alias="LLM_TIMEOUT_SECONDS")
    qwen3_guard_backend: str = Field(default="auto", alias="QWEN3_GUARD_BACKEND")
    qwen3_guard_base_url: str = Field(default="", alias="QWEN3_GUARD_BASE_URL")
    qwen3_guard_api_key: str = Field(default="EMPTY", alias="QWEN3_GUARD_API_KEY")
    qwen3_guard_model: str = Field(
        default="/share/workspace/models/hub/models--Qwen--Qwen3Guard-Gen-8B/snapshots/4505cb1a6f1864f21f8b27f7daf1b9a1aab6edbb",
        alias="QWEN3_GUARD_MODEL",
    )
    qwen3_guard_timeout_seconds: float = Field(default=120.0, alias="QWEN3_GUARD_TIMEOUT_SECONDS")
    qwen3_guard_max_new_tokens: int = Field(default=128, alias="QWEN3_GUARD_MAX_NEW_TOKENS")
    netease_yidun_api_url: str = Field(default="http://as.dun.163.com/v5/text/check", alias="NETEASE_YIDUN_API_URL")
    netease_yidun_secret_id: str = Field(default="", alias="NETEASE_YIDUN_SECRET_ID")
    netease_yidun_secret_key: str = Field(default="", alias="NETEASE_YIDUN_SECRET_KEY")
    netease_yidun_business_id: str = Field(default="", alias="NETEASE_YIDUN_BUSINESS_ID")
    netease_yidun_version: str = Field(default="v5.2", alias="NETEASE_YIDUN_VERSION")
    netease_yidun_signature_method: str = Field(default="", alias="NETEASE_YIDUN_SIGNATURE_METHOD")
    netease_yidun_timeout_seconds: float = Field(default=2.0, alias="NETEASE_YIDUN_TIMEOUT_SECONDS")
    netease_yidun_check_labels: str = Field(default="", alias="NETEASE_YIDUN_CHECK_LABELS")
    cors_allow_origins: str = Field(default="*", alias="CORS_ALLOW_ORIGINS")

    @property
    def frontend_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "frontend"

    @property
    def allowed_origins(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
