# CoolWatch Backend

FastAPI 后端负责接收前端聊天请求、执行 Agent Loop、调用本地 vLLM OpenAI-compatible API，并返回护栏检测状态、泄露指标和 RAG Trace。Qwen3Guard、Llama Prompt Guard、SafeGauge 和易盾在生成前执行；Inline Probing 则嵌入新工具返回后的首次真实 assistant generation。所有护栏均不改写模型上下文或输出。

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

## Inline Probing

选择 Inline Probing 时，Agent Loop 会在每批新工具返回后的第一个 assistant decision point 启用检测。完整 tool result、消息历史、工具定义和正常生成参数会一起发给同一个 patched vLLM OpenAI-compatible `/chat/completions` 服务，该次真实生成请求同时携带 `inline_probing_request`。同一个响应既返回 assistant 内容，也返回 `inline_probing` 结果；不再发送独立的 `max_tokens=1` probe 请求。

生产运行时不会预先知道 tool result 是否含有注入，因此会检测每个新 tool-result batch 后的首次决策。实验评估才根据冻结的 injection round index，只统计已知的注入轮次。如果本轮生成前没有新 tool result，返回状态为“未触发”。

CoolWatch 后端不接收 raw hidden states，也不加载 probe checkpoint；它只构造 typed request，并严格验证 result schema、status、checkpoint ID 和有限数值。

```dotenv
INLINE_PROBING_PROTOCOL=inline_probing
INLINE_PROBING_EXPECTED_CHECKPOINT_ID=sha256:<probe-checkpoint-sha256>
INLINE_PROBING_THRESHOLD=0.5
INLINE_PROBING_TIMEOUT_SECONDS=120
```

该集成只使用 `inline_probing` 命名。如果 vLLM server 尚未暴露 `inline_probing_request` / `inline_probing`，需要先迁移 server patch 的 OpenAI protocol 字段。

仓库内置了
`qwen3-8b-indirect-prompt-injection-assistant-prefix-probing` golden recipe：

```bash
python -m backend.watchers.inline_probing.golden_recipe
```

它包含 probe checkpoint 和覆盖 16 个 strict grid points 的 32 positive +
32 negative replay cases，不包含 hidden states 或离线 feature tensors。连接
patched Qwen3-8B vLLM 后可执行真实在线回归，具体命令见
`recipe/inline_probing/qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/README.md`。

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

实验审计路径与普通聊天路径不同。在 injected-decision-point 评测中，Qwen3Guard
和易盾只检测 `tool_result`，即未经攻击抽取或裁剪的完整工具返回。
普通聊天页面目前仍只在 Agent Loop 前检测本轮用户消息；它不应被解释为已经
覆盖后续工具返回中的间接提示注入。

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
VLLM_BASE_URL=http://127.0.0.1:8013/v1
VLLM_MODEL=qwen3-8b
VLLM_API_KEY=EMPTY
INLINE_PROBING_EXPECTED_CHECKPOINT_ID=sha256:41f1433346caebc8b2e9ff5640b44e3d162050d6ef7ffee45285badba4798b45
```

如需修改：

```bash
VLLM_BASE_URL=http://127.0.0.1:8013/v1 VLLM_MODEL=qwen3-8b uvicorn backend.app:app --host 0.0.0.0 --port 9254
```

启动后访问：

```text
http://127.0.0.1:18088
```

前端点击“发送”会请求 `POST /api/chat`，后端会实际调用 vLLM 的 `/chat/completions`。
