#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
echo "[deprecated] 请改用 ${SCRIPT_DIR}/run_chat_vllm_qwen3_8b.sh" >&2
exec "${SCRIPT_DIR}/run_chat_vllm_qwen3_8b.sh" "$@"
