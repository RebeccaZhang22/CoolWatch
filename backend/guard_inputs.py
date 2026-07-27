from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any


TOOL_RESULT = "tool_result"
TEXT_GUARD_INPUT_MODES = (TOOL_RESULT,)


def message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, Mapping):
            value = item.get("text", item.get("content"))
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def full_tool_result(
    messages: Sequence[Mapping[str, Any]],
    message_indices: Sequence[int],
) -> str:
    """Return complete newly faced tool-result messages, without attack extraction."""

    values: list[str] = []
    for index in message_indices:
        message = messages[int(index)]
        if str(message.get("role") or "") != "tool":
            raise ValueError(f"injection message {index} is not a tool result")
        value = message_text(message)
        if not value.strip():
            raise ValueError(f"tool-result message {index} has no text")
        values.append(value)
    return "\n\n".join(values)


def text_guard_input(
    replay: Mapping[str, Any],
    injection_message_indices: Sequence[int],
    input_mode: str,
) -> str:
    messages = replay.get("messages")
    if not isinstance(messages, list):
        raise ValueError("replay request has no message list")
    if input_mode == TOOL_RESULT:
        value = full_tool_result(messages, injection_message_indices)
    else:
        raise ValueError(f"unsupported text guard input mode: {input_mode}")
    if not value.strip():
        raise ValueError(f"empty text guard input for mode {input_mode}")
    return value


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
