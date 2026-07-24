# CoolWatch Backend

FastAPI 后端负责接收前端聊天请求、执行 Agent Loop、调用本地 vLLM OpenAI-compatible API，并返回输入护栏检测状态、泄露指标和 RAG Trace。输入护栏是外接 query 检测层，不改写 Agent Loop 的上下文或模型输出。

## Llama Prompt Guard 2

选择 Llama Prompt Guard 2 时，后端会在 Agent Loop 前通过 Transformers 懒加载本地 86M 分类模型，对本轮 query 做 Prompt Injection / Jailbreak 二分类。模型最长处理 512 tokens，超出部分会截断。

```dotenv
LLAMA_PROMPT_GUARD_MODEL=../models/Llama-Prompt-Guard-2-86M
LLAMA_PROMPT_GUARD_THRESHOLD=0.5
LLAMA_PROMPT_GUARD_MAX_LENGTH=512
LLAMA_PROMPT_GUARD_DEVICE=auto
```

检测结果的 `MALICIOUS` 概率、阈值和原始概率数组会写入 `guard_results.llama_prompt_guard`。模型权重位于仓库外，不会被 Git 提交。

## SafeGauge

选择 SafeGauge 时，CoolWatch 后端会在进程内加载 MLP，并在 Agent Loop 前检测当前场景的 System Prompt 和本轮用户 Query。生成 prefill logprobs 时直接复用 `VLLM_BASE_URL`，不需要独立 SafeGauge 服务。

```dotenv
SAFEGAUGE_PROCESSOR_PATH=
SAFEGAUGE_TOKENIZER_PATH=
SAFEGAUGE_DEVICE=cpu
SAFEGAUGE_TIMEOUT_SECONDS=120
```

`SAFEGAUGE_PROCESSOR_PATH` 为空时，后端会按 `VLLM_MODEL` 的最后一段自动匹配 `backend/watchers/safegauge/models/<model>/`。找不到或匹配到多个 checkpoint 时，需要显式指定路径。

SafeGauge 返回的任务、标签、概率、阈值和原始响应会写入 `guard_results.safegauge`。当前框架仍采用检测对比模式，即风险命中只给出拦截建议，不会跳过 Agent Loop。

## Qwen3Guard

选择 Qwen3Guard 时，后端会先对本轮用户 query 做一次 Qwen3Guard-Gen 检测，再执行 Agent Loop。检测结果只写入 `guard_results.qwen_guard`，不改写 System Prompt、用户输入、RAG 上下文或模型输出。

默认使用本机 snapshot：

```text
QWEN3_GUARD_BACKEND=auto
QWEN3_GUARD_MODEL=../../../../share/workspace/models/hub/models--Qwen--Qwen3Guard-Gen-8B/snapshots/4505cb1a6f1864f21f8b27f7daf1b9a1aab6edbb
```

`auto` 模式下，如果设置了 `QWEN3_GUARD_BASE_URL`，后端会优先调用独立 OpenAI-compatible guard 服务：

```bash
QWEN3_GUARD_BASE_URL=http://127.0.0.1:8001/v1 \
QWEN3_GUARD_MODEL=Qwen/Qwen3Guard-Gen-8B \
./start-coolwatch.sh
```

也可以按官方方式单独启动 guard 服务：

```bash
vllm serve ../../../../share/workspace/models/hub/models--Qwen--Qwen3Guard-Gen-8B/snapshots/4505cb1a6f1864f21f8b27f7daf1b9a1aab6edbb \
  --port 8001 \
  --max-model-len 32768
```

未设置 `QWEN3_GUARD_BASE_URL` 时，后端会懒加载本地 Transformers 模型。首次选择 Qwen3Guard 会加载 8B 模型，耗时和显存占用都比较高；演示环境更建议将 Qwen3Guard 作为独立 vLLM/SGLang 服务运行。

## 网易易盾

选择“网易易盾”时，后端会按文本单次同步检测接口，在本轮 query 进入 Agent Loop 前调用易盾文本检测。检测结果只写入 `guard_results.netease_yidun`，不拦截、不改写用户输入或模型输出。

需要在 `backend/.env` 配置易盾控制台提供的密钥和业务 ID。后端启动时会自动读取该文件；同名系统环境变量仍然可以覆盖 `.env` 中的值。

```text
NETEASE_YIDUN_SECRET_ID=your_secret_id
NETEASE_YIDUN_SECRET_KEY=your_secret_key
NETEASE_YIDUN_BUSINESS_ID=your_business_id
```

可选配置：

```text
NETEASE_YIDUN_API_URL=http://as.dun.163.com/v5/text/check
NETEASE_YIDUN_VERSION=v5.2
NETEASE_YIDUN_SIGNATURE_METHOD=
NETEASE_YIDUN_TIMEOUT_SECONDS=2
NETEASE_YIDUN_CHECK_LABELS=
```

未配置密钥时，选择“网易易盾”会返回“未配置”，用于提示当前环境还没有接入真实账号。

## 运行

```bash
./start-coolwatch.sh
```

默认连接：

```text
VLLM_BASE_URL=http://127.0.0.1:18087/v1
VLLM_MODEL=Qwen3.5-27B
VLLM_API_KEY=EMPTY
```

如需修改：

```bash
VLLM_BASE_URL=http://127.0.0.1:18087/v1 VLLM_MODEL=Qwen3.5-27B uvicorn backend.app:app --host 0.0.0.0 --port 9254
```

启动后访问：

```text
http://127.0.0.1:18088
```

前端点击“发送”会请求 `POST /api/chat`，后端会实际调用 vLLM 的 `/chat/completions`。
