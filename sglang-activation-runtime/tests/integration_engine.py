"""Concurrent end-to-end correctness, cache/chunk/graph checks and timing.

Run with ../python; uses an isolated tiny model and does not contact a server.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import time

os.environ["SGLANG_ACTIVATION_CAPTURE"] = "1"
import torch
import sglang
from transformers import AutoModelForCausalLM

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.environ.get("ACTIVATION_TEST_MODEL", str(ROOT / "artifacts/tiny-qwen3"))
DTYPE = os.environ.get("ACTIVATION_TEST_DTYPE", "bfloat16")


def spec(layer=1, prompt="all", generated="processed", site="block_output"):
    return {"targets": [{"layer": layer, "site": site}],
            "tokens": {"prompt": prompt, "generated": generated}, "encoding": "base64"}


def decode(chunk):
    return torch.frombuffer(bytearray(base64.b64decode(chunk["data"])),
                            dtype=getattr(torch, chunk["dtype"])).reshape(chunk["shape"])


def reference(model, ids, layer, site):
    captures = []
    module = model.model.layers[layer]
    if site == "ffn_output":
        module = module.mlp
    def save(_module, _args, output):
        value = output[0] if isinstance(output, tuple) else output
        captures.append(value.detach().clone())
    handle = module.register_forward_hook(save)
    try:
        with torch.no_grad():
            model(torch.tensor([ids],device=model.device),use_cache=False)
    finally:
        handle.remove()
    return captures[0][0].cpu()


def check(model, prompt, output, capture_spec):
    chunks=output["meta_info"]["activations"]["chunks"]
    output_ids=[item[1] for item in output["meta_info"]["output_token_logprobs"]]
    ids=prompt+output_ids
    grouped={}
    for chunk in chunks:
        key=(chunk["layer"],chunk["site"])
        for p, token, value in zip(chunk["positions"],chunk["token_ids"],decode(chunk)):
            assert ids[p] == token,(p,token,ids[p])
            assert p not in grouped.setdefault(key,{}),"duplicate exported token"
            grouped[key][p]=value
    max_error=0
    for target in capture_spec["targets"]:
        key=(target["layer"],target["site"])
        rows=grouped[key]
        prompt_selection=capture_spec["tokens"]["prompt"]
        expected_prompt=(list(range(len(prompt))) if prompt_selection=="all" else
                         [len(prompt)-1] if prompt_selection=="last" else
                         prompt_selection if isinstance(prompt_selection,list) else [])
        expected=expected_prompt+(
            list(range(len(prompt),len(ids)-1)) if capture_spec["tokens"]["generated"]=="processed" else [])
        assert sorted(rows)==expected,(sorted(rows),expected)
        gold=reference(model,ids,target["layer"],target["site"])
        positions=sorted(rows)
        actual=torch.stack([rows[p] for p in positions])
        error=(actual.float()-gold[positions].float()).abs().max().item()
        max_error=max(max_error,error)
        torch.testing.assert_close(actual,gold[positions],atol=0.003,rtol=0.04)
    return max_error


async def run(engine, model):
    params={"max_new_tokens":6,"temperature":0,"ignore_eos":True}
    async def generate(ids,s):
        return await engine.async_generate(input_ids=ids,sampling_params=params,
            return_logprob=True,activation_capture=s)
    # Cross-chunk prompt, then identical prompt again: capture must defeat a
    # cache hit only where missing activations actually require recomputation.
    prompt=list(range(3,70))
    s=spec();s["targets"].append({"layer":3,"site":"ffn_output"})
    error=0
    for _ in range(2):
        out=await generate(prompt,s);error=max(error,check(model,prompt,out,s))
        assert any(c["execution"]=="cuda_graph" for c in out["meta_info"]["activations"]["chunks"])
    last=spec(2,"last","none")
    out=await generate(prompt,last);error=max(error,check(model,prompt,out,last))
    cache_hit = out["meta_info"]["cached_tokens"] > 0
    # Hybrid SSM cache snapshots have a larger alignment than this 67-token
    # fixture; the dense model must hit, hybrid models may correctly recompute.
    if not any("linear" in t for t in getattr(model.config,"layer_types",[])):
        assert cache_hit, out["meta_info"]
    # Different layers/sites/prompts, interleaved with non-requesting rows.
    inputs=[list(range(3,8+i*2)) for i in range(16)]
    specs=[None if i%4==0 else spec(i%4,"last" if i%2 else "all",site="ffn_output" if i%3==0 else "block_output") for i in range(16)]
    outputs=await asyncio.gather(*(generate(ids,s) for ids,s in zip(inputs,specs)))
    for ids,s,out in zip(inputs,specs,outputs):
        if s is None:
            assert "activations" not in out["meta_info"]
        else:
            error=max(error,check(model,ids,out,s))
    # Stream sends deltas once; final nonstream result accumulates all chunks.
    streamed=await engine.async_generate(input_ids=inputs[1],sampling_params=params,
        return_logprob=True,activation_capture=spec(),stream=True)
    chunks=[]
    async for part in streamed:
        chunks.extend(part["meta_info"]["activations"]["chunks"])
    part["meta_info"]["activations"]["chunks"]=chunks
    error=max(error,check(model,inputs[1],part,spec()))
    # API batch normalization supports a distinct spec per request.
    batch=await engine.async_generate(input_ids=inputs[:3],sampling_params=params,
        return_logprob=True,activation_capture=[spec(0),None,spec(3)])
    for ids,s,out in zip(inputs[:3],[spec(0),None,spec(3)],batch):
        if s: error=max(error,check(model,ids,out,s))
    # A long non-stream response exercises the scheduler's forced intermediate
    # publications. Only the final response should encode the accumulated bytes.
    long_params={**params,"max_new_tokens":64}
    plain=await engine.async_generate(input_ids=inputs[1],sampling_params=long_params)
    long_out=await engine.async_generate(input_ids=inputs[1],sampling_params=long_params,
        return_logprob=True,activation_capture=spec(2,"last"))
    assert plain["text"]==long_out["text"],"capture changed greedy output"
    error=max(error,check(model,inputs[1],long_out,spec(2,"last")))
    timing=[]
    for concurrency in (1,8,16):
        for label,s in [("no_capture",None),("last_prompt",spec(1,"last","none")),
                        ("prompt_and_decode",spec())]:
            # All cases reuse the same warmed model; report measured service
            # wall time, not a hardware-isolated throughput claim.
            latencies=[]
            for _ in range(3):
                start=time.perf_counter()
                await asyncio.gather(*(generate(inputs[1],s) for _ in range(concurrency)))
                latencies.append(time.perf_counter()-start)
            elapsed=sorted(latencies)[1]
            timing.append({"concurrency":concurrency,"mode":label,
                           "median_batch_seconds":elapsed,"requests_per_second":concurrency/elapsed})
    report={"max_absolute_reference_error":error,"concurrent_requests_checked":16,
            "decode_cuda_graph_verified":True,"cache_hit_verified":cache_hit,"timings":timing}
    report["model"]=MODEL
    report["tp_size"]=int(os.environ.get("ACTIVATION_TEST_TP", "1"))
    report["reference_device"]=str(model.device)
    report["dtype"]=DTYPE
    (ROOT/"artifacts"/f"integration-{Path(MODEL).name}-tp{report['tp_size']}.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)


if __name__=="__main__":
    model=AutoModelForCausalLM.from_pretrained(MODEL,dtype=getattr(torch,DTYPE),attn_implementation="eager").eval()
    model=model.to(os.environ.get("ACTIVATION_REFERENCE_DEVICE","cpu"))
    engine=sglang.Engine(model_path=MODEL,dtype=DTYPE,mem_fraction_static=0.025,
        tp_size=int(os.environ.get("ACTIVATION_TEST_TP", "1")),
        max_total_tokens=4096,max_running_requests=16,context_length=512,
        chunked_prefill_size=16,cuda_graph_bs_decode=[1,2,4,8,16],
        disable_prefill_cuda_graph=os.environ.get("ACTIVATION_TEST_PREFILL_GRAPH") != "1",
        cuda_graph_bs_prefill=[16,32,64],attention_backend="triton",log_level="error")
    try:
        asyncio.run(run(engine,model))
    finally:
        engine.shutdown()
