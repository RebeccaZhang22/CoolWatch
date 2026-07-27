from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import torch

from backend.watchers.inline_probing import OfflineInlineProbingGuard


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = (
    ROOT / "evaluations" / "qwen3_8b_held_out_strict_injected_round_100_samples"
)
SCRIPT = ROOT / "scripts" / "evaluate_injected_round_guards.py"


def load_script():
    spec = importlib.util.spec_from_file_location("evaluate_injected_round_guards", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_injected_round_sample_has_100_unique_cases_across_strict_settings() -> None:
    settings = json.loads((EVALUATION_DIR / "settings.json").read_text())
    manifest = json.loads((EVALUATION_DIR / "case_manifest.json").read_text())
    cases_path = EVALUATION_DIR / manifest["cases_path"]
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()]

    assert settings["agentic_model"] == "Qwen/Qwen3-8B"
    assert settings["sampling"]["population_settings"] == 16
    assert settings["sampling"]["sample_size"] == 100
    assert settings["sampling"]["seed"] == 42
    assert manifest["case_count"] == 100
    assert manifest["population_count"] == 5618
    assert manifest["settings_represented"] == 16
    assert len(cases) == len({row["decision_point_id"] for row in cases}) == 100
    assert all(row["injection_message_indices"] for row in cases)
    assert all(
        max(row["injection_message_indices"]) < row["assistant_message_index"]
        for row in cases
    )
    assert hashlib.sha256(cases_path.read_bytes()).hexdigest() == manifest["cases_sha256"]


def test_no_guard_is_a_non_intervening_never_detect_baseline() -> None:
    module = load_script()
    result = asyncio.run(module.evaluate_one("no_guard", None, {}, {}, "injected"))

    assert result == {
        "detected": False,
        "error": None,
        "latency_ms": 0,
        "raw_output": "",
    }


def test_message_text_extracts_only_textual_message_content() -> None:
    module = load_script()
    assert module.message_text(
        {
            "role": "tool",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "image_url", "image_url": "ignored"},
                {"type": "text", "content": "second"},
            ],
        }
    ) == "first\nsecond"


def test_summary_does_not_report_unrun_guard_as_zero_percent(tmp_path: Path) -> None:
    module = load_script()
    summary = module.summarize(EVALUATION_DIR, tmp_path)

    for guard in module.GUARDS:
        assert summary["guards"][guard]["completed"] == 0
        assert summary["guards"][guard]["missing"] == 100
        assert summary["guards"][guard]["detection_rate_all_frozen_samples"] is None


def test_offline_probe_scores_a_frozen_decision_point(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "probe.pt"
    torch.save(
        {
            "schema": "fyh.probe_checkpoint.v2",
            "feature_name": "default",
            "feature_composition": "single_layer",
            "probe_architecture": "linear",
            "selected_layer_indices": [4],
            "input_dim": 2,
            "model_state_dict": {
                "input_mean": torch.zeros(1, 2),
                "input_std": torch.ones(1, 2),
                "probe.weight": torch.tensor([[1.0, -1.0]]),
                "probe.bias": torch.tensor([0.0]),
            },
        },
        checkpoint_path,
    )
    feature_dir = tmp_path / "features" / "default" / "grid-a"
    feature_dir.mkdir(parents=True)
    (feature_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "fyh.features.split.v1",
                "feature_name": "default",
                "backend": "offline_test",
                "model_id": "Qwen/Qwen3-8B",
                "selected_positions": [-1],
                "decision_point_ids": ["decision-a"],
            }
        )
    )
    torch.save(
        {
            "schema": "fyh.features.layer.v1",
            "grid_point_id": "grid-a",
            "layer_index": 4,
            "features": torch.tensor([[[2.0, 1.0]]]),
        },
        feature_dir / "L4.pt",
    )

    guard = OfflineInlineProbingGuard(
        checkpoint_path=checkpoint_path,
        feature_root=tmp_path / "features",
        threshold=0.5,
    )
    assessment = asyncio.run(
        guard.moderate_decision_point(
            decision_point_id="decision-a",
            grid_point_id="grid-a",
        )
    )

    assert assessment.error is None
    assert assessment.logit == 1.0
    assert assessment.score == 0.7310585786300049
    assert assessment.risky is True
    assert assessment.protocol == "offline_frozen_feature"
    assert assessment.layer == 4
    assert assessment.effective_position == -1
