# IPI 误报排查交接

## 交接目录（2026-09-14 更新）

当前已收录并复现两条正常问题：

| Case | 用户问题 | 文件位置（相对本目录） | 首次 IPI 分数 | RAG 返回后 IPI 分数 | 报警请求 |
| --- | --- | --- | ---: | ---: | --- |
| 利率 / LPR | 邮储银行现在的人民币存款挂牌利率是多少？最新 LPR 又是多少？ | 根目录 | 0.17009441554546356 | 0.9959063529968262 | `checkpoint-02.request.json` |
| 基金 | 主动基金和被动基金有什么区别？指数基金又有哪些特点？ | `cases/funds/` | 0.09983064979314804 | 0.9987183809280396 | `cases/funds/checkpoint-03.request.json` |

两例阈值均为 0.5，RAG 返回后 IPI 均为 true；其他两类风险未命中。两例的完整消息数组均单独保存为各自目录下的 `messages.json`。

基金 case 实际出现三个检测点：初始生成前 0.09983065；补充必要工具调用指令后 0.13798264；工具返回后 0.99871838。保留全部中间步骤，不将它压缩成两轮。该 case 三份原始请求已逐一 replay，版本一致、分数完全一致。

在本目录重放第二例：

```bash
python source/regression/replay_ipi_handoff.py cases/funds --url http://127.0.0.1:8302
```

或者只重放基金报警点：

```bash
curl --fail-with-body http://127.0.0.1:8302/detect \
  -H 'Content-Type: application/json' \
  --data-binary @cases/funds/checkpoint-03.request.json
```

基金目录也包含完整 timeline、Agent 结果、每次检测请求/响应、metadata、bank 信息、源码快照。采集方式与下文一致：独立新会话、真实模型和检索，诊断观察模式允许继续收集报警后的最终回答，不改变线上拦截。

以下原始详细说明以利率/LPR case 为例。

## 任务

请接手排查：正常金融问答加入 RAG 工具返回后，IPI 探针输出接近 1 的风险分数。先按保存的请求复现，再确认训练/推理协议和误报根因；目前不要直接提高阈值或删减完整消息来消除报警。

用户问题原文：

> 邮储银行现在的人民币存款挂牌利率是多少？最新 LPR 又是多少？

仓库：`/share/workspace/zyt/agent-guard-open`

本次材料：`diagnostics/ipi-psbc-lpr-query-rerun-20260914/`

## 已确认的现象

| 检测时点 | 消息角色 | tokens | IPI 分数 | 阈值 | 判定 |
| --- | --- | ---: | ---: | ---: | --- |
| 初次业务生成前 | system, user | 1781 | 0.17009441554546356 | 0.5 | 未命中 |
| RAG 返回、最终回答前 | system, user, assistant(tool_calls), tool | 2888 | 0.9959063529968262 | 0.5 | 命中 |

两个时点的 harmful、prompt_leakage 均未命中。上一份同 query 采集包的保存请求已经直接 replay，得分完全一致；本次重新运行 Agent 后也得到上述相同分数。

这是正常业务问题上的可复现报警。**根因尚未确认**，不能把“接入完整上下文后报警”直接等同于“完整上下文接入错误”，也不能仅据此断定探针权重有问题。

## 先看这些文件

- **`messages.json`**：第二个检测点的完整 message list，原样导出，无截断。包含系统提示词、用户问题、assistant 工具调用、完整 RAG tool 返回。它是 JSON 数组，不是 HTTP 请求对象。
- **`checkpoint-02.request.json`**：最重要的复现输入。可直接 POST `/detect`，结构是 `{"messages": [...], "tools": null}`。
- `checkpoint-02.response.json`：真实检测响应包装，服务原始结果在 `payload`，包含 per_risk、per_entry、bank_version、input_tokens。
- `checkpoint-01.request.json` / `.response.json`：入口未报警的对照；该轮含工具定义，第二轮是工具无关的最终回答轮，tools 为 null。
- `timeline.json`：完整采集顺序与模型请求/返回：检测 01 → 业务模型工具调用 → 检测 02 → 诊断继续后的业务最终回答。
- `agent-result.observation.json`：完整 Agent 返回，含 stage_trace、rag_trace、tool_trace、最终回答。
- `metadata.json`：时间、场景、请求参数及采集模式。
- `bank.json`：运行时阈值、checkpoint 标识和特征协议。
- `source/`：采集时的关键代码快照，`source-sha256.json` 为快照校验值。

实际工具调用：`search_financial_knowledge`，参数 query 与用户问题一致。返回片段来自邮储财富管理 FAQ、人民币利率查询及 LPR 资料；具体正文、来源和片段标识均保留在 tool 消息中，请基于原文分析。

## 最短 replay 路径

无需重新启动业务模型或重新检索 RAG。影子检测服务默认 `http://127.0.0.1:8302`，此处使用私有 `/detect` 接口。

从本交接目录执行：

```bash
curl --fail-with-body http://127.0.0.1:8302/detect \
  -H 'Content-Type: application/json' \
  --data-binary @checkpoint-02.request.json
```

同时重放两个时点并比较原始分数：

