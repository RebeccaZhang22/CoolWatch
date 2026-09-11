# ProspectMonitor Backend

FastAPI 后端负责接收前端聊天请求、执行 Agent Loop、调用本地 vLLM OpenAI-compatible API，并返回护栏检测状态、泄露指标和 RAG Trace。在原有 `/api/chat` 中，Qwen3Guard、Llama Prompt Guard、Suffix Probe（界面名称为 SafeGauge）和易盾在生成前执行；FinVault/系统提示词场景的基于隐藏层的可解释性技术可由 patched vLLM worker 或独立 Transformers 服务执行；间接提示词注入的 Inline Probing 则嵌入新工具返回后的首次真实 assistant generation。这条旧链路中的护栏均不改写模型上下文或输出。

首页使用独立的 `/api/customer-agent/*` API：面向终端客户的 Qwen3-8B 银行财富管理客服自主选择客户持仓、资金审批、调仓草稿或知识检索工具，并使用 `jieba + BM25Okapi` 检索合成金融语料；金融沙盒工具再使用 `gpt-4.1-mini` 生成合成业务响应。defended 模式会在业务模型生成前执行输入检测；任一已启用护栏命中风险，就跳过模型和工具调用，只返回固定安全提示。任意自然消息都可以直接运行或做“其他已有产品对照 / 我们的产品防护”对照。启动方式、API 契约和双模型隔离规则见 [银行财富管理客服后端](CUSTOMER_AGENT.md)。原有 `/api/chat` 仅供旧审计与回放页面兼容。

## Llama Prompt Guard 2

选择 Llama Prompt Guard 2 时，后端会在 Agent Loop 前通过 Transformers 懒加载本地 86M 分类模型，对本轮 query 做 Prompt Injection / Jailbreak 二分类。模型最长处理 512 tokens，超出部分会截断。

```dotenv
LLAMA_PROMPT_GUARD_MODEL=meta-llama/Llama-Prompt-Guard-2-86M
LLAMA_PROMPT_GUARD_THRESHOLD=0.5
LLAMA_PROMPT_GUARD_MAX_LENGTH=512
LLAMA_PROMPT_GUARD_DEVICE=auto
```

检测结果的 `MALICIOUS` 概率、阈值和原始概率数组会写入 `guard_results.llama_prompt_guard`。模型权重位于仓库外，不会被 Git 提交。

## SafeGauge / Suffix Probe

选择 SafeGauge 时，ProspectMonitor 后端会按场景和模型，从 `results/gauge_probe/` 选择对应 MLP，并在 Agent Loop 前检测当前场景的 System Prompt 和本轮用户 Query。生成 prefill logprobs 时复用本轮 Qwen vLLM 端口，不需要独立 SafeGauge 服务。

```dotenv
SAFEGAUGE_PROCESSOR_PATH=
SAFEGAUGE_TOKENIZER_PATH=
SAFEGAUGE_DEVICE=cpu
SAFEGAUGE_TIMEOUT_SECONDS=120
```

当前任务路由为：FinVault → `financially_malicious_action`，系统提示词 → `system_prompt_leakage_intent`。每个任务再按 `qwen3-8b` / `qwen3-32b` 选择 checkpoint；只有不带任务的旧接口才回退到 `SAFEGAUGE_PROCESSOR_PATH`。

SafeGauge 返回的任务、标签、概率、阈值和原始响应会写入 `guard_results.safegauge`。当前框架仍采用检测对比模式，即风险命中只给出拦截建议，不会跳过 Agent Loop。

当统一 moderation 请求同时选择 `safegauge` 和 `inline_probing`，并且
`INLINE_PROBING_TASK` 与 SafeGauge task 一致时，后端会把两项检测融合为
一次 raw-token `/completions` prefill。该请求在原始上下文末尾捕获 activation，
同时读取后续固定 suffix 的 prompt logprobs；suffix 不会进入真实 Agent generation。

```json
{
  "text": "request to inspect",
  "guards": ["safegauge", "inline_probing"],
  "task": "system_prompt_leakage_intent",
  "model": "qwen3-8b"
}
```

