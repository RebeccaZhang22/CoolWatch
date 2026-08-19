#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONTROL="$PROJECT_ROOT/recipe/inline_probing/qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/vllm_server_control_with_probe_enabled.sh"
INLINE_RECIPE="$PROJECT_ROOT/recipe/inline_probing/qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/recipe.json"
ACTIVATION_RECIPE="$PROJECT_ROOT/recipe/activation_probing/qwen3-8b-theft-unified-v16-multilayer-mlp/recipe.json"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 {start|status|stop} [vLLM control options]" >&2
  exit 2
fi

ACTION="$1"
shift

DEFAULT_MODEL="Qwen/Qwen3-8B"
if [[ -f "$PROJECT_ROOT/.runtime/models/Qwen3-8B/config.json" ]]; then
  DEFAULT_MODEL="$PROJECT_ROOT/.runtime/models/Qwen3-8B"
fi

exec "$CONTROL" "$ACTION" \
  --model "${MODEL:-$DEFAULT_MODEL}" \
  --served-model-name "${SERVED_MODEL_NAME:-qwen3-8b}" \
  --gpu "${CUDA_VISIBLE_DEVICES:-4}" \
  --port "${PORT:-8013}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.72}" \
  --max-model-len "${MAX_MODEL_LEN:-16384}" \
  --max-num-seqs "${MAX_NUM_SEQS:-8}" \
  --max-num-batched-tokens "${MAX_NUM_BATCHED_TOKENS:-8192}" \
  --probe-recipe "$INLINE_RECIPE" \
  --probe-recipe "$ACTIVATION_RECIPE" \
  "$@"
