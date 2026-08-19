#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PERSPECTIVE_WATCH_DIR="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
DEFAULT_PROBE_RECIPE="$SCRIPT_DIR/recipe.json"
DEFAULT_VENV="$PERSPECTIVE_WATCH_DIR/.runtime/vllm-0.25.1-inline-probing"
DEFAULT_STATE_DIR="$PERSPECTIVE_WATCH_DIR/.runtime/qwen3-8b-inline-probing-server"
PREFERRED_LIBSTDCXX="${PREFERRED_LIBSTDCXX:-}"

die() { echo "vllm-server-control: $*" >&2; exit 1; }
usage() { echo "usage: $0 {start|status|stop} [options]" >&2; exit 2; }
is_running() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }

[[ $# -ge 1 ]] || usage
ACTION="$1"
shift
[[ "$ACTION" =~ ^(start|status|stop)$ ]] || usage

VENV="$DEFAULT_VENV"
STATE_DIR="$DEFAULT_STATE_DIR"
PROBE_RECIPES=()
MODEL="Qwen/Qwen3-8B"
SERVED_MODEL_NAME="qwen3-8b"
GPU="0"
HOST="127.0.0.1"
PORT="8013"
GPU_MEMORY_UTILIZATION="0.9"
MAX_MODEL_LEN="32768"
MAX_NUM_SEQS="8"
MAX_NUM_BATCHED_TOKENS="8192"
MAX_LOGPROBS="100"
CUDA_COMPAT_LIB_DIR=""
STOP_TIMEOUT="30"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv) VENV="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --probe-recipe) PROBE_RECIPES+=("$2"); shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --served-model-name) SERVED_MODEL_NAME="$2"; shift 2 ;;
    --gpu) GPU="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --gpu-memory-utilization) GPU_MEMORY_UTILIZATION="$2"; shift 2 ;;
    --max-model-len) MAX_MODEL_LEN="$2"; shift 2 ;;
    --max-num-seqs) MAX_NUM_SEQS="$2"; shift 2 ;;
    --max-num-batched-tokens) MAX_NUM_BATCHED_TOKENS="$2"; shift 2 ;;
    --max-logprobs) MAX_LOGPROBS="$2"; shift 2 ;;
    --cuda-compat-lib-dir) CUDA_COMPAT_LIB_DIR="$2"; shift 2 ;;
    --timeout) STOP_TIMEOUT="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

