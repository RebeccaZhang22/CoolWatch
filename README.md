# CoolWatch

CoolWatch 是一个 LLM 安全攻防演示项目。下面以 `Llama-3.1-8B-Instruct` 为例，让 Agent 和 SafeGauge 复用同一个 vLLM 服务，并使用与该模型匹配的 suffix-probe checkpoint 检测系统提示词泄露意图。

## 运行架构

```text
浏览器：http://127.0.0.1:8000
  └─ CoolWatch / FastAPI
       ├─ Llama-3.1-8B-Instruct vLLM：http://127.0.0.1:8768/v1
       ├─ SafeGauge：http://127.0.0.1:8900
       ├─ Llama Prompt Guard 2（可选，本地懒加载）
       ├─ Qwen3Guard（可选）
       └─ 网易易盾（可选）
```

以下命令直接使用当前 Python/vLLM 环境。请将尖括号中的占位符替换为本机绝对路径；三步启动分别占用三个终端。

需要准备：

```text
项目目录：<absolute-path-to-CoolWatch>
Llama 模型：<absolute-path-to-Llama-3.1-8B-Instruct>

SafeGauge checkpoint:
<absolute-path-to-CoolWatch>/backend/watchers/safegauge/models/Llama-3.1-8B-Instruct/sys_prompt/best_model.pt
```

## 第一步：启动 Llama-3.1-8B-Instruct

终端 1：

```bash
export COOLWATCH_ROOT="<absolute-path-to-CoolWatch>"
export LLAMA_MODEL_PATH="<absolute-path-to-Llama-3.1-8B-Instruct>"
cd "$COOLWATCH_ROOT"

CUDA_VISIBLE_DEVICES=0 vllm serve \
  "$LLAMA_MODEL_PATH" \
  --served-model-name Llama-3.1-8B-Instruct \
  --host 127.0.0.1 \
  --port 8768 \
  --dtype bfloat16 \
  --tensor-parallel-size 1 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --trust-remote-code
```

等模型加载完成后检查：

```bash
curl http://127.0.0.1:8768/v1/models
```

返回的模型列表应包含 `Llama-3.1-8B-Instruct`。当前 vLLM 默认的 `max_logprobs=20`、`logprobs_mode=raw_logprobs` 已满足 SafeGauge 请求，无需显式传入。

## 第二步：启动 SafeGauge

终端 2：

```bash
export COOLWATCH_ROOT="<absolute-path-to-CoolWatch>"
export LLAMA_MODEL_PATH="<absolute-path-to-Llama-3.1-8B-Instruct>"
cd "$COOLWATCH_ROOT"

python "$COOLWATCH_ROOT/backend/watchers/safegauge/service.py" \
  --processor-path "$COOLWATCH_ROOT/backend/watchers/safegauge/models/Llama-3.1-8B-Instruct/sys_prompt/best_model.pt" \
  --base-url http://127.0.0.1:8768/v1 \
  --api-key EMPTY \
  --model Llama-3.1-8B-Instruct \
  --tokenizer-path "$LLAMA_MODEL_PATH" \
  --device cpu \
  --host 127.0.0.1 \
  --port 8900
```

检查 SafeGauge 和加载的 meta：

```bash
curl http://127.0.0.1:8900/health
curl http://127.0.0.1:8900/model/info
```

`model/info` 返回值的 `meta` 中应显示：

```text
meta.model_name: Llama-3.1-8B-Instruct
meta.task: system_prompt_leakage_intent
meta.best_threshold: 0.42150071263313293
```

## 第三步：启动 CoolWatch

终端 3：

```bash
export COOLWATCH_ROOT="<absolute-path-to-CoolWatch>"
cd "$COOLWATCH_ROOT"

VLLM_BASE_URL=http://127.0.0.1:8768/v1 \
VLLM_API_KEY=EMPTY \
VLLM_MODEL=Llama-3.1-8B-Instruct \
SAFEGAUGE_BASE_URL=http://127.0.0.1:8900 \
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

检查后端：

```bash
curl http://127.0.0.1:8000/api/health
```

然后在浏览器访问：

```text
http://127.0.0.1:8000
```

FastAPI 会直接托管 `frontend/`，不需要单独启动前端服务。进入页面后勾选 `SafeGauge`，即可使用 Llama-3.1-8B-Instruct 对应的 `system_prompt_leakage_intent` 探针。

## 可选输入护栏

### Llama Prompt Guard 2

本地权重配置示例：

```dotenv
LLAMA_PROMPT_GUARD_MODEL=<absolute-path-to-Llama-Prompt-Guard-2-86M>
LLAMA_PROMPT_GUARD_THRESHOLD=0.5
LLAMA_PROMPT_GUARD_MAX_LENGTH=512
LLAMA_PROMPT_GUARD_DEVICE=auto
```

它会在页面第一次勾选时由后端懒加载，不需要额外启动服务。

### Qwen3Guard

如果已有独立的 Qwen3Guard OpenAI-compatible 服务，可在 `backend/.env` 配置：

```dotenv
QWEN3_GUARD_BACKEND=openai
QWEN3_GUARD_BASE_URL=http://127.0.0.1:8001/v1
QWEN3_GUARD_API_KEY=EMPTY
QWEN3_GUARD_MODEL=Qwen/Qwen3Guard-Gen-8B
```

未设置 `QWEN3_GUARD_BASE_URL` 时，`auto` 模式会尝试通过 Transformers 本地加载配置的 Qwen3Guard 权重。

### 网易易盾

在 `backend/.env` 填写：

```dotenv
NETEASE_YIDUN_SECRET_ID=your_secret_id
NETEASE_YIDUN_SECRET_KEY=your_secret_key
NETEASE_YIDUN_BUSINESS_ID=your_business_id
```

未配置密钥时，页面选择网易易盾会返回“未配置”。

## 三步启动摘要

```text
终端 1：Llama-3.1-8B-Instruct vLLM  127.0.0.1:8768
终端 2：SafeGauge                   127.0.0.1:8900
终端 3：CoolWatch + 前端            0.0.0.0:8000
```
