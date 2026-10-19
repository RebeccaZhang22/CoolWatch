"""Contract validation for the production probe adapter (CPU only)."""
import base64
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import torch
from backend.activation_probe_server import ProbeBank

ROOT = Path(__file__).resolve().parents[2]


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.bank = ProbeBank(ROOT / ".runtime/models/Qwen3-8B", ROOT / "probe/qwen3-8b", .91,
                             enabled_risks="harmful,prompt_leakage,ipi")

    def response(self):
        raw = torch.arange(4096).to(torch.bfloat16).view(torch.uint8).numpy().tobytes()
        return {"meta_info": {"activations": dict(alignment="input_token", encoding="base64", byte_order="little",
            chunks=[dict(layer=l, site="block_output", positions=[2], token_ids=[13], shape=[1, 4096],
                         dtype="bfloat16", data=base64.b64encode(raw).decode()) for l in self.bank.layers.values()])}}

    def test_checkpoint_layers_and_scores(self):
        self.assertEqual(self.bank.layers, {"harmful": 21, "prompt_leakage": 14, "ipi": 22})
        result = self.bank.score(self.bank.decode(self.response(), [11, 12, 13]), 3)
        self.assertEqual(set(result["per_risk"]), set(self.bank.layers))
        self.assertTrue(all(0 <= r["score"] <= 1 for r in result["per_risk"].values()))

    def test_wrong_request_or_site_fails_closed(self):
        for key, value in [("positions", [1]), ("token_ids", [99]), ("layer", 20),
                           ("site", "ffn_output"), ("shape", [4096]), ("dtype", "float16"),
                           ("data", "invalid"), ("data", "AA==")]:
            with self.subTest(key=key, value=value):
                response = self.response()
                response["meta_info"]["activations"]["chunks"][0][key] = value
                with self.assertRaises(ValueError):
                    self.bank.decode(response, [11, 12, 13])

    def test_missing_duplicate_and_nonfinite_fail_closed(self):
        for mode in ("missing", "duplicate", "nonfinite"):
            response = self.response()
            chunks = response["meta_info"]["activations"]["chunks"]
            if mode == "missing":
                chunks.pop()
            elif mode == "duplicate":
                chunks.append(copy.deepcopy(chunks[0]))
            else:
                raw = torch.full((4096,), float("nan"), dtype=torch.bfloat16).view(torch.uint8).numpy().tobytes()
                chunks[0]["data"] = base64.b64encode(raw).decode()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.bank.decode(response, [11, 12, 13])

    def test_prompt_contract_and_tool_normalization(self):
        ids = self.bank.render({"messages": [{"role": "user", "content": "你好"}]})
        rendered = self.bank.tokenizer.decode(ids)
        self.assertTrue(rendered.endswith("<|im_start|>assistant\n"))
        self.assertNotIn("</think>", rendered)
        messages = [{"role": "user", "content": "查找"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "a", "type": "function", "function": {"name": "find", "arguments": '{"q":"x"}'}}]},
                    {"role": "tool", "tool_call_id": "a", "content": "结果"}]
        self.assertTrue(self.bank.render({"messages": messages}))


if __name__ == "__main__":
    unittest.main()
