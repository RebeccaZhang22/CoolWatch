#!/usr/bin/env python3
"""Replay the frozen case with Qwen3-8B using its native chat template."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from time import perf_counter
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def parse_message(raw: str) -> dict[str, Any]:
    visible = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()
    tool_calls = []
    for index, match in enumerate(TOOL_CALL_PATTERN.finditer(visible), start=1):
        payload = json.loads(match.group(1))
        tool_calls.append(
            {
                "id": f"qwen3-transformers-{index}",
                "type": "function",
                "function": {
                    "name": payload["name"],
                    "arguments": json.dumps(payload.get("arguments") or {}, ensure_ascii=False),
                },
            }
        )
    content = TOOL_CALL_PATTERN.sub("", visible).strip()
    return {"role": "assistant", "content": content or None, "tool_calls": tool_calls}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()

    case = json.loads((args.evaluation_dir / "cases.jsonl").read_text().splitlines()[0])
    replay = case["replay_request"]
    messages = [dict(message, content=message.get("content") or "") for message in replay["messages"]]
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    rendered = tokenizer.apply_chat_template(
        messages,
        tools=replay.get("tools"),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = tokenizer(rendered, return_tensors="pt")
    started = perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype=torch.bfloat16,
        device_map=None,
    ).eval()
    load_ms = round((perf_counter() - started) * 1000)
    generation_started = perf_counter()
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
        )
    generated_ids = output[0, inputs.input_ids.shape[1] :]
    raw = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
    message = parse_message(raw)
    row = {
        "schema": "coolwatch.agent_behavior.result.v1",
        "benchmark_id": "pdf-white-text-car-loan-approval-injection",
        "sample_index": case["sample_index"],
        "decision_point_id": case["decision_point_id"],
        "grid_point_id": case["grid_point_id"],
        "language": "zh-CN",
        "model": "Qwen/Qwen3-8B",
        "backend": "transformers-cpu",
        "load_ms": load_ms,
        "latency_ms": round((perf_counter() - generation_started) * 1000),
        "error": None,
        "finish_reason": "tool_calls" if message["tool_calls"] else "stop",
        "message": message,
        "raw_output": raw,
        "rendered_prompt_sha256": __import__("hashlib").sha256(rendered.encode()).hexdigest(),
        "usage": {
            "prompt_tokens": int(inputs.input_ids.shape[1]),
            "completion_tokens": int(generated_ids.shape[0]),
            "total_tokens": int(output.shape[1]),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
