#!/usr/bin/env python3
"""Score the frozen Qwen3-8B decision point with the recipe probe on CPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


FOLLOW_YOUR_HEART_ROOT = Path(__file__).resolve().parents[4]
if str(FOLLOW_YOUR_HEART_ROOT) not in sys.path:
    sys.path.insert(0, str(FOLLOW_YOUR_HEART_ROOT))

from follow_your_heart.probes.featurization.features import (  # noqa: E402
    _apply_chat_template,
    _encode_text,
    _normalize_prompt_messages,
)
from follow_your_heart.probes.featurization.hidden_states import (  # noqa: E402
    capture_prefill_residual_stream,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def token_fingerprint(token_ids: list[int]) -> str:
    digest = hashlib.sha256()
    for token_id in token_ids:
        digest.update(int(token_id).to_bytes(8, byteorder="little", signed=True))
    return f"sha256:{digest.hexdigest()}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    recipe = json.loads(args.recipe.read_text())
    checkpoint_path = args.recipe.parent / recipe["probe"]["path"]
    expected_sha = recipe["probe"]["sha256"]
    actual_sha = sha256_file(checkpoint_path)
    if actual_sha != expected_sha:
        raise RuntimeError(f"probe sha256 mismatch: expected={expected_sha}, actual={actual_sha}")

    case = json.loads((args.evaluation_dir / "cases.jsonl").read_text().splitlines()[0])
    replay = case["replay_request"]
    messages = _normalize_prompt_messages(replay["messages"])
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    rendered = _apply_chat_template(tokenizer, messages, tools=replay.get("tools") or ())
    token_ids = list(_encode_text(tokenizer, rendered))

    started = perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype=torch.bfloat16,
        device_map=None,
        trust_remote_code=True,
    ).eval()
    layer = int(recipe["probe"]["checkpoint_layer"])
    prompt = SimpleNamespace(token_ids=tuple(token_ids), decode_start_index=len(token_ids))
    capture = capture_prefill_residual_stream(
        prompt,
        model=model,
        selected_positions=(int(recipe["probe"].get("effective_position", -1)),),
    )
    feature = capture.hidden_states[layer][0].to(dtype=torch.float32)

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    state = checkpoint["model_state_dict"]
    weight = state["probe.weight"].to(dtype=torch.float32)
    bias = state["probe.bias"].to(dtype=torch.float32)
    mean = state["input_mean"].to(dtype=torch.float32)
    std = state["input_std"].to(dtype=torch.float32)
    normalized = (feature - mean.reshape(-1)) / std.reshape(-1)
    logit = torch.nn.functional.linear(normalized, weight, bias).reshape(()).item()
    score = torch.sigmoid(torch.tensor(logit)).item()
    result = {
        "schema": "coolwatch.guard_detection.result.v1",
        "benchmark_id": "pdf-white-text-car-loan-approval-injection",
        "sample_index": case["sample_index"],
        "decision_point_id": case["decision_point_id"],
        "grid_point_id": case["grid_point_id"],
        "language": "zh-CN",
        "guard": "inline_probing",
        "backend": "transformers-cpu-offline-parity",
        "online_verified": False,
        "detected": score >= args.threshold,
        "error": None,
        "latency_ms": round((perf_counter() - started) * 1000),
        "raw_output": json.dumps({"status": "ok", "score": score, "logit": logit}),
        "score": score,
        "logit": logit,
        "threshold": args.threshold,
        "checkpoint_id": f"sha256:{actual_sha}",
        "layer": layer,
        "requested_position": -1,
        "effective_position": -1,
        "prompt_token_count": len(token_ids),
        "native_prompt_token_fingerprint": token_fingerprint(token_ids),
        "rendered_prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
