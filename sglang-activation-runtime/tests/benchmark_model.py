"""Measure capture costs on a real model; cache disabled for equal forward work."""
import asyncio
import json
import os
from pathlib import Path
import statistics
import time

ENABLED=os.environ.get("ACTIVATION_BENCH_ENABLE","1")=="1"
os.environ["SGLANG_ACTIVATION_CAPTURE"]="1" if ENABLED else "0"
import sglang

ROOT=Path(__file__).resolve().parents[1]
MODEL=os.environ.get("ACTIVATION_BENCH_MODEL","/mnt/kpfs_qyang/yutongz/models/Qwen3-8B")


async def run(engine):
    async def batch(concurrency,capture):
        params={"max_new_tokens":32,"temperature":0,"ignore_eos":True}
        return await asyncio.gather(*(engine.async_generate(
            input_ids=list(range(3,131)),sampling_params=params,activation_capture=capture)
            for _ in range(concurrency)))
    results=[]
    for concurrency in (1,8,16):
        for label,tokens in [("no_capture",None),("last_prompt",{"prompt":"last","generated":"none"}),
                             ("all_prompt_and_decode",{"prompt":"all","generated":"processed"})]:
            if not ENABLED and tokens is not None:
                continue
            capture=None if tokens is None else {"targets":[{"layer":9,"site":"block_output"},
                {"layer":19,"site":"block_output"}],"tokens":tokens,"encoding":"base64"}
            await batch(concurrency,capture)
            times=[]
            for _ in range(3):
                start=time.perf_counter();outputs=await batch(concurrency,capture)
                times.append(time.perf_counter()-start)
            size=sum(sum(len(c["data"]) for c in o["meta_info"].get("activations",{}).get("chunks",[])) for o in outputs)
            results.append({"concurrency":concurrency,"mode":label,"median_seconds":statistics.median(times),
                "output_tokens_per_second":concurrency*32/statistics.median(times),"base64_response_bytes":size})
            print(results[-1],flush=True)
    report={"model":MODEL,"prompt_tokens":128,"output_tokens":32,"targets":[9,19],
            "cache_enabled":False,"capture_feature_enabled":ENABLED,"shared_gpu":True,"results":results}
    name="benchmark-real-model.json" if ENABLED else "benchmark-feature-disabled.json"
    (ROOT/"artifacts"/name).write_text(json.dumps(report,indent=2))


if __name__=="__main__":
    engine=sglang.Engine(model_path=MODEL,dtype="bfloat16",mem_fraction_static=0.8,
        max_total_tokens=4096,max_running_requests=16,context_length=512,
        chunked_prefill_size=256,cuda_graph_bs_decode=[1,8,16],
        disable_prefill_cuda_graph=True,disable_radix_cache=True,
        attention_backend="triton",log_level="error")
    try:asyncio.run(run(engine))
    finally:engine.shutdown()
