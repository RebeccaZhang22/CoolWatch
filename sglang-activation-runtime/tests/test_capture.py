import os
from types import SimpleNamespace as NS

import unittest
from unittest.mock import patch
import torch

from sglang.srt.activation_capture.spec import validate, selected_positions, prefix_limit
from sglang.srt.activation_capture.runtime import Recorder, HostOutput, Segment, make_plan


def spec(layer=1, prompt="all", generated="processed"):
    return {"targets": [{"layer": layer, "site": "block_output"}],
            "tokens": {"prompt": prompt, "generated": generated}, "encoding": "base64"}


def mode(decode):
    return NS(is_decode=lambda: decode, is_extend=lambda: not decode)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"SGLANG_ACTIVATION_CAPTURE": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_unverified_moe_rejected(self):
        from sglang.srt.activation_capture import runtime
        runner = NS(is_draft_worker=False, device="cuda", server_args=NS(),
                    spec_algorithm=NS(is_none=lambda: True),
                    model_config=NS(hf_config=NS(
                        architectures=["Qwen3_5MoeForCausalLM"], model_type="qwen3_5_moe_text")))
        with patch.object(runtime, "_recorder", None), self.assertRaisesRegex(ValueError, "MoE"):
            runtime.initialize(runner)

    def test_validation(self):
        args = dict(num_layers=4, hidden_size=128, prompt_len=8, max_new_tokens=4)
        assert validate(spec(), **args) == spec()
        for invalid in [spec(-1), spec(4), spec(True), spec(prompt=[8]),
                        {**spec(), "targets": []}, {**spec(), "dtype": "float16"},
                        spec(generated="all")]:
            with self.assertRaises(ValueError):
                validate(invalid, **args)
        s = spec(prompt=[4, 2, 2])
        assert validate(s, **args)["tokens"]["prompt"] == [2, 4]


    def test_budget(self):
        os.environ["SGLANG_ACTIVATION_MAX_BYTES"] = "1024"
        with self.assertRaisesRegex(ValueError, "raw bytes"):
            validate(spec(), num_layers=4, hidden_size=128, prompt_len=8, max_new_tokens=4)


    def test_chunk_positions_and_prefix(self):
        assert selected_positions(spec(prompt="last"), 0, 3, 8) == []
        assert selected_positions(spec(prompt="last"), 6, 4, 8) == [7, 8, 9]
        r = NS(activation_capture=spec(), origin_input_ids=list(range(8)))
        assert prefix_limit(r, 7) == 0
        r._activation_seen = {(0, i) for i in range(4)}
        assert prefix_limit(r, 7) == 4
        r.activation_capture = spec(prompt="last")
        assert prefix_limit(r, 7) == 7


    def test_mixed_batch_offsets(self):
        batch = NS(forward_mode=mode(False), extend_lens=[3, 2, 4], prefix_lens=[2, 0, 7],
            reqs=[NS(rid="plain", activation_capture=None),
                  NS(rid="b", activation_capture=spec(), origin_input_ids=[1]*2),
                  NS(rid="c", activation_capture=spec(prompt="last"), origin_input_ids=[1]*11)])
        plans = make_plan(batch)
        assert [(p["rid"],p["row_start"],p["positions"]) for p in plans] == [
            ("b", 3, [0, 1]), ("c", 5, [10])]


    def test_owned_cpu_chunks_and_dedup(self):
        req = NS(rid="a", is_retracted=False, origin_input_ids=[3,4,5],
                 output_ids=[6], finished_len=None)
        batch = NS(reqs=[req])
        tensor = torch.arange(12, dtype=torch.float32).reshape(3,4)
        seg = Segment("a",0,{"layer":1,"site":"block_output"},[0,1,2],0,3)
        out = HostOutput(tensor,[seg])
        out.consume(batch,[None]); out.consume(batch,[None])
        assert len(req._activation_chunks) == 1
        saved = req._activation_chunks[0]["data"]
        tensor.zero_()
        assert torch.frombuffer(bytearray(saved),dtype=torch.float32).sum() == 66


    @unittest.skipUnless(torch.cuda.is_available(), "CUDA required")
    def test_graph_dynamic_layers_and_snapshot(self):
        recorder = Recorder(4,128,4,torch.bfloat16,"cuda")
        hs = [torch.randn(4,128,device="cuda",dtype=torch.bfloat16) for _ in range(4)]
        residual = torch.randn_like(hs[0])
        fb = NS(forward_mode=mode(True), batch_size=4, activation_plan=[])
        stream = torch.cuda.Stream()
        with torch.cuda.stream(stream):
            for i in range(4): recorder.tap(i,hs[i],residual,fb)
        torch.cuda.current_stream().wait_stream(stream)
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            for i in range(4): recorder.tap(i,hs[i],residual,fb)
        def replay(layer, row, site):
            s=spec(layer);s["targets"][0]["site"]=site
            fb.activation_plan=[{"rid":"a","row_start":row,"positions":[9],"spec":s}]
            recorder.begin(fb); graph.replay();return recorder.finish()
        first=replay(1,2,"block_output")
        expected=hs[1][2]+residual[2]
        second=replay(3,0,"ffn_output")
        torch.testing.assert_close(first.tensor[0],expected,atol=0,rtol=0)
        torch.testing.assert_close(second.tensor[0],hs[3][0],atol=0,rtol=0)
        fb.activation_plan=[];recorder.begin(fb);graph.replay()
        assert recorder.finish() is None


    @unittest.skipUnless(torch.cuda.is_available(), "CUDA required")
    def test_eager_sparse_two_sites(self):
        recorder=Recorder(4,128,4,torch.bfloat16,"cuda")
        h=torch.randn(11,128,device="cuda",dtype=torch.bfloat16)
        r=torch.randn_like(h)
        s=spec(2);s["targets"].append({"layer":2,"site":"ffn_output"})
        fb=NS(forward_mode=mode(False),activation_plan=[
            {"rid":"b","spec":s,"positions":[7,9],"position_start":6,"row_start":3}])
        recorder.begin(fb);recorder.tap(2,h,r,fb);out=recorder.finish()
        torch.testing.assert_close(out.tensor[:2],(h+r)[[4,6]],atol=0,rtol=0)
        torch.testing.assert_close(out.tensor[2:],h[[4,6]],atol=0,rtol=0)

if __name__ == "__main__":
    unittest.main()
