#!/usr/bin/env bash
set -euo pipefail
manager_project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$manager_project_root"
manager_python="${MANAGER_PYTHON:-$manager_project_root/.venv/bin/python}"
if [[ ! -x "$manager_python" ]]; then
  manager_python="$(command -v python3)"
fi
exec "$manager_python" -m uvicorn manager.app:create_app --factory \
  --host "${MANAGER_HOST:-0.0.0.0}" --port "${MANAGER_PORT:-18089}" "$@"
