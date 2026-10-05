"""Replay a captured probe request with controlled context ablations.

Example (from the repository root):
python -m evaluation.src.diagnose_rag_leakage \
  --checkpoints evaluation/results/rag-miss-20260918/current/checkpoints.json \
  --output evaluation/results/rag-miss-20260918/ablations.json

Calls the detector only; does not change weights, thresholds or business state.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "probe/src")]
from urllib.request import Request, urlopen


def variants(original):
    yield "original", copy.deepcopy(original)
    without_tools = copy.deepcopy(original)
    without_tools["tools"] = None
    yield "without_tools", without_tools
    for name, base in (("generic_system_with_tools", original),
                       ("generic_system_without_tools", without_tools)):
        payload = copy.deepcopy(base)
        for message in payload["messages"]:
            if message["role"] == "system":
                message["content"] = "你是一个助手。"
        yield name, payload
    # Match the benign question to the same business context, with/without tools.
    # This input-stage control is not a clean post-tool counterfactual: a prior
    # assistant/tool trajectory might itself already depend on attack wording.
    if [m["role"] for m in original["messages"]] == ["system", "user"]:
        for name, base in (("question_only_with_tools", original),
                           ("question_only_without_tools", without_tools)):
            payload = copy.deepcopy(base)
            payload["messages"][-1]["content"] = payload["messages"][-1]["content"].split("\n\n", 1)[0]
            yield name, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--base-url", default="http://127.0.0.1:8302")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original = json.loads(args.checkpoints.read_text())[args.index]["request"]
    base_url = args.base_url.rstrip("/")
    with urlopen(base_url + "/bank", timeout=65) as response:
        bank = json.load(response)
    result = {"source": str(args.checkpoints), "index": args.index,
              "bank": bank, "variants": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for name, payload in variants(original):
        request = Request(base_url + "/detect", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=65) as response:
            scored = json.load(response)
        if scored["bank_version"] != bank["bank_version"]:
            raise RuntimeError("Probe bank changed during the experiment")
        result["variants"].append({"name": name, "request": payload, "response": scored})
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"name": name, "input_tokens": scored["input_tokens"],
                          "per_risk": scored["per_risk"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