如果任务不一致，后端不会融合，防止把间接提示词注入 checkpoint 当成泄露意图
checkpoint。若融合请求中的某一项失败，聊天路径只对失败项回退到原检测服务。
启用泄露意图融合时，需要部署与该任务配套的 inline checkpoint，并同时设置
`INLINE_PROBING_TASK=system_prompt_leakage_intent` 和对应的
`INLINE_PROBING_EXPECTED_CHECKPOINT_ID`。仓库提供了一个只验证 residual 捕获与
融合通路、固定输出 safe 的
[System Prompt Leakage holder recipe](../recipe/inline_probing/qwen3-8b-system-prompt-leakage-placeholder/README.md)；
它没有训练过，不能作为泄露检测器。仓库默认的真实 checkpoint 仍是
`indirect_prompt_injection`，不会被静默用于泄露任务。

## 基于隐藏层的可解释性技术

FinVault 和私有资产窃取场景选择基于隐藏层的可解释性技术时，推荐让 patched vLLM 在 GPU worker 内直接打分。现有 checkpoint 均为单层 residual probe；Qwen3-8B 客服 Agent 默认使用统一 theft probe，一次覆盖 System/Developer Prompt、私有 RAG、私有 CoT 与私有 Skill/tool 窃取意图。请求按 `model + scenario_category` 选择显式 `probe_id`，并校验 probe ID、checkpoint SHA-256、任务和层号。完整启动命令见 [Activation Probe vLLM recipe](../recipe/activation_probing/README.md)。

```dotenv
ACTIVATION_PROBE_BACKEND=vllm
# 留空时跟随聊天请求选择的 vLLM URL；固定部署也可填写完整 /v1 地址。
ACTIVATION_PROBE_VLLM_BASE_URL=http://127.0.0.1:8013/v1
ACTIVATION_PROBE_TIMEOUT_SECONDS=300
```

后端只读取 recipe 元数据并校验 checkpoint SHA-256，不加载 probe 参数，也不接收 raw hidden state。未应用仓库 overlay 的普通 vLLM 不提供 `inline_probing_request` / `inline_probing` 协议，不能用于此后端。

原来的独立 `backend.activation_probe_server` 仍可用作兼容或数值对照。它通过 `--model` 加载一个 Qwen3-8B 或 Qwen3-32B Transformers 实例，并使用对应 checkpoint：

- `results/activation_probe/finvault-qwen3-8b/best_probe.pt`
- `results/activation_probe/theft-unified-qwen3-8b-v16-multilayer-mlp/probe/best_probe.pt`（8B 默认）
- `results/activation_probe/prompt-extraction-qwen3-8b/probe/best_probe.pt`
- `results/activation_probe/finvault-qwen3-32b/best_probe.pt`
- `results/activation_probe/prompt-extraction-qwen3-32b/probe/best_probe.pt`

32B 启动示例：

```bash
CUDA_VISIBLE_DEVICES=5,6 \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python -m backend.activation_probe_server \
  --model qwen3-32b \
  --model-path .runtime/models/Qwen3-32B \
  --port 8910 --device-map balanced
```

8B 启动时改为：

```bash
CUDA_VISIBLE_DEVICES=5 \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python -m backend.activation_probe_server \
  --model qwen3-8b \
  --model-path .runtime/models/Qwen3-8B \
  --port 8910 --device-map auto
```

同一端口一次运行一种模型，所选模型应与前端 Agent 模型一致。

后端配置：

```dotenv
ACTIVATION_PROBE_BACKEND=standalone
ACTIVATION_PROBE_BASE_URL=http://127.0.0.1:8910
ACTIVATION_PROBE_TIMEOUT_SECONDS=300
```

## Inline Probing

选择 Inline Probing 时，Agent Loop 会在每批新工具返回后的第一个 assistant decision point 启用检测。完整 tool result、消息历史、工具定义和正常生成参数会一起发给同一个 patched vLLM OpenAI-compatible `/chat/completions` 服务，该次真实生成请求同时携带 `inline_probing_request`。同一个响应既返回 assistant 内容，也返回 `inline_probing` 结果；不再发送独立的 `max_tokens=1` probe 请求。

生产运行时不会预先知道 tool result 是否含有注入，因此会检测每个新 tool-result batch 后的首次决策。实验评估才根据冻结的 injection round index，只统计已知的注入轮次。如果本轮生成前没有新 tool result，返回状态为“未触发”。

ProspectMonitor 后端不接收 raw hidden states，也不加载 probe checkpoint；它只构造 typed request，并严格验证 result schema、status、checkpoint ID 和有限数值。

