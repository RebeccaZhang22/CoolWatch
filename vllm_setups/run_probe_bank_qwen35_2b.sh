#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
PROBE_SOURCE_ROOT="${PROBE_SOURCE_ROOT:-/ssd/workspace/djs/zhuanli}"
PROBE_PYTHON="${PROBE_PYTHON:-$PROBE_SOURCE_ROOT/.venv-sglang/bin/python}"
PROBE_DIR="${PROBE_DIR:-$PROJECT_ROOT/probe}"
mkdir -p "$PROJECT_ROOT/.runtime/probe-bank-2b"
PROBE_RUN_DIR="$(mktemp -d "$PROJECT_ROOT/.runtime/probe-bank-2b/run-XXXXXXXX")"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
exec "$PROBE_PYTHON" -m backend.probe_bank_server \
  --source-root "$PROBE_SOURCE_ROOT" --model qwen35-2b \
  --spool "$PROBE_RUN_DIR/spool" --port "${PROBE_BANK_PORT:-8302}" \
  --content-safety-checkpoint "${CONTENT_SAFETY_PROBE:-$PROBE_DIR/content_safety/best_probe.pt}" \
  --ipi-checkpoint "${IPI_PROBE_CHECKPOINT:-$PROBE_DIR/indirect_prompt_injection/best_layer_07.pt}" \
  --leakage-checkpoint "${LEAKAGE_PROBE_CHECKPOINT:-$PROBE_DIR/prompt_leakage/best_probe.pt}" \
  --max-batch "${PROBE_MAX_BATCH:-64}" --batch-tokens "${PROBE_BATCH_TOKENS:-65536}" \
  --max-inflight "${PROBE_MAX_INFLIGHT:-1024}" --batch-wait-ms "${PROBE_BATCH_WAIT_MS:-10}" \
  --request-timeout "${PROBE_REQUEST_TIMEOUT:-60}" \
  --mem-fraction "${PROBE_MEM_FRACTION:-0.2}"
