"""Classifier definitions and checkpoint-compatible activation scoring."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn


class MultilayerResidualMLP(nn.Module):
    """Small regularized MLP over standardized, concatenated layer activations."""

    def __init__(self, input_size: int, hidden_sizes: list[int], dropout: float) -> None:
        super().__init__()
        modules: list[nn.Module] = [nn.LayerNorm(input_size, elementwise_affine=False)]
        previous = input_size
        for hidden_size in hidden_sizes:
            modules.extend(
                [
                    nn.Linear(previous, hidden_size),
                    nn.GELU(),
                    nn.Dropout(dropout),
                ]
            )
            previous = hidden_size
        modules.append(nn.Linear(previous, 1))
        self.network = nn.Sequential(*modules)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.network(values).squeeze(-1)


def checkpoint_layer_positions(checkpoint: dict[str, Any]) -> tuple[int, int]:
    return int(checkpoint["start_layer"]), int(checkpoint["end_layer"])


def score_activations(
    checkpoint: dict[str, Any], activations: torch.Tensor
) -> torch.Tensor:
    """Score [batch, selected_layers, hidden] activations on CPU or one device."""
    normalized = (
        activations.float() - checkpoint["mean"].float().to(activations.device)
    ) / checkpoint["std"].float().to(activations.device).clamp_min(1e-5)
    flattened = normalized.flatten(1)
    classifier_type = str(checkpoint.get("classifier_type", "linear"))
    if classifier_type == "linear":
        return (
            flattened @ checkpoint["weight"].float().to(flattened.device).reshape(-1)
            + checkpoint["bias"].float().to(flattened.device)
        )
    if classifier_type == "multilayer_mlp":
        architecture = checkpoint["architecture"]
        model = MultilayerResidualMLP(
            int(architecture["input_size"]),
            [int(value) for value in architecture["hidden_sizes"]],
            float(architecture["dropout"]),
        ).to(flattened.device)
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        with torch.inference_mode():
            return model(flattened)
    raise ValueError(f"Unsupported classifier_type={classifier_type!r}")
