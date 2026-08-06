#!/usr/bin/env python3
"""Generate the deterministic, non-detecting Inline Probe holder checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

import torch


CHECKPOINT_SCHEMA = "inline_probing.probe_checkpoint.v2"
TASK = "system_prompt_leakage_intent"
MODEL_ID = "Qwen/Qwen3-8B"
HIDDEN_WIDTH = 4096
TARGET_LAYER = 4
TARGET_POSITION = -1
PLACEHOLDER_SCORE = 1e-6


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_checkpoint() -> dict:
    bias = math.log(PLACEHOLDER_SCORE / (1.0 - PLACEHOLDER_SCORE))
    return {
        "schema": CHECKPOINT_SCHEMA,
        "checkpoint_role": "non_detecting_placeholder",
        "placeholder": True,
        "trained": False,
        "task": TASK,
        "labeling_protocol": "placeholder_only",
        "model_id": MODEL_ID,
        "input_dim": HIDDEN_WIDTH,
        "feature_composition": "single_layer",
        "selected_layer_index": TARGET_LAYER,
        "selected_layer_indices": [TARGET_LAYER],
        "selected_positions": [TARGET_POSITION],
        "probe_architecture": "linear",
        "placeholder_contract": {
            "meaning": "Exercises residual capture and worker-side scoring only.",
            "security_detector": False,
            "constant_score": PLACEHOLDER_SCORE,
        },
        "model_state_dict": {
            "input_mean": torch.zeros(HIDDEN_WIDTH, dtype=torch.float32),
            "input_std": torch.ones(HIDDEN_WIDTH, dtype=torch.float32),
            "probe.weight": torch.zeros((1, HIDDEN_WIDTH), dtype=torch.float32),
            "probe.bias": torch.tensor([bias], dtype=torch.float32),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("probe.pt"),
        help="Checkpoint path (default: probe.pt next to this script).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        build_checkpoint(),
        output,
        pickle_protocol=2,
    )
    checkpoint = torch.load(output, map_location="cpu", weights_only=True)
    bias = checkpoint["model_state_dict"]["probe.bias"].item()
    score = torch.sigmoid(torch.tensor(bias, dtype=torch.float32)).item()
    print(f"path={output}")
    print(f"sha256={sha256_file(output)}")
    print(f"constant_score={score:.9g}")


if __name__ == "__main__":
    main()
