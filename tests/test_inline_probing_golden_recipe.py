from __future__ import annotations

import json

from backend.watchers.inline_probing.golden_recipe import RECIPE_DIR, validate_recipe


def test_qwen3_8b_golden_recipe_is_self_contained_without_hidden_features() -> None:
    result = validate_recipe()

    assert result["cases"] == 64
    assert result["positive"] == 32
    assert result["negative"] == 32
    assert result["grid_points"] == 16
    assert result["vllm_version"] == "0.25.1"
    assert result["vllm_overlay_files"] == 12
    assert not list(RECIPE_DIR.glob("*feature*"))
    assert RECIPE_DIR.parent.name == "inline_probing"
    assert RECIPE_DIR.parent.parent.name == "recipe"
    recipe = json.loads((RECIPE_DIR / "recipe.json").read_text())
    labeling = recipe["task"]["labeling"]
    assert labeling["protocol"] == "risk_faced"
    assert labeling["unit"] == "assistant_decision_point"
    assert "first assistant decision point" in labeling["positive_class"]
    assert "the attack succeeded" in labeling["does_not_mean"]
    server = recipe["runtime_contract"]["server"]
    assert server["entrypoint"] == "vllm_server_control_with_probe_enabled.sh"
    assert server["commands"] == ["start", "status", "stop"]
