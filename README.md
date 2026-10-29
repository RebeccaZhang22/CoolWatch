# ProspectMonitor

**面向大模型与 Agent 的通用可解释性安全检测与防护框架。**

ProspectMonitor（CoolWatch）将模型隐藏层探针、输出概率信号和文本安全护栏接入同一套检测与展示流程，帮助开发者观察风险、比较检测方法，并在 Agent 执行过程中实施防护。仓库提供有害内容、系统提示词泄露和间接提示词注入三类风险的探针，覆盖对话、RAG 检索和工具调用上下文；当前默认仅启用间接提示词注入（IPI）探针，其他两类可通过部署配置启用。

业务场景通过系统提示词、知识库、工具定义和场景配置组织。你可以使用仓库中的航旅、HR 招聘和金融示例，也可以替换为自己的业务资料和工具。FinVault 是其中一组评估基准；框架的接入入口是标准对话消息、工具定义和可配置的场景数据。

## 产品形态：演示台与管理者控制台

产品由两个面向不同使用者的 Web 界面组成，共用演示产生的活动数据，分别使用普通用户和管理者身份。

| | 演示台 | 管理者控制台 |
| --- | --- | --- |
| 面向谁 | 体验产品的用户、开发者与演示人员 | 负责演示运营、用户跟进与风险审计的团队 |
| 主要任务 | 运行 Agent，观察攻击、防护与工具执行过程 | 查看谁在使用、体验了什么、触发了哪些风险，并记录跟进意向 |
| 核心界面 | 场景与 Agent 配置、聊天、实时 Agent Loop、工具/RAG 轨迹、检测详情与防护对照 | 用户列表、活跃与试用统计、操作时间线、请求详情、风险筛选、意向标签与备注 |
| 默认入口 | `http://127.0.0.1:18088/` | `http://127.0.0.1:18089/manager/` |
| 登录方式 | 普通用户注册/登录；开发者中心提供 CLI/API Token | 独立创建的管理者账号与会话 |
| 代码位置 | [`frontend/`](frontend/README.md) + [`backend/`](backend/README.md) | [`manager/`](manager/README.md) |

**演示台**以实际 Agent 运行为中心：左侧切换航旅客服或 HR 简历筛选场景，配置模型、系统提示词、知识库、工具和防护方法；中央聊天区支持资料附件和多轮交互；执行流程显示每轮生成前检测、模型生成与环境工具执行，详情抽屉展示检测证据和工具结果。可以对同一任务比较无防护与有防护的执行，也可以查看已录制的审计案例。HR 场景包含合成简历、PDF 白字注入、测评材料注入和本地候选人档案，详见 [HR 演示说明](data/hr_agent/README.md)。

**管理者控制台**围绕用户的体验过程组织信息：查看注册用户、最近活跃、试用次数和风险请求，按用户打开时间线，进一步查看请求 JSON、模型答复、工具调用、检测器、风险分数及拦截状态。团队可以手动标记“待判断 / 待跟进 / 暂无意向”并添加备注。它可以作为轻量服务独立启动，不加载模型，也不需要 GPU；演示服务同时保留 `/manager/` 和旧 `/admin.html` 的兼容入口。

演示服务负责采集浏览器操作和服务端请求，管理端读取相同的活动数据库及普通用户账号元数据。普通用户账号、CLI Token 和历史 admin 角色不会授予管理权限。活动记录从启用采集后开始积累，未采集的历史交互无法回溯；已发送的提示词、模型响应和工具结果会进入请求详情，凭证字段按规则脱敏。部署时两个进程应使用相同的 `MANAGER_DATA_DIR`，具体数据范围见[管理中心说明](manager/README.md)。

## 核心能力

