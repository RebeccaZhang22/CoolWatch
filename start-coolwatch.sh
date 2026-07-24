#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18088}"

echo "CoolWatch：http://127.0.0.1:$PORT"
exec python -m uvicorn backend.app:app --host "$HOST" --port "$PORT" "$@"
