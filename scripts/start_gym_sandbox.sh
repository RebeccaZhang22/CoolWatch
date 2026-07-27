#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
coolwatch_root="$(cd -- "${script_dir}/.." && pwd)"

if [[ -f "${coolwatch_root}/backend/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${coolwatch_root}/backend/.env"
  set +a
fi

nemo_gym_root="${NEMO_GYM_ROOT:-$(cd -- "${coolwatch_root}/.." && pwd)/nemo-gym}"
gym_bin="${nemo_gym_root}/.venv/bin/gym"

if [[ ! -x "${gym_bin}" ]]; then
  echo "NeMo Gym virtual environment was not found at ${gym_bin}." >&2
  echo "Run: cd ${nemo_gym_root} && UV_PYTHON=python3.12 uv sync --extra dev --extra sandbox" >&2
  exit 1
fi

model_name="${VLLM_MODEL:-qwen3.5-27b}"
model_url="${VLLM_BASE_URL:-http://127.0.0.1:8767/v1}"
model_api_key="${VLLM_API_KEY:-EMPTY}"
config_path="resources_servers/coolwatch_prompt_injection/configs/coolwatch_prompt_injection.yaml"

cd "${nemo_gym_root}"
docker build \
  --file resources_servers/coolwatch_prompt_injection/Dockerfile \
  --tag coolwatch-gym-sandbox:latest \
  .
exec "${gym_bin}" env start \
  --config "${config_path}" \
  --model-type vllm_model \
  --model "${model_name}" \
  --model-url "${model_url}" \
  --model-api-key "${model_api_key}"
