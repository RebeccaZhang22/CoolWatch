#!/usr/bin/env bash
set -euo pipefail
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

MODEL_PATH="${MODEL_PATH:-Qwen/Qwen3Guard-Gen-8B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen3guard-8b}"
PORT="${PORT:-8001}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.6}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_PATH}" \
    --served-model-name "${SERVED_MODEL_NAME}" \
    --dtype auto \
    --host 0.0.0.0 \
    --tensor-parallel-size 1 \
    --trust-remote-code \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --port "${PORT}" \
    --max-num-batched-tokens 65536 \
    "$@"