- **可解释性检测**：通过 Activation Probe 读取模型隐藏层表征，通过 SafeGauge 分析概率信号，提供风险分数、阈值和检测证据。
- **运行时防护**：在 Agent 模型调用前检查上下文，结合工具与 RAG 返回内容持续检测，按启用的防护策略执行拦截。
- **多方法对照**：集成 Qwen3Guard、Llama Prompt Guard 2、网易易盾和方寸跃迁等护栏，在同一请求上比较检测结果。
- **可视化演示**：展示对话、检索结果、工具调用轨迹和防护状态，支持原始执行与防护执行的对照及已录制案例回放。
- **用户运营与审计**：独立管理者控制台串联用户、浏览器操作、模型请求和风险事件，支持筛选、分页及人工跟进标记。
- **独立检测 API**：通过 HTTP 将检测接入已有应用和 Agent，也可配合单独获取的 SDK 使用。
- **训练与评估**：提供数据准备、激活提取、探针训练和评估代码，支持围绕目标场景准备样本、训练探针和调整阈值。

## 工作方式

业务模型负责对话与工具决策，检测服务负责风险判断，应用根据检测结果控制后续执行。Probe Bank 通过独立的检测模型服务提取特征并运行已启用的风险探针。

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

演示台呈现当轮检测分数、触发阶段和执行轨迹，管理者控制台汇总已采集的用户活动与请求记录。业务场景、检测方法和模型服务分别配置；扩展模型侧检测时，需要配套的特征提取实现、探针权重和目标数据评估。

## 快速开始

### 1. 安装与启动演示台

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

访问 <http://127.0.0.1:18088>，注册或登录普通用户账号后进入演示台。检查服务状态：

```bash
curl http://127.0.0.1:18088/api/health
```

前端 HTML、CSS 和 JavaScript 由 FastAPI 同源托管。实时对话使用业务模型服务，可解释性检测使用 Probe Bank 或对应的检测服务，录制回放使用仓库中的案例数据。

### 2. 启动管理者控制台

在仓库根目录创建独立管理者账号，按提示输入密码，然后启动管理服务：

```bash
python -m manager.auth --email owner@example.com
bash manager/start.sh
```

访问 <http://127.0.0.1:18089/manager/> 并使用刚创建的账号登录。管理端默认没有固定账号或密码；`GET http://127.0.0.1:18089/health` 可检查就绪状态。

如果只运行管理端，可以在单独的虚拟环境中安装 `manager/requirements.txt`，通过 `MANAGER_PYTHON=/path/to/python bash manager/start.sh` 指定解释器，无需安装模型依赖。管理配置模板为 [`manager/.env.example`](manager/.env.example)，与 `backend/.env` 分开；演示服务启动后会将新活动写入共享数据目录，管理端无需重启即可查看。完整部署、账号和统计说明见 [`manager/README.md`](manager/README.md)。

### 3. 配置模型与检测服务

以下配置对应当前 Qwen3-8B 示例部署，可在 `backend/.env` 中按环境调整：

```dotenv
CUSTOMER_AGENT_BUSINESS_VLLM_BASE_URL=http://127.0.0.1:8104/v1
CUSTOMER_AGENT_MODEL=qwen3-8b
CUSTOMER_AGENT_SHADOW_VLLM_BASE_URL=http://127.0.0.1:8302/v1
CUSTOMER_AGENT_SHADOW_MODEL=qwen3-8b
CUSTOMER_AGENT_ENABLE_RUNTIME_PROBES=true
ACTIVATION_PROBE_BACKEND=probe_bank
PROBE_BANK_ENABLED_RISKS=ipi
PROBE_BANK_BASE_URL=http://127.0.0.1:8302
PROBE_BANK_API_KEY=<与该服务的 INSCOPE_API_KEY 相同>
```

**当前部署约定是一个检测服务实例只负责一类风险。** 这是 Coolwatch 的接法，不是 inscope-service 的能力上限：外部服务可以在一个进程里加载多类探针，本仓库不使用那条路径。启用多种风险时，为每类风险各起一个实例，并按风险声明地址；只配置 `PROBE_BANK_BASE_URL` 却启用多类风险会直接拒绝启动。检测前还会核对实例 `/info` 声明的风险，地址配到了别的风险上会失败关闭，而不是把那一类的分数标成这一类：

```dotenv
PROBE_BANK_ENABLED_RISKS=harmful,prompt_leakage,ipi
PROBE_BANK_RISK_ENDPOINTS=harmful=http://127.0.0.1:8301,prompt_leakage=http://127.0.0.1:8303,ipi=http://127.0.0.1:8302
```

