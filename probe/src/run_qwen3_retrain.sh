#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
RUN_ROOT="${RUN_ROOT:-$PWD/.runtime/qwen3-8b-retrain-20260915}"
MODEL_PATH="${MODEL_PATH:-$PWD/.runtime/models/Qwen3-8B}"
PYTHON="${PYTHON:-/home/yutongz/miniconda3/envs/agent/bin/python}"
TRAIN_PYTHON="${TRAIN_PYTHON:-/ssd/workspace/djs/zhuanli/.venv-sglang/bin/python}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-7}" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
"$TRAIN_PYTHON" probe/src/prepare_qwen3_data.py --run-root "$RUN_ROOT"
"$PYTHON" probe/src/extract_qwen3_activations.py --model-path "$MODEL_PATH" --dataset "$RUN_ROOT/leakage_data" --output "$RUN_ROOT/leakage_features" --batch-size 16 --batch-tokens 8192
if [[ ! -f "$RUN_ROOT/leakage_probe/report.json" ]]; then
  "$TRAIN_PYTHON" probe/src/train_qwen3_probe.py --task prompt_leakage --features "$RUN_ROOT/leakage_features" --dataset "$RUN_ROOT/leakage_data" --output "$RUN_ROOT/leakage_probe"
fi
"$PYTHON" probe/src/prepare_harmful_contexts.py "$RUN_ROOT"
"$PYTHON" probe/src/extract_qwen3_activations.py --model-path "$MODEL_PATH" --dataset "$RUN_ROOT/harmful_context_data" --output "$RUN_ROOT/harmful_context_features" --batch-size 16 --batch-tokens 8192
"$TRAIN_PYTHON" probe/src/merge_harmful_features.py "$RUN_ROOT"
if [[ ! -f "$RUN_ROOT/harmful_v2_probe/report.json" ]]; then
  "$TRAIN_PYTHON" probe/src/train_qwen3_probe.py --task harmful --features "$RUN_ROOT/harmful_v2_features" --dataset "$RUN_ROOT/harmful_v2_data" --output "$RUN_ROOT/harmful_v2_probe"
fi
