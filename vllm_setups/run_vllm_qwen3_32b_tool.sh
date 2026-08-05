#!/usr/bin/env bash
set -euo pipefail

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"

MODEL="${MODEL:-Qwen/Qwen3-32B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen3-32b}"
PORT="${PORT:-8978}"
TP_SIZE="${TP_SIZE:-4}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.5}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name "$SERVED_MODEL_NAME" \
    --dtype auto \
    --host 0.0.0.0 \
    --tensor-parallel-size "$TP_SIZE" \
    --trust-remote-code \
    --enforce_eager \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --reasoning-parser qwen3 \
    --port "$PORT" \
    --max-num-batched-tokens 65536 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --max-logprobs 100 \
    "$@"
