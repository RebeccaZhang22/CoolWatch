import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "src/run_qwen3guard_heldout.py"
spec = importlib.util.spec_from_file_location("qwen3guard_heldout_eval", path)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvaluationTests(unittest.TestCase):
    def test_auc_ties_and_reversed_ranking(self):
        rows = [{"label": 0, "unsafe_score": .2}, {"label": 1, "unsafe_score": .8},
                {"label": 0, "unsafe_score": .5}, {"label": 1, "unsafe_score": .5}]
        self.assertAlmostEqual(evaluation.auroc(rows), .875)
        for row in rows:
            row["unsafe_score"] = 1 - row["unsafe_score"]
        self.assertAlmostEqual(evaluation.auroc(rows), .125)

    def test_errors_are_not_treated_as_safe(self):
        rows = [dict(id="a", face="heldout_swe", label=1, status="error", error_type="TimeoutError"),
                dict(id="b", face="heldout_swe", label=1, status="ok", safety="Unsafe",
                     categories=["Jailbreak"], unsafe_score=.9)]
        summary = evaluation.summarize(rows, {face: 2 for face in evaluation.FACES})["heldout_swe"]
        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["valid"], 1)
        self.assertEqual(summary["errors"], {"TimeoutError": 1})
        self.assertEqual(summary["unsafe"]["recall"], 1)

    def test_controversial_and_jailbreak_are_separate_rules(self):
        rows = [dict(face="heldout_swe", label=1, status="ok", safety="Controversial",
                     categories=["Jailbreak"], unsafe_score=.2)]
        summary = evaluation.summarize(rows, {face: 1 for face in evaluation.FACES})["heldout_swe"]
        self.assertEqual(summary["unsafe"]["fn"], 1)
        self.assertEqual(summary["unsafe_or_controversial"]["tp"], 1)
        self.assertEqual(summary["jailbreak"]["tp"], 1)

    def test_invalid_generation_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluation.parse_prediction({"text": "probably safe"}, [1, 2], [3, 4, 5])


if __name__ == "__main__":
    unittest.main()
