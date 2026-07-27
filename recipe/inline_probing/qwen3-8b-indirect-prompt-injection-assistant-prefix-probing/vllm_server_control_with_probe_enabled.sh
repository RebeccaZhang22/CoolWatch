#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COOLWATCH_DIR="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
RECIPE_JSON="$SCRIPT_DIR/recipe.json"
DEFAULT_VENV="$COOLWATCH_DIR/.runtime/vllm-0.25.1-inline-probing"
DEFAULT_STATE_DIR="$COOLWATCH_DIR/.runtime/qwen3-8b-inline-probing-server"
PREFERRED_LIBSTDCXX="/mnt/workspace/zqj/conda_envs/cogpath_clean/lib/libstdc++.so.6"

die() { echo "vllm-server-control: $*" >&2; exit 1; }
usage() { echo "usage: $0 {start|status|stop} [options]" >&2; exit 2; }
is_running() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }

[[ $# -ge 1 ]] || usage
ACTION="$1"
shift
[[ "$ACTION" =~ ^(start|status|stop)$ ]] || usage

VENV="$DEFAULT_VENV"
STATE_DIR="$DEFAULT_STATE_DIR"
MODEL="Qwen/Qwen3-8B"
SERVED_MODEL_NAME="qwen3-8b"
GPU="0"
HOST="127.0.0.1"
PORT="8013"
GPU_MEMORY_UTILIZATION="0.9"
MAX_MODEL_LEN="32768"
MAX_NUM_SEQS="8"
MAX_NUM_BATCHED_TOKENS="8192"
CUDA_COMPAT_LIB_DIR=""
STOP_TIMEOUT="30"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv) VENV="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --served-model-name) SERVED_MODEL_NAME="$2"; shift 2 ;;
    --gpu) GPU="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --gpu-memory-utilization) GPU_MEMORY_UTILIZATION="$2"; shift 2 ;;
    --max-model-len) MAX_MODEL_LEN="$2"; shift 2 ;;
    --max-num-seqs) MAX_NUM_SEQS="$2"; shift 2 ;;
    --max-num-batched-tokens) MAX_NUM_BATCHED_TOKENS="$2"; shift 2 ;;
    --cuda-compat-lib-dir) CUDA_COMPAT_LIB_DIR="$2"; shift 2 ;;
    --timeout) STOP_TIMEOUT="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

VENV="$(realpath -m "$VENV")"
STATE_DIR="$(realpath -m "$STATE_DIR")"
PID_FILE="$STATE_DIR/run.pid"
PGID_FILE="$STATE_DIR/run.pgid"
RUN_JSON="$STATE_DIR/run.json"
PID=""
[[ -f "$PID_FILE" ]] && PID="$(<"$PID_FILE")"

status_json() {
  local state="stopped" pgid="" gpu="" base_url="" log_path=""
  is_running "$PID" && state="running"
  [[ -f "$PGID_FILE" ]] && pgid="$(<"$PGID_FILE")"
  if [[ -f "$RUN_JSON" ]]; then
    gpu="$(jq -r '.gpu // ""' "$RUN_JSON")"
    base_url="$(jq -r '.base_url // ""' "$RUN_JSON")"
    log_path="$(jq -r '.log_path // ""' "$RUN_JSON")"
  fi
  jq -n --arg action status --arg status "$state" --arg pid "$PID" \
    --arg pgid "$pgid" --arg gpu "$gpu" --arg base_url "$base_url" \
    --arg log_path "$log_path" --arg state_dir "$STATE_DIR" \
    --arg stop_command "$SCRIPT_DIR/vllm_server_control_with_probe_enabled.sh stop --state-dir $STATE_DIR" \
    '{action:$action,status:$status,pid:(if $pid=="" then null else ($pid|tonumber) end),
      pgid:(if $pgid=="" then null else ($pgid|tonumber) end),gpu:(if $gpu=="" then null else $gpu end),
      base_url:(if $base_url=="" then null else $base_url end),
      log_path:(if $log_path=="" then null else $log_path end),state_dir:$state_dir,stop_command:$stop_command}'
}

if [[ "$ACTION" == "status" ]]; then
  status_json
  exit 0
fi

if [[ "$ACTION" == "stop" ]]; then
  if ! is_running "$PID"; then
    status_json | jq '.action="stop" | .changed=false'
    exit 0
  fi
  PGID="$PID"
  [[ -f "$PGID_FILE" ]] && PGID="$(<"$PGID_FILE")"
  kill -TERM -- "-$PGID"
  deadline=$((SECONDS + STOP_TIMEOUT))
  while is_running "$PID" && (( SECONDS < deadline )); do sleep 0.25; done
  is_running "$PID" && kill -KILL -- "-$PGID"
  rm -f -- "$PID_FILE" "$PGID_FILE"
  PID=""
  status_json | jq '.action="stop" | .changed=true'
  exit 0
fi

