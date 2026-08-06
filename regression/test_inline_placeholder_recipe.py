from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import torch

from backend.watchers.safegauge.client import RESULTS_DIR, TASK_CHECKPOINTS


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_DIR = (
    ROOT
    / "recipe/inline_probing/qwen3-8b-system-prompt-leakage-placeholder"
)
RECIPE_PATH = PLACEHOLDER_DIR / "recipe.json"
CHECKPOINT_PATH = PLACEHOLDER_DIR / "probe.pt"
GENERATOR_PATH = PLACEHOLDER_DIR / "generate_placeholder.py"
OVERLAY_INLINE = (
    ROOT
    / "recipe/inline_probing/"
    "qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/"
    "vllm-0.25.1-overlay/vllm/v1/inline_probing.py"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_overlay_inline_module():
    spec = importlib.util.spec_from_file_location(
        "test_placeholder_overlay_inline", OVERLAY_INLINE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PlaceholderRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.recipe = json.loads(RECIPE_PATH.read_text())

    def test_checkpoint_is_explicitly_non_detecting_and_runtime_compatible(self):
        recipe = self.recipe
        probe = recipe["probe"]
        self.assertEqual(recipe["task"]["id"], "system_prompt_leakage_intent")
        self.assertFalse(recipe["placeholder_contract"]["security_detector"])
        self.assertFalse(probe["trained"])
        self.assertEqual(sha256_file(CHECKPOINT_PATH), probe["sha256"])

        payload = torch.load(CHECKPOINT_PATH, map_location="cpu", weights_only=True)
        state = payload["model_state_dict"]
        self.assertEqual(payload["schema"], "inline_probing.probe_checkpoint.v2")
        self.assertTrue(payload["placeholder"])
        self.assertFalse(payload["trained"])
        self.assertEqual(payload["selected_layer_index"], probe["checkpoint_layer"])
        self.assertEqual(payload["selected_positions"], [probe["requested_position"]])
        self.assertEqual(tuple(state["probe.weight"].shape), (1, 4096))
        self.assertTrue(torch.count_nonzero(state["probe.weight"]) == 0)

        module = load_overlay_inline_module()
        config = module.InlineProbingConfig(
            schema=module.CONFIG_SCHEMA,
            checkpoint_schema=module.CHECKPOINT_SCHEMA,
            scorer_contract_version=module.SCORER_CONTRACT,
            checkpoint_path=str(CHECKPOINT_PATH),
            checkpoint_sha256=probe["sha256"],
            model_family=recipe["model"]["model_family"],
            model_revision=recipe["model"]["model_revision"],
            target_layer=probe["checkpoint_layer"],
            requested_position=probe["requested_position"],
            effective_position=probe["effective_position"],
            activation_kind=recipe["task"]["activation_kind"],
            hidden_width=recipe["model"]["hidden_width"],
            normalization="checkpoint",
            tensor_parallel_size=1,
            pipeline_parallel_size=1,
        )
        resolved = module.load_resolved_checkpoint(config)
        scorer = module.InlineLinearProbe(resolved, torch.device("cpu"))
        activations = torch.randn(3, recipe["model"]["hidden_width"])
        logits, scores = scorer.score_batch(activations)

        self.assertTrue(torch.allclose(logits, logits[0].expand_as(logits)))
        self.assertTrue(torch.allclose(scores, scores[0].expand_as(scores)))
        self.assertAlmostEqual(scores[0].item(), probe["constant_score"], places=9)
        self.assertLess(scores[0].item(), probe["threshold"])

    def test_generator_reproduces_committed_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="coolwatch-inline-holder-") as temp_dir:
            output = Path(temp_dir) / "probe.pt"
            subprocess.run(
                [sys.executable, str(GENERATOR_PATH), "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(sha256_file(output), self.recipe["probe"]["sha256"])

    def test_safegauge_routes_to_moved_checkpoint_directory(self):
        self.assertEqual(RESULTS_DIR, ROOT / "results/gauge_probe")
        for task_checkpoints in TASK_CHECKPOINTS.values():
            for checkpoint in task_checkpoints.values():
                self.assertTrue(checkpoint.is_file(), checkpoint)


if __name__ == "__main__":
    unittest.main()