`/v1/moderations` 返回每风险分数与 `per_risk_detail` 解释信息；当检测服务启用块级解释时，`per_risk_detail[risk].blocks` 会包含区块证据及其来源消息序号。应用仍返回当前客户端所需的 `detector_model`、`per_risk`、`per_entry`、`triggered_entries` 和 `latency_ms` 字段。

后端并发调用各实例，再把结果合并成统一的 `per_risk`（每类风险一项 `score` / `threshold` / `flagged`）。任一已启用风险的实例不可用时整体返回错误，不会把其余风险算作通过；`disabled_risks` 只表示未启用，不代表检测通过。

防护模式（`defense_mode=defended`）不会静默降级：请求的方法当前不可用、或检测服务返回错误时，本轮业务执行直接拒绝/暂停，而不是退回无检测继续生成。需要无防护对照时请显式使用 `baseline`。`ACTIVATION_PROBE_BACKEND` 只接受 `probe_bank` 或 `standalone`，旧版 `vllm` 取值会在启动时被拒绝。演示台的 `GET /api/health` 会单独报告探针状态（`probe_bank_reachable` / `probe_bank_enabled_risks`），业务模型可用但探针不可用时前端显示“检测服务未就绪”。

业务模型接入 OpenAI-compatible 服务。InsScope Detect 的检测服务是仓库外的 inscope-service，Coolwatch 只通过 `PROBE_BANK_BASE_URL` / `PROBE_BANK_RISK_ENDPOINTS` 调用它。

仓库里还留着两套旧的仓内检测实现（`sglang-activation-runtime/` + `backend/activation_probe_server.py`，以及 `probe-runtime/` + `backend/qwen3_probe_bank_server.py`）。它们提供 `/bank` 和 `per_risk`，**不满足当前适配器要求的 `/info` 风险身份和顶层 `probability`**，不能当作 inscope-service 的替代部署。需要对照旧实验时再单独看对应目录，不要和上面的 Web 启动混用。兼容方案的历史入口为：

```bash
PROBE_SOURCE_ROOT=/path/to/probe-runtime \
PROBE_PYTHON=/path/to/probe-runtime/.venv-sglang/bin/python \
PROBE_MODEL_PATH=/path/to/Qwen3-8B \
CUDA_VISIBLE_DEVICES=0 \
bash vllm_setups/run_probe_bank_qwen3_8b.sh
```

上面这段只保留给旧实验对照，**不要用它启动当前 Web 后端所调用的检测服务**。当前检测服务在仓库外单独部署；Web 后端和各实例的风险配置必须一致，改完分别重启。响应中的 `enabled_risks` / `disabled_risks` 表明实际启用范围，未启用不代表检测通过。

其他护栏的服务地址、模型与凭证统一在[配置模板](backend/.env.example)中设置。

### 4. 持久部署

当前持久部署只需要业务模型、仓库外的 inscope-service，以及本仓库的 Web 后端。`sglang-activation-runtime/deploy/` 和 `deploy/` 里的 probe unit 启动的是上一节所说的旧仓内检测服务，不能接到现在的 `PROBE_BANK_*` 配置上。配置文件中的用户、绝对路径、GPU 和端口需要按目标服务器调整；版本库中的 unit 文件本身不代表服务已安装或启用。

管理者控制台通过 `manager/start.sh` 独立启动；如需长期运行，可按同样方式交给进程管理器。账户数据库、HR 演示状态、日志、模型缓存与本地 `.env` 均不提交到 GitHub。

## 使用自己的业务场景

演示台默认进入[航旅客服](data/hanglvzongheng/README.md)，可在左侧场景选择器切换到 [HR 简历筛选](data/hr_agent/README.md)，也可直接访问 `/index.html?scenario=hr`。切换会建立新会话，不修改服务器的默认场景。仓库还提供[金融场景资料](data/financial_agent/README.md)，可通过 `CUSTOMER_AGENT_DATA_ROOT` 指定场景目录：

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

如果已有自己的 Agent，可以直接调用检测 API，在原有执行流程中提交上下文并处理检测结果。

## API 接入

