#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COOLWATCH_DIR="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BASE_URL="${1:-http://127.0.0.1:8013/v1}"
MODEL="${2:-qwen3-8b}"
OUTPUT="${3:-$COOLWATCH_DIR/results/qwen3-8b-inline-probing-golden.jsonl}"

cd "$COOLWATCH_DIR"
exec "$PYTHON_BIN" -m backend.watchers.inline_probing.golden_recipe \
  --base-url "$BASE_URL" \
  --model "$MODEL" \
  --concurrency 4 \
  --output "$OUTPUT"