```dotenv
INLINE_PROBING_PROTOCOL=inline_probing
INLINE_PROBING_TASK=indirect_prompt_injection
INLINE_PROBING_PROBE_ID=qwen3-8b-indirect-prompt-injection-assistant-prefix-probing
INLINE_PROBING_EXPECTED_CHECKPOINT_ID=sha256:<probe-checkpoint-sha256>
INLINE_PROBING_THRESHOLD=0.5
INLINE_PROBING_TIMEOUT_SECONDS=120
```

该集成只使用 `inline_probing` 命名。如果 vLLM server 尚未暴露 `inline_probing_request` / `inline_probing`，需要先迁移 server patch 的 OpenAI protocol 字段。

融合 SafeGauge 时，patched vLLM 的 `/v1/completions` 还需支持同一个字段，
并允许请求通过 `target_token_index` 指定 suffix 之前的原始上下文边界。

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

默认使用公开模型 ID；也可以配置本地 snapshot：

```text
QWEN3_GUARD_BACKEND=auto
QWEN3_GUARD_MODEL=Qwen/Qwen3Guard-Gen-8B
```

`auto` 模式下，如果设置了 `QWEN3_GUARD_BASE_URL`，后端会优先调用独立 OpenAI-compatible guard 服务：

```bash
QWEN3_GUARD_BASE_URL=http://127.0.0.1:8001/v1 \
QWEN3_GUARD_MODEL=Qwen/Qwen3Guard-Gen-8B \
./start-perspective-watch.sh
```

也可以按官方方式单独启动 guard 服务：

```bash
vllm serve Qwen/Qwen3Guard-Gen-8B \
  --port 8001 \
  --max-model-len 32768
```

未设置 `QWEN3_GUARD_BASE_URL` 时，后端会懒加载本地 Transformers 模型。首次选择 Qwen3Guard 会加载 8B 模型，耗时和显存占用都比较高；演示环境更建议将 Qwen3Guard 作为独立 vLLM/SGLang 服务运行。

## 网易易盾文本安全护栏

选择“网易易盾文本安全护栏”时，后端会按文本单次同步检测接口，在本轮 query 进入 Agent Loop 前调用易盾文本检测。检测结果只写入 `guard_results.netease_yidun`，不拦截、不改写用户输入或模型输出。

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
NETEASE_YIDUN_API_URL=https://as.dun.163.com/v5/text/check
NETEASE_YIDUN_VERSION=v5.2
NETEASE_YIDUN_SIGNATURE_METHOD=
NETEASE_YIDUN_TIMEOUT_SECONDS=2
NETEASE_YIDUN_CHECK_LABELS=
```

未配置密钥时，选择“网易易盾文本安全护栏”会返回“未配置”，用于提示当前环境还没有接入真实账号。

## 方寸跃迁安全护栏

选择“方寸跃迁安全护栏”时，后端在模型调用前使用 Hook API 的
`POST https://guard.fangcunleap.com/v1/hook/scan-input` 检测用户消息，
请求使用 `Authorization: Bearer <FANGCUN_API_KEY>`。客户端同时提供
`scan_output`，用于在模型生成后调用
`POST https://guard.fangcunleap.com/v1/hook/scan-output`。
当前演示界面把输入检测作为观察信号展示；Hook API 的错误按默认
fail-open 处理，不会因为网络异常把业务模型强制拦截。

项目根目录 `.env` 或 `backend/.env` 均可配置：

```text
FANGCUN_API_KEY=your_api_key
FANGCUN_BASE_URL=https://guard.fangcunleap.com
FANGCUN_TIMEOUT_SECONDS=15
```

输入请求体为 `{"messages":[{"role":"user","content":"..."}],"stream":false}`；
Hook 返回顶层 `action`（例如 `allow` / `block`）和 `detection_result`。

## 运行

```bash
./start-perspective-watch.sh
```

当前 Qwen3-32B 演示默认连接：

```text
VLLM_BASE_URL=http://127.0.0.1:8978/v1
VLLM_MODEL=qwen3-32b
VLLM_API_KEY=EMPTY
```

如需修改：

```bash
VLLM_BASE_URL=http://127.0.0.1:8978/v1 VLLM_MODEL=qwen3-32b uvicorn backend.app:app --host 0.0.0.0 --port 18088
```

启动后访问：

```text
http://127.0.0.1:18088
```

前端点击“发送”会请求 `POST /api/chat`，后端会实际调用 vLLM 的 `/chat/completions`。
