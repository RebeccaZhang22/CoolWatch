"""Load complete activation shards in their original sample order."""
from pathlib import Path
from typing import Any
import numpy as np
import torch

def load_shards(
    features_dir: Path,
) -> tuple[torch.Tensor, list[dict[str, Any]], dict[str, Any]]:
    paths = sorted(features_dir.glob("shard_*_of_*.pt"))
    if not paths:
        raise FileNotFoundError(f"No activation shards under {features_dir}")
    shards = [torch.load(path, map_location="cpu", weights_only=False) for path in paths]
    if len(shards) != int(shards[0]["num_shards"]):
        raise ValueError(f"Expected {shards[0]['num_shards']} shards, found {len(paths)}")
    reference_layers = [int(value) for value in shards[0]["layer_indices"]]
    for shard in shards[1:]:
        for key in ("model_path", "model_type", "num_layers", "hidden_size", "max_length"):
            if shard[key] != shards[0][key]:
                raise ValueError(f"Inconsistent {key} across feature shards")
        if [int(value) for value in shard["layer_indices"]] != reference_layers:
            raise ValueError("Inconsistent layer_indices across feature shards")
    if set(shards[0]["features"]) != {"residual"}:
        raise ValueError("Nonlinear unified probe expects residual-only activation shards")
    features = torch.cat([shard["features"]["residual"] for shard in shards], dim=0)
    metadata = [row for shard in shards for row in shard["metadata"]]
    order = np.argsort([int(row["sample_index"]) for row in metadata])
    order_tensor = torch.tensor(order, dtype=torch.long)
    features = features[order_tensor]
    metadata = [metadata[index] for index in order]
    if len({str(row["sample_id"]) for row in metadata}) != len(metadata):
        raise ValueError("Duplicate sample_id in activation cache")
    info = {
        key: shards[0][key]
        for key in ("model_path", "model_type", "num_layers", "hidden_size", "max_length")
    }
    info["layer_indices"] = reference_layers
    return features, metadata, info

