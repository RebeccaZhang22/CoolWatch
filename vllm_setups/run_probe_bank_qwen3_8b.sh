#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
PROBE_SOURCE_ROOT="${PROBE_SOURCE_ROOT:-$PROJECT_ROOT/probe-runtime}"
PROBE_PYTHON="${PROBE_PYTHON:-$PROBE_SOURCE_ROOT/.venv-sglang/bin/python}"
PROBE_DIR="${PROBE_DIR:-$PROJECT_ROOT/probe/qwen3-8b}"
PROBE_MODEL_PATH="${PROBE_MODEL_PATH:-$PROJECT_ROOT/.runtime/models/Qwen3-8B}"
if [[ ! -x "$PROBE_PYTHON" ]]; then
  echo "Missing probe Python environment: $PROBE_PYTHON" >&2
  exit 1
fi
export PYTHONPATH="$PROJECT_ROOT:$PROBE_SOURCE_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ ! -f "$PROBE_SOURCE_ROOT/src/sglang_det/core.py" || ! -f "$PROBE_MODEL_PATH/config.json" ]]; then
  echo "Missing probe runtime source or model config; check PROBE_SOURCE_ROOT and PROBE_MODEL_PATH." >&2
  exit 1
fi
"$PROBE_PYTHON" -c 'from importlib.metadata import version; v = version("sglang"); assert v == "0.5.19", f"Expected sglang 0.5.19, found {v}"'
mkdir -p "$PROJECT_ROOT/.runtime/probe-bank-8b"
PROBE_RUN_DIR="$(mktemp -d "$PROJECT_ROOT/.runtime/probe-bank-8b/run-XXXXXXXX")"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
exec "$PROBE_PYTHON" -m backend.qwen3_probe_bank_server \
  --source-root "$PROBE_SOURCE_ROOT" --model qwen3-8b \
  --enabled-risks "${PROBE_BANK_ENABLED_RISKS:-ipi}" \
  --model-path "$PROBE_MODEL_PATH" \
  --spool "$PROBE_RUN_DIR/spool" --port "${PROBE_BANK_PORT:-8302}" \
  --content-safety-checkpoint "${CONTENT_SAFETY_PROBE:-$PROBE_DIR/content_safety/best_probe.pt}" \
  --ipi-checkpoint "${IPI_PROBE_CHECKPOINT:-$PROBE_DIR/indirect_prompt_injection/best_layer_22.pt}" \
  --ipi-threshold "${IPI_THRESHOLD:-0.91}" \
  --leakage-checkpoint "${LEAKAGE_PROBE_CHECKPOINT:-$PROBE_DIR/prompt_leakage/best_probe.pt}" \
  --max-batch "${PROBE_MAX_BATCH:-4}" --batch-tokens "${PROBE_BATCH_TOKENS:-16384}" \
  --max-inflight "${PROBE_MAX_INFLIGHT:-1024}" --batch-wait-ms "${PROBE_BATCH_WAIT_MS:-10}" \
  --request-timeout "${PROBE_REQUEST_TIMEOUT:-60}" \
  --max-total-tokens "${PROBE_MAX_TOTAL_TOKENS:-32768}" \
  --mem-fraction "${PROBE_MEM_FRACTION:-0.45}"
