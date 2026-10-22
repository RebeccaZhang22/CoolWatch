"""跨后端数值对比：把同一批输入分别送本地 probe 与实际服务，定位 logit 差异。

handoff §验收3 要求不能假定 bitwise parity。这个脚本给出可复现的差异报告，
不做任何阈值调整。

用法：
  # 只看本地（不连服务），确认给定输入在本机的 logit
  python compare_backend.py --cases audit --local-only

  # 本地 vs 线上 8302（只读，不影响服务）
  python compare_backend.py --cases audit --service http://127.0.0.1:8302

  # 指定自己的 JSONL：每行 {"id": ..., "messages": [...], "tools": [...]}
  python compare_backend.py --jsonl my.jsonl --service http://127.0.0.1:8302
"""
import argparse
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
import torch
from transformers import AutoTokenizer

from shadow_server.composer import ComposerConfig, compose_prompt
from shadow_server.probe import Probe

AUDIT = "/mnt/kpfs_qyang/djs/ipi-doom/analysis/coolwatch-simplified-audit-20261022"
MODELS = ("/mnt/kpfs_qyang/djs/ipi-doom/results/ladder-merged-blend-growth1-20261022"
          "/cells/A5_n2097152/models")
PREFIX = "Are there risks of indirect prompt injection?"


def load_cases(kind, jsonl):
    if jsonl:
        return [(row["id"], row["messages"], row.get("tools") or [])
                for row in (json.loads(line) for line in Path(jsonl).open() if line.strip())]
    cases = json.loads((Path(AUDIT) / "cases.json").read_text())
    return [(name, request["messages"], request.get("tools") or [])
            for name, request in cases.items()]


def local_logits(tokenizer, probe, cases, config):
    rows = []
    for name, messages, tools in cases:
        composed = compose_prompt(tokenizer, messages, tools, config)
        # 本地无法产出 engine 特征，只报告 token 数；数值对比需要 features.pt
        rows.append((name, len(composed.token_ids)))
    return rows


def score_from_cached(probe, audit):
    """用 audit 里冻结的缓存特征复算，给出本机基准 logit。"""
    cases = list(json.loads((Path(audit) / "cases.json").read_text()))
    features = torch.load(Path(audit) / "features.pt", map_location="cpu", weights_only=True)
    results = json.loads((Path(audit) / "results.json").read_text())["results"]
    table = []
    for index, name in enumerate(cases):
        if not name.startswith("oracle"):
            continue
        scored = probe.score(features[index].reshape(1, 3, 1, 4096))
        table.append({"id": name, "local_logit": scored["logit"],
                      "cached_logit": results[name]["seeds"]["42"]["logit"],
                      "flagged": scored["flagged"]})
    return table


def query_service(service, cases, api_key):
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    rows = []
    with httpx.Client(base_url=service, headers=headers, timeout=180) as client:
        info = client.get("/info")
        info.raise_for_status()
        contract = info.json()
        print("服务 /info:", json.dumps({k: contract.get(k) for k in
                                        ("setting", "detector_seed", "threshold_logit",
                                         "input_dim", "selected_positions", "capture_layers")},
                                       ensure_ascii=False))
        for name, messages, tools in cases:
            body = {"messages": messages}
            if tools:
                body["tools"] = tools
            response = client.post("/detect", json=body)
            if response.status_code != 200:
                rows.append({"id": name, "error": response.status_code, "detail": response.text[:200]})
                continue
            result = response.json()
            rows.append({"id": name, "service_logit": result["logit"],
                         "score": result["score"], "flagged": result["flagged"],
                         "input_tokens": result["input_tokens"],
                         "threshold_logit": result["threshold_logit"]})
    return contract, rows


def compare(local, remote):
    by_id = {row["id"]: row for row in remote}
    print(f"\n{'id':28s} {'local':>12s} {'service':>12s} {'Δ':>10s} {'期望一致':>8s}")
    deltas = []
    for row in local:
        other = by_id.get(row["id"], {})
        if "service_logit" not in other:
            print(f"{row['id']:28s} {row['local_logit']:+12.6f} {'—':>12s} "
                  f"{'—':>10s} {'服务未返回':>8s}")
            continue
        delta = other["service_logit"] - row["local_logit"]
        deltas.append(abs(delta))
        print(f"{row['id']:28s} {row['local_logit']:+12.6f} {other['service_logit']:+12.6f} "
              f"{delta:+10.4f} {'—':>8s}")
    if deltas:
        print(f"\n|Δ| 中位数 {statistics.median(deltas):.4f}  最大 {max(deltas):.4f}")
        print("handoff 提示跨后端同输入 logit 差可约 1；阈值不应据此重调，"
              "而应在固定 validation 上复核运行时指标。")
    return deltas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", default="/mnt/kpfs_qyang/yutongz/models/Qwen3-8B-FP8")
    parser.add_argument("--audit", default=AUDIT)
    parser.add_argument("--models", default=MODELS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--service", default="", help="如 http://127.0.0.1:8302")
    parser.add_argument("--api-key", default=os.environ.get("INSCOPE_API_KEY") or os.environ.get("SHADOW_API_KEY", ""))
    parser.add_argument("--jsonl", default="", help="自定义用例；默认用 audit 的 oracle")
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    probe = Probe(args.models, seed=args.seed)

    if args.jsonl or args.service:
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)
        config = ComposerConfig(probe_prefix=PREFIX)
        cases = load_cases("audit", args.jsonl)
        for name, count in local_logits(tokenizer, probe, cases, config):
            print(f"  {name}: {count} tokens")

    if args.local_only:
        print("\n本机基准（冻结缓存特征）:")
        for row in score_from_cached(probe, args.audit):
            print(f"  {row['id']}: {row['local_logit']:+.6f} "
                  f"(缓存 {row['cached_logit']:+.6f}) flagged={row['flagged']}")
        return 0

    if not args.service:
        parser.error("需要 --service 或 --local-only")

    cases = load_cases("audit", args.jsonl)
    _, remote = query_service(args.service, cases, args.api_key)
    local = score_from_cached(probe, args.audit)
    compare(local, remote)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
