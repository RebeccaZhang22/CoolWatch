# CoolWatch

CoolWatch 是一个 LLM 安全攻防演示项目。Agent 和 SafeGauge 复用同一个 vLLM 服务；SafeGauge MLP 由 CoolWatch 后端进程内加载，不需要单独启动检测服务。

## 运行架构

```text
浏览器：http://127.0.0.1:18088
  └─ CoolWatch / FastAPI
       ├─ Qwen3.5-27B vLLM：http://127.0.0.1:18087/v1
       ├─ SafeGauge MLP（进程内加载，复用上述 vLLM）
       ├─ Llama Prompt Guard 2（可选，本地懒加载）
       ├─ Qwen3Guard（可选）
       └─ 网易易盾（可选）
```

以下命令直接使用当前 Python/vLLM 环境，只需要启动 vLLM 和 CoolWatch 两个进程。当前机器已经存在完整的 Qwen3.5-27B 权重：

```text
/share/workspace/models/hub/models--Qwen--Qwen3.5-27B/snapshots/fc05daec18b0a78c049392ed2e771dde82bdf654
```

## 第一步：启动 Qwen3.5-27B

终端 1：

```bash
cd /ssd/workspace/zms/CoolWatch

MODEL=/share/workspace/models/hub/models--Qwen--Qwen3.5-27B/snapshots/fc05daec18b0a78c049392ed2e771dde82bdf654 \
SERVED_MODEL_NAME=Qwen3.5-27B \
./start-qwen35.sh --gpus 0,1
```

`--gpus` 显式指定物理 GPU 编号，例如单卡使用 `--gpus 0`，四卡使用 `--gpus 0,1,2,3`。脚本会按照所选 GPU 数量自动设置 `tensor-parallel-size`。

等模型加载完成后检查：

```bash
curl http://127.0.0.1:18087/v1/models
```

返回的模型列表应包含 `Qwen3.5-27B`。vLLM 的 prompt logprobs 能力会同时供 SafeGauge 使用。

## 第二步：启动 CoolWatch

终端 2：

```bash
cd /ssd/workspace/zms/CoolWatch
./start-coolwatch.sh
```

启动脚本的默认配置已经与模型服务对齐：

```text
VLLM_BASE_URL=http://127.0.0.1:18087/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=Qwen3.5-27B
CoolWatch PORT=18088
```

检查后端：

```bash
curl http://127.0.0.1:18088/api/health
```

然后在浏览器访问：

```text
http://127.0.0.1:18088
```

FastAPI 会直接托管 `frontend/`。页面首次读取 SafeGauge 信息时，后端会自动加载与 `VLLM_MODEL` 同名目录中的 `best_model.pt`；检测时复用 `VLLM_BASE_URL`，没有额外端口。

如需指定 checkpoint、tokenizer 或 MLP 设备：

```dotenv
SAFEGAUGE_PROCESSOR_PATH=backend/watchers/safegauge/models/Qwen3.5-27B/universe/best_model.pt
SAFEGAUGE_TOKENIZER_PATH=
SAFEGAUGE_DEVICE=cpu
SAFEGAUGE_TIMEOUT_SECONDS=120
```

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

## 两步启动摘要

```text
终端 1：Qwen3.5-27B vLLM            127.0.0.1:18087
终端 2：CoolWatch + SafeGauge + 前端 0.0.0.0:18088
```
