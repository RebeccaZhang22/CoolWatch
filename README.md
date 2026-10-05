# ProspectMonitor

**面向大模型与 Agent 的通用可解释性安全检测与防护框架。**

ProspectMonitor 将模型隐藏层探针、输出概率信号和文本安全护栏接入同一套检测与展示流程，帮助开发者观察风险、比较检测方法，并在 Agent 执行过程中实施防护。当前提供有害内容、系统提示词泄露和间接提示词注入三类风险的探针，覆盖对话、RAG 检索和工具调用上下文。

业务场景通过系统提示词、知识库、工具定义和场景配置组织。你可以使用仓库中的航旅、金融示例，也可以替换为自己的业务资料和工具。FinVault 是其中一组评估基准；框架的接入入口是标准对话消息、工具定义和可配置的场景数据。

## 核心能力

- **可解释性检测**：通过 Activation Probe 读取模型隐藏层表征，通过 SafeGauge 分析概率信号，提供风险分数、阈值和检测证据。
- **运行时防护**：在 Agent 模型调用前检查上下文，结合工具与 RAG 返回内容持续检测，按启用的防护策略执行拦截。
- **多方法对照**：集成 Qwen3Guard、Llama Prompt Guard 2、网易易盾和方寸跃迁等护栏，在同一请求上比较检测结果。
- **可视化演示**：展示对话、检索结果、工具调用轨迹和防护状态，支持原始执行与防护执行的对照及已录制案例回放。
- **独立 API 与 SDK**：通过 HTTP、Python 或 TypeScript 将检测接入已有应用和 Agent。
- **训练与评估**：提供数据准备、激活提取、探针训练和评估代码，支持围绕目标场景准备样本、训练探针和调整阈值。

## 工作方式

业务模型负责对话与工具决策，检测服务负责风险判断，应用根据检测结果控制后续执行。当前 Probe Bank 通过独立的检测模型服务提取特征并运行多个风险探针。

```text
用户消息 + 对话历史 + 工具定义
                │
                ▼
          上下文安全检测 ── 风险命中 ──► 拦截与记录
                │
              检测通过
                ▼
          业务模型与 Agent
                │
         ┌──────┴──────┐
         ▼             ▼
    RAG / 工具调用   最终答复
         │
         └── 结果加入上下文，进入下一轮检测
```

控制台与审计接口呈现检测分数、触发阶段和执行轨迹。业务场景、检测方法和模型服务分别配置；扩展模型侧检测时，需要配套的特征提取实现、探针权重和目标数据评估。

## 快速开始

### 1. 安装与启动控制台

使用 Python 3.10 或更高版本，在仓库根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp backend/.env.example backend/.env
```

在 `backend/.env` 中填写模型服务地址和相关凭证，然后启动：

```bash
bash vllm_setups/run_agent_backend.sh
```

访问 <http://127.0.0.1:18088>。检查服务状态：

```bash
curl http://127.0.0.1:18088/api/health
```

前端 HTML、CSS 和 JavaScript 由 FastAPI 同源托管。实时对话使用业务模型服务，可解释性检测使用 Probe Bank 或对应的检测服务，录制回放使用仓库中的案例数据。

### 2. 配置模型与检测服务

以下配置对应当前 Qwen3-8B 示例部署，可在 `backend/.env` 中按环境调整：

```dotenv
CUSTOMER_AGENT_BUSINESS_VLLM_BASE_URL=http://127.0.0.1:8104/v1
CUSTOMER_AGENT_MODEL=qwen3-8b
CUSTOMER_AGENT_SHADOW_VLLM_BASE_URL=http://127.0.0.1:8302/v1
CUSTOMER_AGENT_SHADOW_MODEL=qwen3-8b
CUSTOMER_AGENT_ENABLE_RUNTIME_PROBES=true
ACTIVATION_PROBE_BACKEND=probe_bank
PROBE_BANK_BASE_URL=http://127.0.0.1:8302
```

业务模型接入 OpenAI-compatible 服务。Probe Bank 启动入口为：

```bash
PROBE_SOURCE_ROOT=/path/to/probe-runtime \
PROBE_PYTHON=/path/to/probe-runtime/.venv-sglang/bin/python \
PROBE_MODEL_PATH=/path/to/Qwen3-8B \
CUDA_VISIBLE_DEVICES=0 \
bash vllm_setups/run_probe_bank_qwen3_8b.sh
```

将上述路径替换为已准备好的 Probe 运行环境与模型目录。启动脚本使用配套 SGLang 运行环境，默认加载 `probe/qwen3-8b/` 中的三类探针权重。部署参数见[启动脚本](vllm_setups/run_probe_bank_qwen3_8b.sh)，探针训练与数据处理见[训练代码说明](probe/src/README.md)。

其他护栏的服务地址、模型与凭证统一在[配置模板](backend/.env.example)中设置。

## 使用自己的业务场景

当前默认场景为[航旅客服](data/hanglvzongheng/README.md)，仓库同时提供[金融场景资料](data/financial_agent/README.md)。通过 `CUSTOMER_AGENT_DATA_ROOT` 指定场景目录：

```bash
CUSTOMER_AGENT_DATA_ROOT="$PWD/data/financial_agent" \
bash vllm_setups/run_agent_backend.sh
```

自定义场景可以从现有目录复制并调整，主要配置如下：

| 配置 | 用途 |
| --- | --- |
| `scenario.json` | 场景名称、模型配置、启用的护栏，以及各类资源的路径 |
| 系统提示词文件 | Agent 的角色、业务规则和回答方式 |
| `rag/documents.json` 与知识文档 | 检索资料、文档元数据和可见性标记 |
| `tools/definitions.json` | 工具名称、说明和参数结构 |
| `conversation_starters.json` | 控制台中的示例问题 |

修改场景文件后重启后端即可加载。系统提示词路径由 `scenario.json` 的 `agent.system_prompt_path` 指定；知识库和工具路径也由同一文件管理。

业务工具由后端执行器处理。接入新的工具类型时，同步扩展[场景加载器](backend/customer_agent_catalog.py)中的工具声明和[Agent 执行器](backend/customer_agent.py)中的调用逻辑。现有演示工具采用本地检索、沙盒或模型生成的模拟业务响应，实际业务系统可以通过对应工具适配接入。

如果已有自己的 Agent，可以直接使用检测 SDK，在原有执行流程中提交上下文并处理检测结果。

## SDK 接入

在仓库根目录安装 Python SDK：

```bash
pip install .
```

将访问令牌设置为 `SILICONPROSPECT_API_KEY` 环境变量，并使用部署后的服务地址：

```python
from siliconprospect_guard import SiliconProspectGuard

