from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import torch

from .client import InlineProbingGuard


RECIPE_DIR = (
    Path(__file__).resolve().parents[3]
    / "recipe"
    / "inline_probing"
    / "qwen3-8b-indirect-prompt-injection-assistant-prefix-probing"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_recipe(recipe_dir: Path = RECIPE_DIR) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    recipe = json.loads((recipe_dir / "recipe.json").read_text())
    cases = [
        json.loads(line)
        for line in (recipe_dir / recipe["cases"]["path"]).read_text().splitlines()
        if line.strip()
    ]
    return recipe, cases


def validate_recipe(recipe_dir: Path = RECIPE_DIR) -> dict[str, Any]:
    recipe, cases = load_recipe(recipe_dir)
    labeling = recipe["task"]["labeling"]
    if labeling["protocol"] != recipe["probe"]["labeling_protocol"]:
        raise ValueError("recipe labeling definition does not match probe")
    if labeling["unit"] != "assistant_decision_point":
        raise ValueError("unsupported golden recipe labeling unit")
    probe_path = recipe_dir / recipe["probe"]["path"]
    cases_path = recipe_dir / recipe["cases"]["path"]
    if _sha256(probe_path) != recipe["probe"]["sha256"]:
        raise ValueError("golden probe sha256 mismatch")
    if _sha256(cases_path) != recipe["cases"]["sha256"]:
        raise ValueError("golden cases sha256 mismatch")
    if any(recipe_dir.glob("*feature*")):
        raise ValueError("golden recipe must not contain saved hidden features")

    runtime = recipe["runtime_contract"]
    overlay = runtime["overlay"]
    manifest_path = recipe_dir / overlay["manifest"]
    if _sha256(manifest_path) != overlay["manifest_sha256"]:
        raise ValueError("vLLM overlay manifest sha256 mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("vllm_version") != runtime["vllm_version"]:
        raise ValueError("vLLM overlay version does not match recipe")
    if len(manifest.get("files", [])) != overlay["patched_files"]:
        raise ValueError("vLLM overlay file count does not match recipe")
    overlay_root = recipe_dir / overlay["path"] / "vllm"
    for item in manifest["files"]:
        source = overlay_root / item["path"]
        if not source.is_file() or _sha256(source) != item["patched_sha256"]:
            raise ValueError(f"vLLM overlay file mismatch: {item['path']}")
        compile(source.read_bytes(), str(source), "exec")
    required_recipe_files = (
        overlay["patch_tool"],
        runtime["server"]["entrypoint"],
        runtime["server"]["example"],
        "README.md",
    )
    for relative in required_recipe_files:
        if not (recipe_dir / relative).is_file():
            raise ValueError(f"golden recipe runtime file missing: {relative}")

    checkpoint = torch.load(probe_path, map_location="cpu", weights_only=True)
    state = checkpoint["model_state_dict"]
    expected_width = int(recipe["model"]["hidden_width"])
    if checkpoint.get("schema") != "fyh.probe_checkpoint.v2":
        raise ValueError("unsupported golden checkpoint schema")
    if checkpoint.get("selected_layer_index") != recipe["probe"]["checkpoint_layer"]:
        raise ValueError("checkpoint layer does not match recipe")
    if checkpoint.get("selected_positions") != [recipe["probe"]["requested_position"]]:
        raise ValueError("checkpoint position does not match recipe")
    if tuple(state["probe.weight"].shape) != (1, expected_width):
        raise ValueError("probe width does not match model family")
    if state["input_mean"].numel() != expected_width or state["input_std"].numel() != expected_width:
        raise ValueError("checkpoint normalization width mismatch")
    if not torch.all(torch.isfinite(state["input_std"])) or torch.any(state["input_std"] <= 0):
        raise ValueError("checkpoint normalization is invalid")

    positive = sum(int(case["label"]) for case in cases)
    negative = len(cases) - positive
    counts: dict[tuple[str, int], int] = {}
    for case in cases:
        if "prompt_token_ids" in case or "features" in case:
            raise ValueError("golden cases must not embed token arrays or hidden features")
        key = (str(case["grid_point_id"]), int(case["label"]))
        counts[key] = counts.get(key, 0) + 1
    if any(count != 2 for count in counts.values()) or len(counts) != 32:
        raise ValueError("golden cases are not 2x2 stratified over 16 grid points")
    expected = recipe["cases"]
    if (len(cases), positive, negative) != (
        expected["total"],
        expected["positive"],
        expected["negative"],
    ):
        raise ValueError("golden case balance does not match recipe")
    return {
        "recipe_id": recipe["recipe_id"],
        "cases": len(cases),
        "positive": positive,
        "negative": negative,
        "grid_points": len({case["grid_point_id"] for case in cases}),
        "checkpoint_id": f"sha256:{recipe['probe']['sha256']}",
        "vllm_version": runtime["vllm_version"],
        "vllm_overlay_files": len(manifest["files"]),
    }


async def run_online(
    *,
    recipe_dir: Path,
    base_url: str,
    model: str,
    concurrency: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    recipe, cases = load_recipe(recipe_dir)
    settings = SimpleNamespace(
        inline_probing_timeout_seconds=120.0,
        inline_probing_threshold=float(recipe["probe"]["threshold"]),
        inline_probing_expected_checkpoint_id=f"sha256:{recipe['probe']['sha256']}",
        inline_probing_protocol="inline_probing",
        vllm_model=model,
        vllm_base_url=base_url,
        vllm_api_key="EMPTY",
    )
    guard = InlineProbingGuard(settings)
    semaphore = asyncio.Semaphore(concurrency)

    async def run_case(case: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            assessment = await guard.moderate_messages(
                case["messages"],
                tools=case.get("tools"),
                tool_choice=case.get("tool_choice"),
            )
        raw = json.loads(assessment.raw_output) if assessment.raw_output else {}
        return {
            "case_index": case["case_index"],
            "decision_point_id": case["decision_point_id"],
            "label": case["label"],
            "score": assessment.score,
            "logit": assessment.logit,
            "prediction": None if assessment.risky is None else int(assessment.risky),
            "error": assessment.error,
            "prompt_fingerprint_match": raw.get("native_prompt_token_fingerprint")
            == case["expected_prompt_token_fingerprint"],
            "score_absolute_delta": None
            if assessment.score is None
            else abs(assessment.score - case["reference_online_score"]),
        }

    try:
        rows = await asyncio.gather(*(run_case(case) for case in cases))
    finally:
        await guard.close()

    tn = fp = fn = tp = 0
    for row in rows:
        pair = (row["label"], row["prediction"])
        if pair == (0, 0):
            tn += 1
        elif pair == (0, 1):
            fp += 1
        elif pair == (1, 0):
            fn += 1
        elif pair == (1, 1):
            tp += 1
    summary = {
        "cases": len(rows),
        "errors": sum(row["error"] is not None for row in rows),
        "prompt_fingerprint_matches": sum(row["prompt_fingerprint_match"] for row in rows),
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        "max_score_absolute_delta": max(
            row["score_absolute_delta"] or 0.0 for row in rows
        ),
    }
    reference = recipe["reference_metrics"]["sample64_online"]
    for key in ("tn", "fp", "fn", "tp"):
        if summary[key] != reference[key]:
            raise RuntimeError(f"golden online {key} mismatch: {summary[key]} != {reference[key]}")
    if summary["errors"] or summary["prompt_fingerprint_matches"] != len(rows):
        raise RuntimeError("golden online request or prompt fingerprint failure")
    if summary["max_score_absolute_delta"] > reference["max_score_absolute_delta"]:
        raise RuntimeError("golden online score drift exceeded tolerance")
    return summary, rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the Qwen3-8B indirect-prompt-injection "
            "assistant-prefix probing golden recipe"
        )
    )
    parser.add_argument("--recipe-dir", type=Path, default=RECIPE_DIR)
    parser.add_argument("--base-url")
    parser.add_argument("--model", default="qwen3-8b")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_recipe(args.recipe_dir), indent=2, sort_keys=True))
    if args.base_url:
        summary, rows = asyncio.run(
            run_online(
                recipe_dir=args.recipe_dir,
                base_url=args.base_url,
                model=args.model,
                concurrency=args.concurrency,
            )
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
            )


if __name__ == "__main__":
    main()
