"""Configuration owned by the independent management application."""
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MANAGER_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MANAGER_ROOT.parent


class ManagerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=MANAGER_ROOT / ".env", extra="ignore")

    data_dir: Path = Field(default=MANAGER_ROOT / "data", alias="MANAGER_DATA_DIR")
    user_db: Path = Field(default=PROJECT_ROOT / ".runtime" / "prospectmonitor.db", alias="MANAGER_USER_DB")
    usage_log: Path = Field(default=PROJECT_ROOT / ".runtime" / "usage_events.jsonl", alias="MANAGER_USAGE_LOG")
    email: str = Field(default="", validation_alias=AliasChoices("MANAGER_EMAIL", "PROSPECTMONITOR_MANAGER_EMAIL"))
    password: str = Field(default="", validation_alias=AliasChoices("MANAGER_PASSWORD", "PROSPECTMONITOR_MANAGER_PASSWORD"))

    @field_validator("data_dir", "user_db", "usage_log", mode="after")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        value = value.expanduser()
        return value.resolve() if value.is_absolute() else (MANAGER_ROOT / value).resolve()


def get_config() -> ManagerConfig:
    return ManagerConfig()
