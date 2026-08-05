# Perspective Watch

Perspective Watch 是一个面向金融 Agent 的安全审计与攻防演示系统。仓库包含可直接浏览的冻结审计结果、Case Study、FinVault 单轮回放，以及接入真实 Qwen/vLLM 和多种护栏的前后端代码。

模型路径、场景选型、端口规划、vLLM 启动命令和 API 调用示例见 [软件接入与使用说明](软件接入与使用说明.md)。

## 包含的能力

- 实验审计：FinVault 高风险任务、系统提示词泄露、间接提示词注入。
- 攻防演示台：Qwen3-8B/32B，支持流式输出与单轮 FinVault 录制回放。
- 护栏对比：Activation Probe、SafeGauge、Qwen3Guard、Llama Prompt Guard 2、网易易盾、XGuard，以及无防护基线。
- Case Study：用流程图对比无防护与有防护的 Agent 行为。

审计页和录制回放不要求 GPU 或外部模型服务。只有实时聊天、实时护栏判定和 Activation Probe 推理需要额外模型服务。

## 快速启动（审计与录制回放）

要求 Python 3.10 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp backend/.env.example backend/.env
./start-perspective-watch.sh
```

打开 `http://127.0.0.1:18088`。健康检查为：

```bash
curl http://127.0.0.1:18088/api/health
```

未启动 vLLM 时，健康接口会报告模型不可达，但审计页、Case Study 和 FinVault 录制回放仍可使用。

## 实时演示服务

### Qwen3-32B vLLM

SafeGauge 会复用该服务的 prefill logprobs，因此启动参数必须保留 `--max-logprobs 100`。

```bash
pip install -r requirements.txt
CUDA_VISIBLE_DEVICES=0,1,2,3 \
  MODEL=Qwen/Qwen3-32B \
  bash vllm_setups/run_vllm_qwen3_32b_tool.sh
```

所有启动参数都可以用环境变量覆盖，默认端口为 `8978`。

### Activation Probe

该服务按 `--model` 加载仓库内对应的 FinVault 与系统提示词 checkpoint。以下是 Qwen3-32B 示例：

```bash
CUDA_VISIBLE_DEVICES=0,1 \
  python -m backend.activation_probe_server \
  --model qwen3-32b \
  --model-path .runtime/models/Qwen3-32B \
  --device-map balanced \
  --port 8910
```

Qwen3-8B 使用 `--model qwen3-8b --model-path .runtime/models/Qwen3-8B`。`--model-path` 是显式运行参数；服务不会读取 checkpoint 中的训练机路径。模型权重属于部署依赖，不属于发布数据。普通 OpenAI-compatible vLLM API 不返回所需中间激活，不能替代该服务。

### 其他可选护栏

Qwen3Guard 可用 `vllm_setups/run_vllm_qwen3guard_8b.sh` 启动。Llama Prompt Guard 2 使用本地 Transformers 权重。网易易盾需要用户自己的账号凭证。完整变量见 `backend/.env.example`，真实 `.env` 不应提交。

间接提示词注入的 Inline Probing 需要应用仓库中 `recipe/inline_probing/` 的 vLLM 0.25.1 patch；该目录包含运行 patch、probe checkpoint 和说明，不含训练特征。

统一文本判定接口为 `POST /v1/moderations`。SafeGauge 请求可通过 `task` 选择 `financially_malicious_action`（默认）或 `system_prompt_leakage_intent`，并可通过 `model`、`vllm_port` 指向对应的 Qwen 服务。

## 数据与 checkpoint

运行版只保留下列数据：

- `results/audit_data/`：前端实验审计直接读取的冻结结果。
- `results/activation_probe/`：实时服务所需的 8B/32B × FinVault/提示词泄露四个 checkpoint，以及前端所需的评测摘要和预测。
- `results/suffix_probe/`：FinVault/提示词泄露 × Qwen3-8B/32B 的四个 SafeGauge checkpoint。
- `data/finvault/`、`data/system_prompt_extraction/`、`evaluations/`：审计接口和 Replay 读取的冻结输入。
- `case_studies/`：Case Study 页面读取的 PDF、轨迹和护栏结果。

详细映射和保留理由见 [ARTIFACTS.md](ARTIFACTS.md)。训练特征、训练集副本、处理脚本、实验迭代、日志和缓存均未包含。

## 项目结构

```text
backend/          FastAPI、Agent Loop、护栏客户端、Activation Probe 服务
frontend/         无构建步骤的 HTML/CSS/JavaScript 页面
data/             运行时读取的冻结输入
evaluations/      间接提示词注入审计输入
results/          前端审计结果与训练完成的 checkpoint
case_studies/     Case Study 的固定证据
recipe/           Inline Probing 的 vLLM patch 与 probe
vllm_setups/      当前支持模型的启动脚本
```

## 配置与安全

- 前端由 FastAPI 同源托管，不需要单独的前端服务器，也不应把 vLLM 暴露给浏览器。
- `backend/.env` 已从交付目录移除；只提交不含凭证的 `.env.example`。
- 默认 CORS 为 `*`，面向公网部署时请通过 `CORS_ALLOW_ORIGINS` 限制来源并在反向代理层增加认证。
- 本项目用于安全研究与授权评估，不应对未授权系统发起测试。

## 方法来源

- SafeGauge / Suffix Probe：[LeakDojo](https://github.com/yeasen-z/LeakDojo)
- Activation Probe：[Probing-leak-intents](https://github.com/jianshuod/Probing-leak-intents)
- Qwen3Guard：Qwen 团队公开模型
- Llama Prompt Guard 2：Meta 公开模型

## 发布前许可证

本副本没有擅自替项目所有者选择软件许可证。公开发布前必须添加明确的 `LICENSE`，并核对数据集、模型 checkpoint、PDF 示例和 vLLM patch 的再分发条款。
