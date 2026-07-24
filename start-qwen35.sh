#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3.5-27B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-${MODEL##*/}}"
PORT="${PORT:-18087}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
GPU_IDS="${GPU_IDS:-${CUDA_VISIBLE_DEVICES:-}}"
EXTRA_ARGS=()

while (( $# > 0 )); do
    case "$1" in
        --gpus)
            if (( $# < 2 )); then
                echo "错误：--gpus 后需要提供 GPU 编号，例如 --gpus 0,1。" >&2
                exit 2
            fi
            GPU_IDS="$2"
            shift 2
            ;;
        --gpus=*)
            GPU_IDS="${1#*=}"
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "错误：未找到 nvidia-smi，请确认已安装 NVIDIA 驱动。" >&2
    exit 1
fi

if ! command -v vllm >/dev/null 2>&1; then
    echo "错误：未找到 vllm，请先运行：pip install -U vllm" >&2
    exit 1
fi

AVAILABLE_GPU_IDS="$(nvidia-smi --query-gpu=index --format=csv,noheader | paste -sd, -)"
if [[ -z "$AVAILABLE_GPU_IDS" ]]; then
    echo "错误：未检测到可用的 NVIDIA GPU。" >&2
    exit 1
fi

GPU_IDS="${GPU_IDS//[[:space:]]/}"
GPU_IDS="${GPU_IDS:-$AVAILABLE_GPU_IDS}"
if [[ ! "$GPU_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    echo "错误：GPU 编号格式无效：$GPU_IDS；示例：--gpus 0,1。" >&2
    exit 2
fi

IFS=',' read -r -a SELECTED_GPU_IDS <<< "$GPU_IDS"
for gpu_id in "${SELECTED_GPU_IDS[@]}"; do
    if [[ ",$AVAILABLE_GPU_IDS," != *",$gpu_id,"* ]]; then
        echo "错误：GPU $gpu_id 不存在；可用 GPU：$AVAILABLE_GPU_IDS。" >&2
        exit 2
    fi
done

GPU_COUNT="${#SELECTED_GPU_IDS[@]}"
TP_SIZE="${TP_SIZE:-$GPU_COUNT}"
export CUDA_VISIBLE_DEVICES="$GPU_IDS"

echo "模型：$MODEL"
echo "服务模型名：$SERVED_MODEL_NAME"
echo "使用 GPU：$GPU_IDS"
echo "张量并行：$TP_SIZE"
echo "上下文长度：$MAX_MODEL_LEN"
echo "接口：http://127.0.0.1:$PORT/v1"

exec vllm serve "$MODEL" \
    --served-model-name "$SERVED_MODEL_NAME" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --tensor-parallel-size "$TP_SIZE" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --reasoning-parser qwen3 \
    --language-model-only \
    "${EXTRA_ARGS[@]}"