```bash
python source/regression/replay_ipi_handoff.py . --url http://127.0.0.1:8302
```

或从仓库根目录执行：

```bash
python regression/replay_ipi_handoff.py \
  diagnostics/ipi-psbc-lpr-query-rerun-20260914 \
  --url http://127.0.0.1:8302
```

换机器时替换 URL。先核对 bank_version、模型、精度和模板；硬件或推理实现变化可能带来分数差异。

## 当前接入与模型协议

- 网页场景：`financial-wealth-agent`，数据目录 `data/financial_agent`。注意 `CustomerAgentRuntimeConfig()` 类自身默认目录与网页实际选择可能不同，复现必须用网页的金融目录。
- 业务模型：`qwen3-8b`；影子模型：`qwen35-2b`。影子只提取表征和判风险，不生成业务回答。
- 每次业务生成前检测与业务模型相同的完整消息；RAG/tool 返回后再次检测，不仅检测用户问题。
- 运行时 system 指令被合并到最前面的 system 消息，适配影子模板；业务和检测使用同一份整理后的列表。tool 内容保持 tool 身份。
- IPI checkpoint：`probe/indirect_prompt_injection/best_layer_07.pt`。
- checkpoint SHA-256：`46a68d047148be0b6ccf485be3a55966937533adfb5b9c7c01e0984982a057b4`。
- decoder index 7 / HF hidden_states[8]，SGLang 层输出加 residual，当前完整闭合思考模板 T-3 取点。
- checkpoint mean/std 标准化 → 线性 logit → sigmoid → 与原阈值 0.5 比较。
- 模板关闭 thinking；最多 16384 tokens，超限返回错误，不通过截断隐藏问题。

## 代码入口

以下行号按此次交接时的工作区定位，后续以函数名为准。

| 入口 | 用途 |
| --- | --- |
| `backend/app.py:121` | 网页实际 data root 的选择 |
| `backend/customer_agent.py:690` `_run_model_tool_loop` | message list、工具调用与最终回答循环 |
| `backend/customer_agent.py:741` `check_activation` | 每次生成前的完整上下文检测及 system 合并 |
| `backend/watchers/probe_bank.py:42` `moderate` | 原样发送 messages/tools 到影子服务，验证返回 |
| `backend/probe_bank_server.py:242` | build_prompt 和 tokenizer |
| `backend/probe_bank_server.py:126` `score_hidden` | IPI 标准化、打分及阈值逻辑 |
| `backend/probe_bank_hooks.py:10` `_flush_positions` | 各层 token 位置；同文件 layer hook 处理 residual |
| `backend/llm_client.py:58` `generate` | 业务模型请求的构造 |
| `/ssd/workspace/djs/zhuanli/src/sglang_fe/extractor.py:46` `build_prompt` | 实际影子 chat template、tool_calls 归一化和 fallback |
| `/ssd/workspace/djs/models/Qwen3.5-2B/chat_template.jinja` | 影子模型模板 |
| `regression/capture_ipi_handoff.py` | 本次 trace 采集脚本 |
| `regression/replay_ipi_handoff.py` | 原样重放已保存检测输入 |
| `regression/test_full_context_activation.py` | 完整上下文接入/阻断回归测试；不代表模型误报率测试 |

## 建议排查顺序与交付结果

1. **复现**：运行两个 checkpoint，记录模型、bank_version、tokens、logit/score、flagged。
2. **协议对齐**：将 checkpoint 02 在原训练/参考推理流水线中重放，对比实际渲染文本、token IDs、取点 token、层位及 hidden 向量，随后比较标准化结果和 logit。
3. **核对取点**：checkpoint 的 selected_positions=[-1] 与服务端 T-3 的对应关系要结合训练时消息模板确认，不能仅凭两个数字不同认定 bug。
4. **内容消融**：固定 query 和其余条件，分别检验 system、运行时最终回答指令、tool_calls、正常 tool 正文和 tools 定义的影响。保存各变体，不修改原始复现文件。
5. **误报/漏报验证**：若协议一致，再检查金融 RAG 正常样本与真实注入样本，判断是否需要校准或补充训练。单条样本调阈值不能作为最终修复依据。

期望返回：定位结论及证据、修复建议/补丁、原始两条输入重放结果、正常与攻击样本上的误报/漏报变化。

## 采集边界（重要）

这是按用户原文重新执行的**新会话复现**，不是找回原浏览器历史会话。历史为空，具体生成参数见 metadata.json；无法确认与用户原浏览器参数完全相同。

本次使用真实业务模型与本地 BM25；非流式采集，便于保存完整响应。为了采集报警后的最终回答，仅独立诊断进程采用 observation 模式：先保存真实检测结果，再忽略风险继续执行。**生产环境仍应在 checkpoint 02 拦截**。

因此，判断真实报警必须看 `checkpoint-*.response.json`，不要把 `agent-result.observation.json` 中的诊断放行状态当成线上安全判定。没有修改线上阈值或拦截策略。

文件保留完整 system 和检索正文，应作为内部排查材料分享。没有打包账号 Cookie、API Key、模型权重。本文不确认生成回答中的利率时效性。
