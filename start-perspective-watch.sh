#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18088}"

echo "Perspective Watch：http://127.0.0.1:$PORT"
exec python -m uvicorn backend.app:app --host "$HOST" --port "$PORT" "$@"
