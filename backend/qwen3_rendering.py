"""One tool-call normalization contract for Qwen3 training and serving."""
import json


def normalize_tool_calls(messages):
    normalized = []
    for message in messages:
        if message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                arguments = function.get("arguments", call.get("arguments"))
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {"raw": arguments}
                calls.append({"name": function.get("name") or call.get("name") or "",
                              "arguments": arguments})
            message = {**message, "tool_calls": calls}
        normalized.append(message)
    return normalized
