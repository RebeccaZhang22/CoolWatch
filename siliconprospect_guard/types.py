from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MessageRole = Literal["developer", "system", "user", "assistant", "tool"]


class ModerationMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: MessageRole
    content: str | list[dict[str, Any]] | None = None
    name: str | None = Field(default=None, max_length=128)
    reasoning_content: str | None = None
    reasoning_details: Any | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    @field_validator("reasoning_content")
    @classmethod
    def validate_reasoning(cls, value: str | None) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("reasoning_content must be a string")
        return value


class ModerationRequest(BaseModel):
    messages: list[ModerationMessage] = Field(min_length=1, max_length=128)
    tools: list[dict[str, Any]] | None = None
    metadata: dict[str, str] | None = None
    idempotency_key: str | None = None
    request_id: str | None = None

class DetectionResult(BaseModel):
    score: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    flagged: bool


class Usage(BaseModel):
    input_tokens: int = Field(ge=0)
    billable_tokens: int = Field(ge=0)
    billable_units: float = Field(ge=0)
    unit: str = "1k_input_tokens"


class Latency(BaseModel):
    queue: float = 0
    prefill: float = 0
    detect: float = 0
    total: float = 0


class ModerationResponse(BaseModel):
    id: str
    request_id: str
    created: int
    detector_model: str
    bank_version: str
    action: Literal["pass", "block"]
    per_risk: dict[str, DetectionResult]
    per_entry: dict[str, float]
    triggered_entries: list[str]
    usage: Usage
    latency_ms: Latency
