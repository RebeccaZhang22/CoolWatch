"""One-time converter for the original DetectorCore JSON bank."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    bank = json.loads(args.source.read_text(encoding="utf-8"))
    entries = []
    for source in bank["entries"]:
        if source["risk"] != "harmful":
            continue
        metadata = {
            key: value for key, value in source.items()
            if key not in {"w", "b", "scaler_mu", "scaler_sd", "cal_mu", "cal_sd"}
        }
        metadata["state"] = {
            "weight": torch.tensor(source["w"], dtype=torch.float64),
            "bias": float(source["b"]),
            "scaler_mean": torch.tensor(source["scaler_mu"], dtype=torch.float64),
            "scaler_std": torch.tensor(source["scaler_sd"], dtype=torch.float64),
            "calibration_mean": float(source["cal_mu"]),
            "calibration_std": float(source["cal_sd"]),
        }
        entries.append(metadata)
    checkpoint = {
        "schema": "prospectmonitor.content_safety_probe.v1",
        "risk": "harmful",
        "model_contract": {
            "model": bank["model"],
            "hidden_size": bank["hidden"],
            "num_layers": bank["n_layers"],
        },
        "training_protocol": bank["protocol"],
        "relative_depths": bank["rel_depths"],
        "calibration": bank["calibration"],
        "fusion": bank["fusion"],
        "thresholds": bank["thresholds"]["harmful"],
        "entries": entries,
    }
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    torch.save(checkpoint, args.destination)


if __name__ == "__main__":
    main()