is_running "$PID" && die "server already running with pid $PID"
VLLM_BIN="$VENV/bin/vllm"
VENV_PYTHON="$VENV/bin/python"
[[ -x "$VLLM_BIN" && -x "$VENV_PYTHON" ]] || die "vLLM environment missing: $VENV"
TARGET="$($VENV_PYTHON -c "import pathlib,sysconfig; print(pathlib.Path(sysconfig.get_paths()['purelib'])/'vllm')")"
PYTHON_BIN="$VENV_PYTHON" "$SCRIPT_DIR/patch-vllm.sh" check --target "$TARGET" >/dev/null

PROBE_PATH="$SCRIPT_DIR/$(jq -r '.probe.path' "$RECIPE_JSON")"
PROBE_SHA="$(jq -r '.probe.sha256' "$RECIPE_JSON")"
[[ "$(sha256sum "$PROBE_PATH" | awk '{print $1}')" == "$PROBE_SHA" ]] || die "probe sha256 mismatch"
PROBE_CONFIG="$(jq -c --arg checkpoint_path "$PROBE_PATH" '
  {schema:"inline_probing.probe_config.v1",checkpoint_schema:"inline_probing.probe_checkpoint.v2",
   scorer_contract_version:"inline_probing.linear_probe.v1",checkpoint_path:$checkpoint_path,
   checkpoint_sha256:.probe.sha256,model_family:.model.model_family,model_revision:.model.model_revision,
   target_layer:.probe.checkpoint_layer,requested_position:.probe.requested_position,
   effective_position:.probe.effective_position,activation_kind:.task.activation_kind,
   hidden_width:.model.hidden_width,normalization:"checkpoint",tensor_parallel_size:1,
   pipeline_parallel_size:1,required:true,transport:"inline",disable_ubatching:true,
   disable_speculative_decoding:true,disable_async_scheduling:true,
   disable_pipeline_batch_queues:true,max_deadline_ms:120000}' "$RECIPE_JSON")"
THRESHOLD="$(jq -r '.probe.threshold' "$RECIPE_JSON")"

mkdir -p "$STATE_DIR"
LOG_DIR="$COOLWATCH_DIR/logs/$(date -u +%F)"
mkdir -p "$LOG_DIR"
LOG_PATH="$LOG_DIR/qwen3-8b-inline-probing-$(date -u +%Y%m%dT%H%M%SZ).log"

COMMAND=("$VLLM_BIN" serve "$MODEL" --served-model-name "$SERVED_MODEL_NAME"
  --host "$HOST" --port "$PORT" --tensor-parallel-size 1 --pipeline-parallel-size 1
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" --max-model-len "$MAX_MODEL_LEN"
  --max-num-seqs "$MAX_NUM_SEQS" --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS"
  --enable-auto-tool-choice --tool-call-parser hermes --language-model-only
  --enable-chunked-prefill --enforce-eager --no-async-scheduling --ubatch-size 0)
ENVIRONMENT=("PATH=$VENV/bin:$PATH" "CUDA_VISIBLE_DEVICES=$GPU" "VLLM_USE_V2_MODEL_RUNNER=0"
  "INLINE_PROBING_CONFIG=$PROBE_CONFIG" "INLINE_PROBING_THRESHOLD=$THRESHOLD"
  "INLINE_PROBING_EXPECTED_CHECKPOINT_ID=sha256:$PROBE_SHA")
[[ -f "$PREFERRED_LIBSTDCXX" ]] && ENVIRONMENT+=("LD_PRELOAD=$PREFERRED_LIBSTDCXX")
[[ -n "$CUDA_COMPAT_LIB_DIR" ]] && ENVIRONMENT+=("LD_LIBRARY_PATH=$(realpath "$CUDA_COMPAT_LIB_DIR")")

nohup setsid env -u LD_LINK -u LD_LIBRARY_PATH -u LD_PRELOAD \
  "${ENVIRONMENT[@]}" "${COMMAND[@]}" </dev/null >>"$LOG_PATH" 2>&1 &
PID="$!"
printf '%s\n' "$PID" > "$PID_FILE"
printf '%s\n' "$PID" > "$PGID_FILE"
COMMAND_JSON="$(printf '%s\n' "${COMMAND[@]}" | jq -R . | jq -s .)"
jq -n --argjson pid "$PID" --arg gpu "$GPU" --arg base_url "http://$HOST:$PORT/v1" \
  --arg model "$MODEL" --arg served_model_name "$SERVED_MODEL_NAME" --arg log_path "$LOG_PATH" \
  --arg started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson command "$COMMAND_JSON" \
  '{schema:"coolwatch.inline_probing.server_state.v1",pid:$pid,pgid:$pid,gpu:$gpu,
    base_url:$base_url,model:$model,served_model_name:$served_model_name,log_path:$log_path,
    command:$command,started_at:$started_at}' > "$RUN_JSON"
sleep 0.5
is_running "$PID" || die "vLLM exited during startup; inspect $LOG_PATH"
status_json | jq '.action="start"'