messages = [
    {"role": "system", "content": "你是企业知识助手，依据授权资料回答问题。"},
    {"role": "user", "content": "请介绍差旅报销流程。"},
]

with SiliconProspectGuard(base_url="http://127.0.0.1:18088") as client:
    result = client.moderations.create(messages=messages)
    print(result.action)
    print(result.per_risk)

    if result.action == "block":
        raise RuntimeError(f"请求已拦截：{result.request_id}")

    # 检测通过后，在这里继续业务模型调用。
```

SDK 调用 `/v1/moderations`，支持通过 `tools` 参数传入工具定义。每次将工具或 RAG 结果加入消息历史后，可以再次检测完整上下文。返回结果包含 `pass` / `block`、各风险的分数与阈值、触发条目、请求标识和耗时，由调用方执行对应的防护策略。

详细用法见 [Python SDK](siliconprospect_guard/README.md) 和 [TypeScript SDK](sdk/typescript/README.md)。

## 数据、训练与评估

| 目录 | 内容 |
| --- | --- |
| `data/` | 业务场景配置、系统提示词、RAG 资料和回放场景 |
| `train/data/` | 按风险分类的训练、验证样本和来源清单 |
| `probe/src/` | 数据准备、激活提取和探针训练代码 |
| `probe/qwen3-8b/` | 当前 Qwen3-8B 检测服务使用的探针权重 |
| `evaluation/dataset/` | 自建场景数据与 FinVault 等评估基准 |
| `evaluation/src/` | 评估、打分与报告生成脚本 |
| `evaluation/results/` | 评估记录、逐条预测和审计资料 |
| `evaluation/aviation_demo/` | 航旅演示的复现、发布脚本与回放记录 |
| `results/` | 已保存的探针权重、指标和预测结果 |
| `frontend/data/`、`frontend/assets/` | 页面使用的演示数据与静态素材 |

训练入口见[训练说明](train/README.md)，样本构成与来源见[数据说明](train/data/README.md)，评估流程见[评估说明](evaluation/README.md)。迁移到新的场景时，可围绕目标业务整理正常与攻击样本，通过独立评估集验证检测效果，再配置适合该场景的探针和阈值。

## 代码结构

```text
backend/                 API、Agent 执行、场景加载和检测服务
frontend/                控制台、审计页面、案例展示与接入文档
siliconprospect_guard/    Python SDK
sdk/typescript/          TypeScript SDK
vllm_setups/             后端与模型服务启动入口
```

配置凭证保存在本地 `backend/.env`，版本库中的 `.env.example` 提供配置模板。对外部署时，通过 `CORS_ALLOW_ORIGINS` 设置访问来源，并在服务入口配置认证与访问控制。

## 方法与参考

- SafeGauge：[LeakDojo](https://github.com/yeasen-z/LeakDojo)、[SafeGauge](https://github.com/yeasen-z/SafeGauge)
- Activation Probe：[Probing-leak-intents](https://github.com/jianshuod/Probing-leak-intents)
- Qwen3Guard：Qwen 系列安全检测模型
- Llama Prompt Guard 2：Meta 提示词注入检测模型
