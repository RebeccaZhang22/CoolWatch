#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
RUN_ROOT="${RUN_ROOT:-$PWD/.runtime/leakage-toolctx-reproduction}"
BASE_RUN="${BASE_RUN:-$PWD/.runtime/qwen3-8b-retrain-20260915}"
MODEL_PATH="${MODEL_PATH:-$PWD/.runtime/models/Qwen3-8B}"
FEATURE_PYTHON="${FEATURE_PYTHON:-/home/yutongz/miniconda3/envs/agent/bin/python}"
TRAIN_PYTHON="${TRAIN_PYTHON:-/ssd/workspace/djs/zhuanli/.venv-sglang/bin/python}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-7}" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
if [[ -e "$RUN_ROOT" ]]; then
  echo 'RUN_ROOT must be a fresh directory' >&2
  exit 1
fi
"$FEATURE_PYTHON" probe/src/prepare_tool_context_leakage.py --base-data "$BASE_RUN/leakage_data" --output "$RUN_ROOT/additions_data" --diagnostics evaluation/results/rag-miss-20260918
"$FEATURE_PYTHON" probe/src/extract_qwen3_activations.py --model-path "$MODEL_PATH" --dataset "$RUN_ROOT/additions_data" --output "$RUN_ROOT/additions_features" --batch-size 8 --batch-tokens 4096
"$FEATURE_PYTHON" probe/src/merge_tool_context_features.py --base "$BASE_RUN" --run "$RUN_ROOT"
"$TRAIN_PYTHON" probe/src/train_qwen3_probe.py --task prompt_leakage --features "$RUN_ROOT/combined_features" --dataset "$RUN_ROOT/combined_data" --output "$RUN_ROOT/probe" --validation-group-field stage
"$TRAIN_PYTHON" evaluation/src/evaluate_tool_context_probe.py --run "$RUN_ROOT" --old-checkpoint probe/qwen3-8b/prompt_leakage/best_probe.pt
"$TRAIN_PYTHON" evaluation/src/validate_tool_context_candidate.py --run "$RUN_ROOT"
