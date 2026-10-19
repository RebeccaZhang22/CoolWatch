#!/usr/bin/env bash
set -euo pipefail
activation_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$activation_root/.."
export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2
export TOKENIZERS_PARALLELISM=false
exec "$activation_root/python" -m backend.activation_probe_server \
  --enabled-risks "${PROBE_BANK_ENABLED_RISKS:-ipi}" \
  --model-path "${MODEL_PATH:-$PWD/.runtime/models/Qwen3-8B}" \
  --probe-dir "${PROBE_DIR:-$PWD/probe/qwen3-8b}" \
  --upstream "${ACTIVATION_MODEL_URL:-http://127.0.0.1:8303}" \
  --port "${PROBE_PORT:-8302}" "$@"
