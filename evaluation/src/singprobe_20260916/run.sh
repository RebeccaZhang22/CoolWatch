#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
RUN_ROOT="$PWD/evaluation/results/singprobe_20260916"
TRAIN_PYTHON=/ssd/workspace/djs/zhuanli/.venv-sglang/bin/python
EXTRACT_PYTHON=/home/yutongz/miniconda3/envs/agent/bin/python
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-7}"
mkdir -p "$RUN_ROOT"
# Prepare the exact upstream revision; no changes are made to serving processes.
if [[ ! -d /tmp/agent-guard-SingProbe-20260916 ]]; then
 git clone https://github.com/inclusionAI/SingProbe.git /tmp/agent-guard-SingProbe-20260916
 git -C /tmp/agent-guard-SingProbe-20260916 checkout 10edcb813482db08734e755f354390bf4d68a6b8
fi
test "$(git -C /tmp/agent-guard-SingProbe-20260916 rev-parse HEAD)" = 10edcb813482db08734e755f354390bf4d68a6b8
"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/run_mlp.py > "$RUN_ROOT/mlp.log" 2>&1
"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/run_ipi.py > "$RUN_ROOT/ipi.log" 2>&1
"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/audit_ipi_overlap.py > "$RUN_ROOT/ipi_overlap.log" 2>&1
"$EXTRACT_PYTHON" evaluation/src/singprobe_20260916/extract_sequences.py > "$RUN_ROOT/extraction.log" 2>&1
"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/score_audits.py > "$RUN_ROOT/benchmarks.log" 2>&1
"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/train_attention.py > "$RUN_ROOT/attention_training.log" 2>&1
"$EXTRACT_PYTHON" evaluation/src/singprobe_20260916/extract_sequences.py --attention-audit > "$RUN_ROOT/attention_audit.log" 2>&1

"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/score_attention.py > "$RUN_ROOT/attention_scores.log" 2>&1
"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/measure_latency.py > "$RUN_ROOT/latency.log" 2>&1
"$TRAIN_PYTHON" evaluation/src/singprobe_20260916/build_report.py
