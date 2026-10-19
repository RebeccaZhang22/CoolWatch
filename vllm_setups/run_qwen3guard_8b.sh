#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
GUARD_PYTHON="${GUARD_PYTHON:-$PROJECT_ROOT/probe-runtime/.venv-sglang/bin/python}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export TOKENIZERS_PARALLELISM=false
"$GUARD_PYTHON" -c 'from importlib.metadata import version; assert version("sglang") == "0.5.19"'
exec "$GUARD_PYTHON" -m sglang.launch_server \
  --model-path "${GUARD_MODEL_PATH:-$PROJECT_ROOT/.runtime/models/Qwen3Guard-Gen-8B}" \
  --served-model-name qwen3guard-8b \
  --host 127.0.0.1 --port "${GUARD_PORT:-8001}" \
  --tp-size 1 --dtype bfloat16 --context-length 16384 \
  --max-running-requests 8 --max-total-tokens 65536 \
  --mem-fraction-static "${GUARD_MEM_FRACTION:-0.60}" \
  --cuda-graph-backend-decode full --cuda-graph-max-bs-decode 8 \
  --cuda-graph-backend-prefill disabled "$@"
