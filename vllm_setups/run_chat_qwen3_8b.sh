#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

CHAT_PYTHON="${CHAT_PYTHON:-$PROJECT_ROOT/probe-runtime/.venv-sglang/bin/python}"
MODEL_PATH="${MODEL_PATH:-$PROJECT_ROOT/.runtime/models/Qwen3-8B}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export TOKENIZERS_PARALLELISM=false

"$CHAT_PYTHON" -c 'from importlib.metadata import version; assert version("sglang") == "0.5.19"'
exec "$CHAT_PYTHON" -m sglang.launch_server \
  --model-path "$MODEL_PATH" --served-model-name qwen3-8b \
  --host "${CHAT_HOST:-127.0.0.1}" --port "${CHAT_PORT:-8104}" \
  --tp-size 1 --dtype bfloat16 \
  --context-length "${CHAT_CONTEXT_LENGTH:-16384}" \
  --max-running-requests "${CHAT_MAX_RUNNING_REQUESTS:-8}" \
  --max-total-tokens "${CHAT_MAX_TOTAL_TOKENS:-131072}" \
  --mem-fraction-static "${CHAT_MEM_FRACTION:-0.80}" \
  --cuda-graph-backend-decode full --cuda-graph-max-bs-decode 8 \
  --cuda-graph-backend-prefill disabled \
  --tool-call-parser qwen --reasoning-parser qwen3 "$@"
