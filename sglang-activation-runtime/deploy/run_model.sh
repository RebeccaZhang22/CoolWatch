#!/usr/bin/env bash
set -euo pipefail
activation_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$activation_root/.."
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-7}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
role="${1:?Expected chat or shadow}"
shift
case "$role" in
  shadow)
    export SGLANG_ACTIVATION_CAPTURE=1
    port=8303; running=64
    # Probe thresholds must not change with the number of concurrent requests.
    precision_args=(--enable-deterministic-inference)
    ;;
  chat) export SGLANG_ACTIVATION_CAPTURE=0; port=8104; running=32; precision_args=() ;;
  *) echo "Expected chat or shadow" >&2; exit 2 ;;
esac
exec "$activation_root/python" -m sglang.launch_server \
  --model-path "${MODEL_PATH:-$PWD/.runtime/models/Qwen3-8B}" \
  --served-model-name qwen3-8b --host 127.0.0.1 --port "${MODEL_PORT:-$port}" \
  --tp-size 1 --dtype bfloat16 --context-length 16384 \
  --max-running-requests "$running" --max-queued-requests 128 \
  --max-total-tokens "${MAX_TOTAL_TOKENS:-131072}" \
  --mem-fraction-static "${MEM_FRACTION_STATIC:-0.45}" \
  --chunked-prefill-size 4096 --max-prefill-tokens 16384 \
  --attention-backend triton --cuda-graph-max-bs-decode 32 \
  --cuda-graph-backend-prefill disabled \
  --tool-call-parser qwen --reasoning-parser qwen3 "${precision_args[@]}" "$@"
