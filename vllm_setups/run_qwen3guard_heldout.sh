#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-7}"
export OMP_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="$PROJECT_ROOT/.runtime/qwen3guard-heldout/python${PYTHONPATH:+:$PYTHONPATH}"
exec "$PROJECT_ROOT/sglang-activation-runtime/.venv/bin/python" -m sglang.launch_server \
  --model-path "$PROJECT_ROOT/.runtime/models/Qwen3Guard-Gen-8B" \
  --served-model-name qwen3guard-8b \
  --host 127.0.0.1 --port "${GUARD_PORT:-8411}" \
  --tp-size 1 --dtype bfloat16 --context-length 32768 \
  --max-running-requests 8 --max-queued-requests 32 \
  --max-total-tokens 65536 --mem-fraction-static 0.88 \
  --chunked-prefill-size 2048 --max-prefill-tokens 4096 \
  --attention-backend triton \
  --cuda-graph-backend-decode disabled --cuda-graph-backend-prefill disabled \
  "$@"
