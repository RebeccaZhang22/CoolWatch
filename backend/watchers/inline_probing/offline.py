from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from .client import InlineProbingAssessment


class OfflineInlineProbingGuard:
    """Score frozen feature shards without replaying the model request."""

    def __init__(
        self,
        *,
        checkpoint_path: str | Path,
        feature_root: str | Path,
        threshold: float,
    ) -> None:
        import torch

        self._torch = torch
        self.checkpoint_path = Path(checkpoint_path).resolve()
        self.feature_root = Path(feature_root).resolve()
        self.threshold = float(threshold)
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("offline probe threshold must be between 0 and 1")
        self.checkpoint_id = f"sha256:{_sha256_file(self.checkpoint_path)}"
        self._checkpoint = torch.load(
            self.checkpoint_path,
            map_location="cpu",
            weights_only=False,
        )
        self._validate_checkpoint()
        self._feature_name = str(self._checkpoint["feature_name"])
        self._layer_indices = [
            int(value) for value in self._checkpoint["selected_layer_indices"]
        ]
        self._feature_cache: dict[str, tuple[dict[str, int], Any, dict[str, Any]]] = {}

    async def close(self) -> None:
        self._feature_cache.clear()

    async def moderate_decision_point(
        self,
        *,
        decision_point_id: str,
        grid_point_id: str,
    ) -> InlineProbingAssessment:
        started = perf_counter()
        try:
            row_indices, features, metadata = self._load_grid_point(grid_point_id)
            if decision_point_id not in row_indices:
                raise KeyError(
                    f"decision point is absent from frozen features: {decision_point_id}"
                )
            row_index = row_indices[decision_point_id]
            logit = self._score(features[row_index])
            score = 1.0 / (1.0 + math.exp(-logit))
            raw = {
                "mode": "offline_frozen_feature",
                "feature_name": self._feature_name,
                "feature_backend": metadata.get("backend"),
                "feature_model_id": metadata.get("model_id"),
                "grid_point_id": grid_point_id,
                "decision_point_id": decision_point_id,
            }
            return InlineProbingAssessment(
                score=score,
                logit=logit,
                threshold=self.threshold,
                checkpoint_id=self.checkpoint_id,
                layer=self._layer_indices[0] if len(self._layer_indices) == 1 else None,
                effective_position=_single_position(metadata.get("selected_positions")),
                protocol="offline_frozen_feature",
                raw_output=json.dumps(raw, ensure_ascii=False, sort_keys=True),
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except Exception as error:
            return InlineProbingAssessment(
                score=None,
                logit=None,
                threshold=self.threshold,
                checkpoint_id=self.checkpoint_id,
                layer=self._layer_indices[0] if len(self._layer_indices) == 1 else None,
                effective_position=None,
                protocol="offline_frozen_feature",
                raw_output="",
                latency_ms=round((perf_counter() - started) * 1000),
                error=str(error),
            )

    def _validate_checkpoint(self) -> None:
        checkpoint = self._checkpoint
        if checkpoint.get("schema") != "fyh.probe_checkpoint.v2":
            raise ValueError("unsupported offline probe checkpoint schema")
        if checkpoint.get("probe_architecture") != "linear":
            raise ValueError("offline frozen-feature scoring currently requires a linear probe")
        if checkpoint.get("feature_composition") != "single_layer":
            raise ValueError("offline frozen-feature scoring requires single_layer features")
        selected_layers = checkpoint.get("selected_layer_indices")
        if not isinstance(selected_layers, list) or not selected_layers:
            raise ValueError("offline probe checkpoint has no selected layers")
        state = checkpoint.get("model_state_dict")
        required = {"input_mean", "input_std", "probe.weight", "probe.bias"}
        if not isinstance(state, Mapping) or not required.issubset(state):
            raise ValueError("offline probe checkpoint has an unsupported state dict")
        expected_width = int(checkpoint["input_dim"])
        if state["input_mean"].numel() != expected_width:
            raise ValueError("offline probe normalization width mismatch")
        if state["input_std"].numel() != expected_width:
            raise ValueError("offline probe normalization width mismatch")
        if state["probe.weight"].numel() != expected_width:
            raise ValueError("offline probe weight width mismatch")
        if self._torch.any(state["input_std"] <= 0):
            raise ValueError("offline probe normalization standard deviation is invalid")

    def _load_grid_point(self, grid_point_id: str) -> tuple[dict[str, int], Any, dict[str, Any]]:
        cached = self._feature_cache.get(grid_point_id)
        if cached is not None:
            return cached
        directory = self.feature_root / self._feature_name / grid_point_id
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"frozen feature manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema") != "fyh.features.split.v1":
            raise ValueError(f"unsupported frozen feature manifest: {manifest_path}")
        decision_point_ids = [str(value) for value in manifest["decision_point_ids"]]
        layer_tensors = []
        for layer_index in self._layer_indices:
            shard_path = directory / f"L{layer_index}.pt"
            shard = self._torch.load(shard_path, map_location="cpu", weights_only=False)
            if shard.get("schema") != "fyh.features.layer.v1":
                raise ValueError(f"unsupported frozen layer shard: {shard_path}")
            if int(shard.get("layer_index")) != layer_index:
                raise ValueError(f"frozen layer index mismatch: {shard_path}")
            layer_tensors.append(shard["features"])
        features = self._torch.stack(layer_tensors, dim=1)
        if int(features.shape[0]) != len(decision_point_ids):
            raise ValueError("frozen feature rows are not aligned with decision point ids")
        row_indices = {
            decision_point_id: index
            for index, decision_point_id in enumerate(decision_point_ids)
        }
        if len(row_indices) != len(decision_point_ids):
            raise ValueError("frozen feature manifest has duplicate decision point ids")
        cached = (row_indices, features, manifest)
        self._feature_cache[grid_point_id] = cached
        return cached

    def _score(self, feature: Any) -> float:
        state = self._checkpoint["model_state_dict"]
        vector = feature.reshape(1, -1).to(dtype=self._torch.float32)
        expected_width = int(self._checkpoint["input_dim"])
        if int(vector.shape[1]) != expected_width:
            raise ValueError(
                f"frozen feature width mismatch: {vector.shape[1]} != {expected_width}"
            )
        normalized = (vector - state["input_mean"]) / state["input_std"]
        logit = normalized.matmul(state["probe.weight"].transpose(0, 1))
        logit = logit + state["probe.bias"]
        value = float(logit.item())
        if not math.isfinite(value):
            raise ValueError("offline probe produced a non-finite logit")
        return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _single_position(value: object) -> int | None:
    if isinstance(value, list) and len(value) == 1:
        return int(value[0])
    return None
