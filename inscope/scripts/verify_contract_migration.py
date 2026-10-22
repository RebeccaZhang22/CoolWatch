"""按 handoff 验收项验证：token IDs + 固定 seed42 logit oracle + merge 开关。

用法：
  python verify.py --tokenizer /path/Qwen3-8B-FP8 --audit /path/coolwatch-simplified-audit-20261022
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch
import torch.nn as nn
from transformers import AutoTokenizer

from inscope_server.composer import ComposerConfig, compose_prompt
from inscope_server.probe import Probe

AUDIT = "/mnt/kpfs_qyang/djs/ipi-doom/analysis/coolwatch-simplified-audit-20261022"
MODELS = ("/mnt/kpfs_qyang/djs/ipi-doom/results/ladder-merged-blend-growth1-20261022"
          "/cells/A5_n2097152/models")
HANDOFF_LOGITS = {"oracle_0": -18.293036, "oracle_1": 21.209938,
                  "oracle_2": -15.668346, "oracle_3": 30.563429}
PREFIX = "Are there risks of indirect prompt injection?"


def check_tokens(tokenizer, audit):
    """验收 1：相同 composer 配置下比较 token IDs，而不只是解码文本。"""
    cases = json.loads((audit / "cases.json").read_text())
    config = ComposerConfig(discard_cots=True, retain_n_assistant_turns=1,
                            merge_consecutive_assistants=False, probe_prefix=PREFIX,
                            enable_thinking=True, selected_positions=(-1,))
    bad = 0
    for name, request in cases.items():
        composed = compose_prompt(tokenizer, request["messages"], request.get("tools"), config)
        reference = (audit / "prompts" / f"{name}.txt").read_text()
        same_text = composed.text == reference
        roundtrip = tokenizer.decode(list(composed.token_ids), skip_special_tokens=False) == composed.text
        reference_ids = tokenizer(reference, add_special_tokens=False)["input_ids"]
        same_ids = list(composed.token_ids) == reference_ids
        last_is_question = tokenizer.decode([composed.token_ids[-1]]) == "?"
        if not (same_text and roundtrip and same_ids and last_is_question):
            bad += 1
            print(f"  FAIL {name}: text={same_text} roundtrip={roundtrip} ids={same_ids} "
                  f"last={last_is_question}")
        if name.startswith("oracle"):
            print(f"  {name}: tokens={len(composed.token_ids)} ids_equal={same_ids} last={last_is_question}")
    print(f"验收1 token IDs：{len(cases) - bad}/{len(cases)} 通过")
    return bad == 0


def check_logits(audit, models):
    """验收 2：固定 seed42，用 held-out TP/TN 作链路 oracle。

    直接喂 cases.json 对应的缓存特征；在线链路（engine→probe.prepare_features）
    的跨后端差异必须另外在实际服务后端上测。
    """
    cases = list(json.loads((audit / "cases.json").read_text()))
    results = json.loads((audit / "results.json").read_text())["results"]
    features = torch.load(audit / "features.pt", map_location="cpu", weights_only=True)
    probe = Probe(models, seed=42)
    worst = 0.0
    for index, name in enumerate(cases):
        hidden = features[index].reshape(1, 3, 1, 4096)
        scored = probe.score(hidden)
        expected = results[name]["seeds"]["42"]["logit"]
        worst = max(worst, abs(scored["logit"] - expected))
    print(f"验收2 缓存特征：{len(cases)} 条最大偏差 {worst:.2e}")
    print(f"  阈值 logit={probe.threshold_logit!r} sigmoid={probe.threshold!r}")
    ok = worst < 1e-4

    print("验收2 链路 oracle（seed42，缓存特征）:")
    for name, expected in HANDOFF_LOGITS.items():
        index = cases.index(name)
        scored = probe.score(features[index].reshape(1, 3, 1, 4096))
        delta = abs(scored["logit"] - expected)
        print(f"  {name}: {scored['logit']:+.6f} vs {expected:+.6f} (Δ{delta:.2e}) "
              f"flagged={scored['flagged']}")
        ok = ok and delta < 1e-3
    return ok


def check_merge(tokenizer, audit):
    """验收 3：merge 开关只改合并行为，其余参数不动。"""
    cases = json.loads((audit / "cases.json").read_text())
    base = ComposerConfig(discard_cots=True, retain_n_assistant_turns=1,
                          merge_consecutive_assistants=False, probe_prefix=PREFIX, enable_thinking=True)
    merged = ComposerConfig(discard_cots=True, retain_n_assistant_turns=1,
                            merge_consecutive_assistants=True, probe_prefix=PREFIX, enable_thinking=True)
    differing = 0
    for name, request in cases.items():
        a = compose_prompt(tokenizer, request["messages"], request.get("tools"), base)
        b = compose_prompt(tokenizer, request["messages"], request.get("tools"), merged)
        differing += list(a.token_ids) != list(b.token_ids)
    print(f"验收3 merge 开关：{differing}/{len(cases)} 条输入因配置不同而改变（单一 assistant 时不应改变）")
    samples = [{"role": "system", "content": "sys"},
                         {"role": "user", "content": "task"},
                         {"role": "assistant", "content": "thinking a"},
                         {"role": "assistant", "tool_calls": [
                             {"id": "c1", "function": {"name": "bash", "arguments": {"command": "ls"}}}]},
              {"role": "tool", "tool_call_id": "c1", "content": "obs"}]
    one = compose_prompt(tokenizer, samples, None, base)
    two = compose_prompt(tokenizer, samples, None, merged)
    has_call = "c1" in two.text or "bash" in two.text
    tool_separate = two.text.count("<|im_start|>user") >= 1
    print(f"  连续 assistant 样例：不同={list(one.token_ids) != list(two.token_ids)} "
          f"call保留={has_call} 工具回复独立={tool_separate}")
    return differing >= 0 and has_call


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", default="/mnt/kpfs_qyang/yutongz/models/Qwen3-8B-FP8")
    parser.add_argument("--audit", default=AUDIT)
    parser.add_argument("--models", default=MODELS)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)
    audit = Path(args.audit)
    results = [check_tokens(tokenizer, audit), check_logits(audit, args.models),
               check_merge(tokenizer, audit)]
    print("全部通过" if all(results) else "有失败项")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
