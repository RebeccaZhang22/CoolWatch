from __future__ import annotations

from typing import Any


def is_first_assistant_decision_after_tool_result(
    messages: list[dict[str, Any]],
) -> bool:
    """Return whether this generation immediately follows new tool output.

    A production guard cannot know whether a tool result contains an injection
    before inspecting the resulting model state. It therefore probes the first
    assistant decision after every newly appended batch of tool messages. Once
    an assistant message follows that batch, later decisions do not trigger.
    """

    return bool(messages) and str(messages[-1].get("role") or "") == "tool"