从演示台开发者中心获取 API Token，将其设置为 `SILICONPROSPECT_API_KEY` 环境变量，并使用部署后的服务地址：

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:18088/v1/moderations \
  -H "Authorization: Bearer $SILICONPROSPECT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"system","content":"你是企业知识助手，依据授权资料回答问题。"},{"role":"user","content":"请介绍差旅报销流程。"}]}'
```

`/v1/moderations` 支持通过 `tools` 参数传入工具定义。每次将工具或 RAG 结果加入消息历史后，可以再次检测完整上下文。返回结果包含 `pass` / `block`、各风险的分数与阈值、触发条目、请求标识和耗时；调用方在返回 `block` 时停止执行，在检测通过后继续业务模型调用。

Python 和 TypeScript SDK 源码不随此仓库发布，需单独获取；仅调用 HTTP API 不依赖 SDK。

## 本次更新

- **独立管理者控制台**：新增 `manager/`，提供独立认证、用户活动统计、请求与风险详情、意向备注；演示台加入浏览器打点和服务端采集。
- **HR 演示与资料附件**：新增简历筛选场景、内置文件选择器、PDF/文本资料读取、简历检索排序及候选人档案持久化。
- **实时执行过程**：Agent Loop 展示多轮模型与工具执行、每轮生成前检测和拦截位置，增加等待心跳、断连清理与更明确的服务异常提示。
- **模型运行与评估**：纳入两套 SGLang 探针运行代码、systemd 部署示例及 [Qwen3Guard held-out 评估脚本](evaluation/src/run_qwen3guard_heldout.py)。已保存的[评估报告](evaluation/results/qwen3guard-heldout-20261012/REPORT.md)是部分运行快照，完整度以报告中的样本覆盖数为准。

## 数据、训练与评估

| 目录 | 内容 |
| --- | --- |
| `data/` | 业务场景配置、系统提示词、RAG 资料和回放场景 |
| `probe/src/` | 数据准备、激活提取和探针训练代码 |
| `probe/qwen3-8b/` | 当前 Qwen3-8B 检测服务使用的探针权重 |
| `evaluation/dataset/` | 自建场景数据与 FinVault 等评估基准 |
| `evaluation/src/` | 评估、打分与报告生成脚本 |
| `evaluation/results/` | 评估记录、逐条预测和审计资料 |
| `evaluation/aviation_demo/` | 航旅演示的复现、发布脚本与回放记录 |
| `results/` | 已保存的探针权重、指标和预测结果 |
| `frontend/data/`、`frontend/assets/` | 页面使用的演示数据与静态素材 |

探针训练代码见[代码说明](probe/src/README.md)，评估流程见[评估说明](evaluation/README.md)。`train/` 中的训练资产不随此仓库发布，运行依赖这些数据的脚本前需另行准备。迁移到新的场景时，可围绕目标业务整理正常与攻击样本，通过独立评估集验证检测效果，再配置适合该场景的探针和阈值。

## 代码结构

```text
backend/                 演示 API、Agent 执行、场景加载和检测服务
frontend/                演示台、审计页面、案例展示与开发者中心
manager/                 独立管理者控制台、认证、活动采集与统计
data/hr_agent/           HR 演示场景、合成简历与工具配置
probe-runtime/           原有 SGLang 特征提取运行时
sglang-activation-runtime/ 按请求采集隐藏状态的 SGLang 补丁与部署
deploy/                  原有服务的 systemd 部署示例
vllm_setups/             后端与模型服务启动入口
```

配置凭证保存在本地 `backend/.env`，版本库中的 `.env.example` 提供配置模板。对外部署时，通过 `CORS_ALLOW_ORIGINS` 设置访问来源，并在服务入口配置认证与访问控制。

## 方法与参考

- SafeGauge：[LeakDojo](https://github.com/yeasen-z/LeakDojo)、[SafeGauge](https://github.com/yeasen-z/SafeGauge)
- Activation Probe：[Probing-leak-intents](https://github.com/jianshuod/Probing-leak-intents)
- Qwen3Guard：Qwen 系列安全检测模型
- Llama Prompt Guard 2：Meta 提示词注入检测模型