VENV="$(realpath -m "$VENV")"
STATE_DIR="$(realpath -m "$STATE_DIR")"
[[ ${#PROBE_RECIPES[@]} -gt 0 ]] || PROBE_RECIPES=("$DEFAULT_PROBE_RECIPE")
for index in "${!PROBE_RECIPES[@]}"; do
  PROBE_RECIPES[$index]="$(realpath -m "${PROBE_RECIPES[$index]}")"
done
PROBE_RECIPE="${PROBE_RECIPES[0]}"
PID_FILE="$STATE_DIR/run.pid"
PGID_FILE="$STATE_DIR/run.pgid"
RUN_JSON="$STATE_DIR/run.json"
PID=""
[[ -f "$PID_FILE" ]] && PID="$(<"$PID_FILE")"

status_json() {
  local state="stopped" pgid="" gpu="" base_url="" log_path="" probe_recipe="" recipe_id="" checkpoint_id="" probe_task=""
  local probe_recipes='[]' probe_ids='[]' checkpoint_ids='[]' probe_tasks='[]'
  is_running "$PID" && state="running"
  [[ -f "$PGID_FILE" ]] && pgid="$(<"$PGID_FILE")"
  if [[ -f "$RUN_JSON" ]]; then
    gpu="$(jq -r '.gpu // ""' "$RUN_JSON")"
    base_url="$(jq -r '.base_url // ""' "$RUN_JSON")"
    log_path="$(jq -r '.log_path // ""' "$RUN_JSON")"
    probe_recipe="$(jq -r '.probe_recipe // ""' "$RUN_JSON")"
    recipe_id="$(jq -r '.recipe_id // ""' "$RUN_JSON")"
    checkpoint_id="$(jq -r '.checkpoint_id // ""' "$RUN_JSON")"
    probe_task="$(jq -r '.probe_task // ""' "$RUN_JSON")"
    probe_recipes="$(jq -c '.probe_recipes // []' "$RUN_JSON")"
    probe_ids="$(jq -c '.probe_ids // []' "$RUN_JSON")"
    checkpoint_ids="$(jq -c '.checkpoint_ids // []' "$RUN_JSON")"
    probe_tasks="$(jq -c '.probe_tasks // []' "$RUN_JSON")"
  fi
  jq -n --arg action status --arg status "$state" --arg pid "$PID" \
    --arg pgid "$pgid" --arg gpu "$gpu" --arg base_url "$base_url" \
    --arg log_path "$log_path" --arg state_dir "$STATE_DIR" --arg probe_recipe "$probe_recipe" \
    --arg recipe_id "$recipe_id" --arg checkpoint_id "$checkpoint_id" --arg probe_task "$probe_task" \
    --argjson probe_recipes "$probe_recipes" --argjson probe_ids "$probe_ids" \
    --argjson checkpoint_ids "$checkpoint_ids" --argjson probe_tasks "$probe_tasks" \
    --arg stop_command "$SCRIPT_DIR/vllm_server_control_with_probe_enabled.sh stop --state-dir $STATE_DIR" \
    '{action:$action,status:$status,pid:(if $pid=="" then null else ($pid|tonumber) end),
      pgid:(if $pgid=="" then null else ($pgid|tonumber) end),gpu:(if $gpu=="" then null else $gpu end),
      base_url:(if $base_url=="" then null else $base_url end),
      log_path:(if $log_path=="" then null else $log_path end),
      probe_recipe:(if $probe_recipe=="" then null else $probe_recipe end),
      recipe_id:(if $recipe_id=="" then null else $recipe_id end),
      checkpoint_id:(if $checkpoint_id=="" then null else $checkpoint_id end),
      probe_task:(if $probe_task=="" then null else $probe_task end),
      probe_recipes:$probe_recipes,probe_ids:$probe_ids,
      checkpoint_ids:$checkpoint_ids,probe_tasks:$probe_tasks,
      state_dir:$state_dir,stop_command:$stop_command}'
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

PROBE_CONFIGS='[]'
PROBE_RECIPE_PATHS='[]'
PROBE_IDS='[]'
CHECKPOINT_IDS='[]'
PROBE_TASKS='[]'
MODEL_SIGNATURE=""
PROBE_CONFIG=""
PROBE_SHA=""
RECIPE_ID=""
PROBE_TASK=""
THRESHOLD=""
for current_recipe in "${PROBE_RECIPES[@]}"; do
  [[ -f "$current_recipe" ]] || die "probe recipe missing: $current_recipe"
  jq -e '.probe.path and .probe.sha256 and .probe.checkpoint_layer != null and .task.activation_kind and .model.hidden_width' \
    "$current_recipe" >/dev/null || die "invalid probe recipe: $current_recipe"
  recipe_dir="$(dirname "$current_recipe")"
  relative_path="$(jq -r '.probe.path' "$current_recipe")"
  if [[ "$relative_path" = /* ]]; then
    probe_path="$(realpath -m "$relative_path")"
  else
    probe_path="$(realpath -m "$recipe_dir/$relative_path")"
  fi
  probe_sha="$(jq -r '.probe.sha256' "$current_recipe")"
  recipe_id="$(jq -r '.recipe_id // "custom-inline-probe"' "$current_recipe")"
  probe_id="$(jq -r '.probe.id // .recipe_id // "custom-inline-probe"' "$current_recipe")"
  probe_task="$(jq -r '.task.id // .task.threat_model // ""' "$current_recipe")"
  if jq -e --arg probe_id "$probe_id" 'index($probe_id) != null' <<<"$PROBE_IDS" >/dev/null; then
    die "duplicate probe ID: $probe_id"
  fi
  model_signature="$(jq -c '[.model.model_family,.model.model_revision,.model.hidden_width]' "$current_recipe")"
  [[ -z "$MODEL_SIGNATURE" || "$MODEL_SIGNATURE" == "$model_signature" ]] || \
    die "all probe recipes must target the same model runtime"
  MODEL_SIGNATURE="$model_signature"
  [[ -f "$probe_path" ]] || die "probe checkpoint missing: $probe_path"
  [[ "$(sha256sum "$probe_path" | awk '{print $1}')" == "$probe_sha" ]] || \
    die "probe sha256 mismatch: $probe_id"
  probe_config="$(jq -c --arg checkpoint_path "$probe_path" --arg probe_id "$probe_id" --arg task "$probe_task" '
    {schema:"inline_probing.probe_config.v1",
     checkpoint_schema:(.probe.checkpoint_schema // "inline_probing.probe_checkpoint.v2"),
     scorer_contract_version:"inline_probing.linear_probe.v1",checkpoint_path:$checkpoint_path,
     checkpoint_sha256:.probe.sha256,model_family:.model.model_family,model_revision:.model.model_revision,
     target_layer:.probe.checkpoint_layer,requested_position:.probe.requested_position,
     effective_position:.probe.effective_position,activation_kind:.task.activation_kind,
     hidden_width:.model.hidden_width,normalization:"checkpoint",tensor_parallel_size:1,
     pipeline_parallel_size:1,required:true,transport:"inline",disable_ubatching:true,
     disable_speculative_decoding:true,disable_async_scheduling:true,
     disable_pipeline_batch_queues:true,max_deadline_ms:120000,probe_id:$probe_id,task:$task,
     decision_threshold:(.probe.probability_threshold // .probe.threshold // null),
     target_layers:(.probe.checkpoint_layers // [.probe.checkpoint_layer])}' "$current_recipe")"
  PROBE_CONFIGS="$(jq -cn --argjson values "$PROBE_CONFIGS" --argjson item "$probe_config" '$values + [$item]')"
  PROBE_RECIPE_PATHS="$(jq -cn --argjson values "$PROBE_RECIPE_PATHS" --arg item "$current_recipe" '$values + [$item]')"
  PROBE_IDS="$(jq -cn --argjson values "$PROBE_IDS" --arg item "$probe_id" '$values + [$item]')"
  CHECKPOINT_IDS="$(jq -cn --argjson values "$CHECKPOINT_IDS" --arg item "sha256:$probe_sha" '$values + [$item]')"
  PROBE_TASKS="$(jq -cn --argjson values "$PROBE_TASKS" --arg item "$probe_task" '$values + [$item]')"
  if [[ -z "$PROBE_CONFIG" ]]; then
    PROBE_CONFIG="$probe_config"
    PROBE_SHA="$probe_sha"
    RECIPE_ID="$recipe_id"
    PROBE_TASK="$probe_task"
    THRESHOLD="$(jq -r '.probe.probability_threshold // .probe.threshold // 0.5' "$current_recipe")"
  fi
done

if [[ -f "$MODEL/config.json" ]]; then
  expected_hidden_width="$(jq -r '.[2]' <<<"$MODEL_SIGNATURE")"
  actual_hidden_width="$(jq -r '.hidden_size // 0' "$MODEL/config.json")"
  [[ "$actual_hidden_width" == "$expected_hidden_width" ]] || \
    die "model hidden width mismatch: recipe=$expected_hidden_width model=$actual_hidden_width"
fi

mkdir -p "$STATE_DIR"
LOG_DIR="$PERSPECTIVE_WATCH_DIR/logs/$(date -u +%F)"
mkdir -p "$LOG_DIR"
LOG_MODEL_NAME="${SERVED_MODEL_NAME//\//-}"
LOG_PATH="$LOG_DIR/$LOG_MODEL_NAME-inline-probing-$(date -u +%Y%m%dT%H%M%SZ).log"

COMMAND=("$VLLM_BIN" serve "$MODEL" --served-model-name "$SERVED_MODEL_NAME"
  --host "$HOST" --port "$PORT" --tensor-parallel-size 1 --pipeline-parallel-size 1
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" --max-model-len "$MAX_MODEL_LEN"
  --max-num-seqs "$MAX_NUM_SEQS" --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS"
  --max-logprobs "$MAX_LOGPROBS"
  --reasoning-parser qwen3
  --enable-auto-tool-choice --tool-call-parser hermes --language-model-only
  --enable-chunked-prefill --enforce-eager --no-async-scheduling --ubatch-size 0)
ENVIRONMENT=("PATH=$VENV/bin:$PATH" "CUDA_VISIBLE_DEVICES=$GPU" "VLLM_USE_V2_MODEL_RUNNER=0"
  "INLINE_PROBING_CONFIG=$PROBE_CONFIG" "INLINE_PROBING_CONFIGS=$PROBE_CONFIGS"
  "INLINE_PROBING_THRESHOLD=$THRESHOLD"
  "INLINE_PROBING_EXPECTED_CHECKPOINT_ID=sha256:$PROBE_SHA")
[[ -n "$PREFERRED_LIBSTDCXX" && -f "$PREFERRED_LIBSTDCXX" ]] && ENVIRONMENT+=("LD_PRELOAD=$PREFERRED_LIBSTDCXX")
[[ -n "$CUDA_COMPAT_LIB_DIR" ]] && ENVIRONMENT+=("LD_LIBRARY_PATH=$(realpath "$CUDA_COMPAT_LIB_DIR")")

nohup setsid env -u LD_LINK -u LD_LIBRARY_PATH -u LD_PRELOAD \
  "${ENVIRONMENT[@]}" "${COMMAND[@]}" </dev/null >>"$LOG_PATH" 2>&1 &
PID="$!"
printf '%s\n' "$PID" > "$PID_FILE"
printf '%s\n' "$PID" > "$PGID_FILE"
COMMAND_JSON="$(printf '%s\n' "${COMMAND[@]}" | jq -R . | jq -s .)"
jq -n --argjson pid "$PID" --arg gpu "$GPU" --arg base_url "http://$HOST:$PORT/v1" \
  --arg model "$MODEL" --arg served_model_name "$SERVED_MODEL_NAME" --arg log_path "$LOG_PATH" \
  --arg probe_recipe "$PROBE_RECIPE" --arg recipe_id "$RECIPE_ID" \
  --arg checkpoint_id "sha256:$PROBE_SHA" --arg probe_task "$PROBE_TASK" \
  --argjson probe_recipes "$PROBE_RECIPE_PATHS" --argjson probe_ids "$PROBE_IDS" \
  --argjson checkpoint_ids "$CHECKPOINT_IDS" --argjson probe_tasks "$PROBE_TASKS" \
  --arg started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson command "$COMMAND_JSON" \
  '{schema:"perspective_watch.inline_probing.server_state.v1",pid:$pid,pgid:$pid,gpu:$gpu,
    base_url:$base_url,model:$model,served_model_name:$served_model_name,log_path:$log_path,
    probe_recipe:$probe_recipe,recipe_id:$recipe_id,checkpoint_id:$checkpoint_id,
    probe_task:$probe_task,probe_recipes:$probe_recipes,probe_ids:$probe_ids,
    checkpoint_ids:$checkpoint_ids,probe_tasks:$probe_tasks,command:$command,
    started_at:$started_at}' > "$RUN_JSON"
sleep 0.5
is_running "$PID" || die "vLLM exited during startup; inspect $LOG_PATH"
status_json | jq '.action="start"'
