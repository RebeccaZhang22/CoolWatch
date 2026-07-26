# Qwen3-8B held-out strict no-intervene evaluation

This evaluation separates trace collection from guard detection.

1. AgentDojo runs the Qwen3-8B agent without a guard, steering, blocking, or
   inline-probing request.
2. `cases.jsonl` freezes 100 positive `risk_faced` decision points sampled with
   seed 42 from all 16 held-out strict settings.
3. Detection happens by post-hoc replay after collection. Qwen3Guard and
   NetEase YiDun receive only the newly faced injected text. The probe replays
   the exact frozen messages, tools, and tool choice through patched Qwen3-8B
   to capture layer 4. No detector output is returned to the agent.
4. Later assistant decisions after the same injection round are excluded.

The primary replay evaluation uses the patched vLLM endpoint:

```bash
python scripts/evaluate_injected_round_guards.py run \
  --guard inline_probing \
  --output-dir results/guard_detection/qwen3-8b-held-out-strict-injected-round-100-seed42-no-intervene-replay \
  --probe-base-url http://127.0.0.1:8013/v1 \
  --probe-model qwen3-8b \
  --probe-checkpoint-id sha256:41f1433346caebc8b2e9ff5640b44e3d162050d6ef7ffee45285badba4798b45 \
  --probe-threshold 0.5
```

Previously materialized feature shards may be used only as a cached replay
cross-check:

```bash
python scripts/evaluate_injected_round_guards.py run \
  --guard inline_probing \
  --output-dir results/guard_detection/qwen3-8b-held-out-strict-injected-round-100-seed42-no-intervene-offline \
  --probe-feature-root ../../results/probe_traces/v2/agentdojo-20260430T015534Z-qwen3-8b-dp4/features \
  --probe-checkpoint recipe/inline_probing/qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/probe.pt \
  --probe-threshold 0.5
```

The frozen inputs remain unchanged. The audited replay results and source
hashes are recorded in the result directory's `run_manifest.json`.
