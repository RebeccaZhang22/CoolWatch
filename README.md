# ProspectMonitor

ProspectMonitor 是一个 Agent 安全审计与攻防演示系统。首页围绕一个真实可对话的商城客服 Agent 展示运行时防护，仓库同时保留冻结审计结果、Case Study、FinVault 单轮回放，以及接入真实 Qwen/vLLM 和多种护栏的代码。

模型路径、场景选型、端口规划、vLLM 启动命令和 API 调用示例见 [软件接入与使用说明](软件接入与使用说明.md)。

## 包含的能力

- 实验审计：FinVault 高风险任务、系统提示词泄露、间接提示词注入。
- 攻防演示台：单一 Qwen3-8B reasoning 客服 Agent，支持真实工具调用、RAG、逐阶段轨迹和同消息防护对照。
- 护栏对比：Activation Probe、SafeGauge、Qwen3Guard、Llama Prompt Guard 2、网易易盾、XGuard，以及无防护基线。
- 竞品资料：[护栏竞品对比与接入分析](竞品护栏对比与接入分析.md)，梳理输入输出、产品形态、部署方式和本项目接入边界。
- Case Study：用流程图对比无防护与有防护的 Agent 行为。

审计页和录制回放不要求 GPU 或外部模型服务。只有实时聊天、实时护栏判定和 Activation Probe 推理需要额外模型服务。

## 统一客服 Agent 攻防 API

`/api/customer-agent/*` 与首页把实时演示收束为一个 Qwen3-8B reasoning 客服 Agent。用户直接发送自然消息，模型自行决定是否调用订单或知识库工具；右侧面板展示输入、上下文、生成和输出阶段的防护结果，并可对同一条消息运行 baseline/defended 对照。一键模型与后端启动命令、API 示例和安全边界见 [统一客服 Agent 后端](backend/CUSTOMER_AGENT.md)。

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

当前三个风险类别由 Probe Bank 加载 `probe/qwen3-8b/` 下的权重。启动：

```bash
./vllm_setups/run_probe_bank_qwen3_8b.sh
```

后端配置为 `ACTIVATION_PROBE_BACKEND=probe_bank` 和 `PROBE_BANK_BASE_URL=http://127.0.0.1:8302`。训练代码在 `probe/src/`。独立 Transformers 后端 `standalone` 仍保留用于旧部署对照。

### 其他可选护栏

Qwen3Guard 可用 `vllm_setups/run_vllm_qwen3guard_8b.sh` 启动。Llama Prompt Guard 2 使用本地 Transformers 权重。网易易盾需要用户自己的账号凭证。完整变量见 `backend/.env.example`，真实 `.env` 不应提交。

旧版 patched-vLLM 的补丁、占位权重及启动入口已移除。Inline Probing 协议客户端仅用于外部兼容服务，仓库不再提供配套服务安装包。

## 数据与 checkpoint

运行版只保留下列数据：

- `evaluation/results/audit_data/`：前端实验审计直接读取的冻结结果。
- `results/activation_probe/`：实时服务所需的 8B/32B × FinVault/提示词泄露四个 checkpoint，以及前端所需的评测摘要和预测。
- `results/gauge_probe/`：FinVault/提示词泄露 × Qwen3-8B/32B 的四个 SafeGauge checkpoint。
- `data/`：金融问答与注入回放场景。
- `train/data/`：按风险划分的训练/验证数据。
- `evaluation/dataset/`：自建场景测试与基准，详见 [评估说明](evaluation/README.md)。
- `evaluation/src/`、`evaluation/results/`：judge 脚本与审计结果。
- `case_studies/`：Case Study 页面读取的 PDF、轨迹和护栏结果。

详细映射和保留理由见 [ARTIFACTS.md](ARTIFACTS.md)。历史特征和缓存保留在 `.runtime/`；当前数据入口见上述目录。

## 项目结构

```text
backend/          FastAPI、Agent Loop、护栏客户端、Activation Probe 服务
frontend/         无构建步骤的 HTML/CSS/JavaScript 页面
data/             运行时场景数据
train/            训练和验证数据
probe/            线上权重与 src/ 训练代码
evaluation/       测试数据、judge 脚本和审计结果
results/          前端审计结果与训练完成的 checkpoint
case_studies/     Case Study 的固定证据
vllm_setups/      当前支持模型的启动脚本
```

## 配置与安全

- 前端由 FastAPI 同源托管，不需要单独的前端服务器，也不应把 vLLM 暴露给浏览器。
- `backend/.env` 已从交付目录移除；只提交不含凭证的 `.env.example`。
- 默认 CORS 为 `*`，面向公网部署时请通过 `CORS_ALLOW_ORIGINS` 限制来源并在反向代理层增加认证。
- 本项目用于安全研究与授权评估，不应对未授权系统发起测试。

## 方法来源

- SafeGauge：[LeakDojo](https://github.com/yeasen-z/LeakDojo), [SafeGauge](https://github.com/yeasen-z/SafeGauge)
- Activation Probe：[Probing-leak-intents](https://github.com/jianshuod/Probing-leak-intents)
- Qwen3Guard：Qwen 团队公开模型
- Llama Prompt Guard 2：Meta 公开模型

## 发布前许可证

本副本没有擅自替项目所有者选择软件许可证。公开发布前必须添加明确的 `LICENSE`，并核对数据集、模型 checkpoint、PDF 示例和 vLLM patch 的再分发条款。
