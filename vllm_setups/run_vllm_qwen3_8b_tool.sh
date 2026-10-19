#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
echo "[deprecated] 请改用 ${SCRIPT_DIR}/run_chat_qwen3_8b.sh (SGLang 0.5.19)" >&2
exec bash "${SCRIPT_DIR}/run_chat_qwen3_8b.sh" "$@"
