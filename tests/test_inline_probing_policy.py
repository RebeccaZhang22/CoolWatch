from backend.watchers.inline_probing.policy import (
    is_first_assistant_decision_after_tool_result,
)


def test_only_generation_immediately_after_tool_result_is_probe_eligible() -> None:
    assert not is_first_assistant_decision_after_tool_result([])
    assert not is_first_assistant_decision_after_tool_result(
        [{"role": "user", "content": "hello"}]
    )
    assert is_first_assistant_decision_after_tool_result(
        [
            {"role": "tool", "content": "first"},
            {"role": "tool", "content": "second"},
        ]
    )
    assert not is_first_assistant_decision_after_tool_result(
        [
            {"role": "tool", "content": "result"},
            {"role": "assistant", "content": "decision"},
        ]
    )
