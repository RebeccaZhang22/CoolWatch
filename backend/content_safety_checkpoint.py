"""Validated loader for the packaged Qwen3.5-2B content-safety probes."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import torch


class ContentSafetyCheckpoint:
    def __init__(self, path: str | Path, *, model: str, hidden_size: int, num_layers: int):
        path = Path(path)
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        contract = checkpoint.get("model_contract", {})
        if (checkpoint.get("schema") != "prospectmonitor.content_safety_probe.v1"
                or checkpoint.get("risk") != "harmful"
                or contract.get("model") != model
                or contract.get("hidden_size") != hidden_size
                or contract.get("num_layers") != num_layers
                or checkpoint.get("fusion") != "max"):
            raise ValueError("Unsupported content-safety checkpoint contract")

        entries = checkpoint.get("entries", [])
        if {entry.get("id") for entry in entries} != {"harmful/m1", "harmful/m2"}:
            raise ValueError("Content-safety checkpoint must contain harmful/m1 and harmful/m2")
        for entry in entries:
            state = entry.get("state", {})
            vectors = [state.get("weight"), state.get("scaler_mean"), state.get("scaler_std")]
            if any(not isinstance(value, torch.Tensor) or value.numel() != hidden_size for value in vectors):
                raise ValueError("Invalid content-safety probe dimensions")
            if any(not torch.isfinite(value).all() for value in vectors) or not (state["scaler_std"] > 0).all():
                raise ValueError("Invalid content-safety probe parameters")
            scalars = [state.get("bias"), state.get("calibration_mean"), state.get("calibration_std")]
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in scalars):
                raise ValueError("Invalid content-safety calibration parameters")
            layer = entry.get("layer_hf")
            if not isinstance(layer, int) or not 1 <= layer <= num_layers:
                raise ValueError("Invalid content-safety tap layer")

        thresholds = checkpoint.get("thresholds", {})
        if set(thresholds) != {"strict", "balanced", "lenient"} or any(
                not isinstance(value, (int, float)) or not 0 < value < 1
                for value in thresholds.values()):
            raise ValueError("Invalid content-safety thresholds")
        self.checkpoint = checkpoint

    def to_detector_bank(self) -> dict:
        checkpoint = self.checkpoint
        contract = checkpoint["model_contract"]
        entries = []
        for source in checkpoint["entries"]:
            state = source["state"]
            entries.append({
                key: value for key, value in source.items() if key != "state"
            } | {
                "w": state["weight"].reshape(-1).tolist(),
                "b": float(state["bias"]),
                "scaler_mu": state["scaler_mean"].reshape(-1).tolist(),
                "scaler_sd": state["scaler_std"].reshape(-1).tolist(),
                "cal_mu": float(state["calibration_mean"]),
                "cal_sd": float(state["calibration_std"]),
            })
        return {
            "model": contract["model"],
            "hidden": contract["hidden_size"],
            "n_layers": contract["num_layers"],
            "protocol": checkpoint["training_protocol"],
            "rel_depths": checkpoint["relative_depths"],
            "layer_union": sorted({entry["layer_hf"] for entry in entries}),
            "thresholds": {"harmful": checkpoint["thresholds"]},
            "calibration": checkpoint["calibration"],
            "fusion": checkpoint["fusion"],
            "entries": entries,
        }
