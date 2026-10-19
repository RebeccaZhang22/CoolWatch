#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BASE_PYTHON="${PROBE_BASE_PYTHON:-python3}"
ENV_DIR="$PROJECT_ROOT/probe-runtime/.venv-sglang"

# Reuse the server's CUDA/PyTorch installation, while keeping additions local.
"$BASE_PYTHON" -m venv --system-site-packages "$ENV_DIR"
"$ENV_DIR/bin/python" -m pip install \
  -r "$PROJECT_ROOT/probe-runtime/requirements-local.txt"
PYTHONPATH="$PROJECT_ROOT/probe-runtime/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$ENV_DIR/bin/python" -c 'from importlib.metadata import version; from sglang.srt.entrypoints.engine import Engine; from sglang_det.core import DetectorCore; assert version("sglang") == "0.5.19"; print("SGLang 0.5.19 probe imports OK")'
