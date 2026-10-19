"""Exercise the co-resident deployment, including request isolation and graphs."""
import asyncio
import base64
import json
from pathlib import Path
import statistics
import sys
import time

import httpx
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.activation_probe_server import ProbeBank


async def main():
    torch.set_num_threads(2)
    bank = ProbeBank(ROOT / ".runtime/models/Qwen3-8B", ROOT / "probe/qwen3-8b", .91)
    report = {"layers": bank.layers, "site": "block_output", "requests": []}
    async with httpx.AsyncClient(timeout=90) as client:
        async def post(port, route, payload):
            response = await client.post(f"http://127.0.0.1:{port}{route}", json=payload)
            response.raise_for_status()
            return response.json()

        prompts = [{"messages": [{"role": "user", "content": f"编号{i}：" + "请说明如何查询订单物流。" * (i + 1)}]} for i in range(16)]
        references = [await post(8302, "/detect", p) for p in prompts]
        async def timed_detect(payload):
            start = time.perf_counter()
            result = await post(8302, "/detect", payload)
            return result, time.perf_counter() - start

        async def chat(i):
            return await post(8104, "/v1/chat/completions", dict(model="qwen3-8b",
                messages=[{"role": "user", "content": f"用中文写一段关于春天的短文，编号{i}。"}],
                max_tokens=96, temperature=0, chat_template_kwargs={"enable_thinking": False}))

        for concurrency in (1, 8, 16, 32):
            start = time.perf_counter()
            detection = asyncio.gather(*(timed_detect(prompts[i % 16]) for i in range(concurrency)))
            chats = asyncio.gather(*(chat(i) for i in range(2)))
            outputs, chat_outputs = await asyncio.gather(detection, chats)
            score_errors = []
            for i, (out, _) in enumerate(outputs):
                ref = references[i % 16]
                assert out["input_tokens"] == ref["input_tokens"]
                for risk in bank.layers:
                    error = abs(out["per_risk"][risk]["score"] - ref["per_risk"][risk]["score"])
                    score_errors.append(error)
                    assert error < 1e-6, (i, risk, error)
                    assert out["per_risk"][risk]["flagged"] == ref["per_risk"][risk]["flagged"]
            assert all(o["choices"][0]["message"]["content"] for o in chat_outputs)
            latencies = sorted(t for _, t in outputs)
            row = dict(concurrency=concurrency, simultaneous_chat_requests=2,
                       wall_seconds=time.perf_counter()-start, probe_median_seconds=statistics.median(latencies),
                       probe_max_seconds=max(latencies), completed=len(outputs),
                       max_score_delta=max(score_errors))
            report["requests"].append(row)
            print(row, flush=True)

        # Different layer/site selections in the same continuous decode batch.
        payloads = []
        for i in range(8):
            target = dict(layer=9 if i % 2 else 19, site="ffn_output" if i % 3 else "block_output")
            payloads.append(dict(input_ids=list(range(100 + i, 132 + i)),
                sampling_params=dict(max_new_tokens=6, temperature=0, ignore_eos=True),
                activation_capture=dict(targets=[target], tokens=dict(prompt="last", generated="processed"), encoding="base64")))
        native = await asyncio.gather(*(post(8303, "/generate", p) for p in payloads))
        for payload, out in zip(payloads, native):
            chunks = out["meta_info"]["activations"]["chunks"]
            target = payload["activation_capture"]["targets"][0]
            positions = []
            for chunk in chunks:
                assert all(chunk[k] == target[k] for k in ("layer", "site"))
                assert len(base64.b64decode(chunk["data"])) == len(chunk["positions"]) * 4096 * 2
                positions.extend(chunk["positions"])
            assert sorted(positions) == list(range(31, 37)), positions
            assert any(c["execution"] == "cuda_graph" for c in chunks)
        report["dynamic_layers_and_decode_graph"] = "pass"

        # Chunked prefill followed by a cached replay still captures the last token.
        ids = bank.render({"messages": [{"role": "user", "content": "这是一条用于长上下文校验的信息。" * 450}]})
        assert 4096 < len(ids) < 16384
        long_request = dict(input_ids=ids, sampling_params=dict(max_new_tokens=1, temperature=0), activation_capture=bank.capture)
        vectors = [bank.decode(await post(8303, "/generate", long_request), ids) for _ in range(2)]
        for layer in bank.layers.values():
            torch.testing.assert_close(vectors[0][layer], vectors[1][layer], atol=.04, rtol=.04)
        report["chunked_and_cached_prompt_tokens"] = len(ids)
        for invalid, code in [({"messages": []}, 400), ({"messages": "wrong"}, 400)]:
            response = await client.post("http://127.0.0.1:8302/detect", json=invalid)
            assert response.status_code == code
        report["stats"] = (await client.get("http://127.0.0.1:8302/batch-stats")).json()
    path = ROOT / ".runtime/activation-gpu7/live-validation.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("PASS:", path)


if __name__ == "__main__":
    asyncio.run(main())
