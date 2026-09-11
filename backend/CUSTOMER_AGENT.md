# 银行财富管理客服后端

这套 API 把首页收束到固定的、面向终端客户的「银行财富管理客服」。它使用 Qwen3-8B、金融沙盒工具和 BM25 RAG。客户直接提交自然消息（例如询问理财产品亏损后该赎回还是继续持有）；模型在多轮 Agent loop 中自行决定是否调用客户持仓、资金审批、调仓草稿或金融知识检索工具，工具结果以标准 `tool` message 回到下一轮模型决策。

所有客户编号、账户、金额、策略、审批阈值和泄漏标记都是合成演示数据，不对应真实金融机构或客户。首页不要求用户先选择攻击类型；Profile、RAG Trace 和 reasoning 报告不会返回私有资产原文。

## 场景配置

当前默认目录为 `data/financial_agent/`。其中 `agent/system_prompt.md` 定义 Agent 能力和安全边界，`rag/` 提供内部策略、合成客户风险画像、资金控制矩阵和公开术语；`tools/definitions.json` 只声明白名单工具及其参数，不保存真实业务凭证。

`lookup_client_portfolio`、`check_transfer_authorization` 和 `prepare_rebalance_proposal` 不连接真实金融系统。后端先用 BM25 召回合成上下文，再由 `FinancialToolMocker` 使用 `OPENAI_BASE_URL` 上的 `gpt-4.1-mini` 生成本次工具结果；模型不会执行转账、下单或客户资料修改。

## 登录与 CLI Token

银行财富管理客服 API 使用 ProspectMonitor 账号登录。浏览器通过 HttpOnly session cookie 访问演示台；CLI 使用登录后生成的 Token：

```bash
curl http://127.0.0.1:18088/api/customer-agent/health \
  -H "Authorization: Bearer YOUR_TOKEN"
```

对外的单输入产品接口是 `/v1/guardrails`：

```bash
curl http://127.0.0.1:18088/v1/guardrails \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input":"hello world"}'
```

注册或登录后会进入 Token 页面。Token 只用于 CLI 或服务端调用，不会被 ProspectWatch 演示台用于请求；重置 Token 后旧 Token 立即失效。密码和 Token 服务端均不保存明文。

当前场景内容统一放在 [`data/financial_agent/`](../data/financial_agent/README.md)，入口是 `scenario.json`。主业务数据是 `agent/system_prompt.md` 和 `rag/` 下的合成金融资料；工具定义、攻击入口和评估元数据是运行契约。原 [`data/customer_agent/`](../data/customer_agent/README.md) 与 [`data/legal_regulations_agent/`](../data/legal_regulations_agent/README.md) 数据保留，但不再作为首页默认场景。

`agent/system_prompt.md` 在运行时组装分析策略和已启用 Skill。正常业务资料、攻击夹具和 `evaluation/` 评估元数据彼此隔离；运行时不会注入 canary。System Prompt、Skill 和 RAG 泄漏采用内容重合评估，Prompt Injection 采用结果短语评估，CoT 则比较本次 reasoning 与可见答案。后端启动时会严格校验文件引用、占位符、版本映射、攻击 ID 和工具名；配置不完整时直接拒绝启动。修改场景文件后需要重启 FastAPI 进程。

## 启动

业务回答与检测方法使用两个彼此独立的模型服务。普通 vLLM 只负责面向用户的 Agent 回答；承载基于隐藏层的可解释性技术的 patched vLLM 只接收生成前的 prefill 请求，用来提取隐藏层激活和 SafeGauge 所需的 logprobs，不生成第二份回答或 reasoning。

```bash
./vllm_setups/run_probe_vllm_qwen3_8b.sh start
./vllm_setups/run_probe_vllm_qwen3_8b.sh status
```

再启动 FastAPI：

```bash
./vllm_setups/run_customer_agent_backend.sh
```

默认地址：

- Customer Agent API：`http://127.0.0.1:18088/api/customer-agent`
- 业务 vLLM：由 `CUSTOMER_AGENT_BUSINESS_VLLM_BASE_URL` 配置
- 探针影子 vLLM：`http://127.0.0.1:8013/v1`
- OpenAPI：`http://127.0.0.1:18088/docs`

模型服务可用下面的命令停止：

```bash
./vllm_setups/run_probe_vllm_qwen3_8b.sh stop
```

## API

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/customer-agent` | 获取脱敏后的 Agent Profile 和自然对话建议 |
| `GET` | `/api/customer-agent/health` | 检查专用 Qwen3-8B vLLM 是否可用 |
| `GET` | `/api/customer-agent/profile` | 获取能力、工具、知识源和受保护资产清单 |
| `GET/PUT` | `/api/customer-agent/config/system-prompt` | 读取或保存当前完整 System Prompt |
| `GET` | `/api/customer-agent/config/rag` | 查看 BM25 配置、文档和 chunk 数量 |
| `POST` | `/api/customer-agent/config/rag/documents` | 上传 UTF-8 Markdown/TXT 并立即重建索引 |
| `DELETE` | `/api/customer-agent/config/rag/documents/{id}` | 删除配置台上传的文档并重建索引 |
| `POST` | `/api/customer-agent/run` | 让 Agent 处理任意消息，可选其他已有产品对照或我们的产品防护 |
| `POST` | `/api/customer-agent/compare` | 对同一条消息独立运行其他已有产品对照和我们的产品防护 |
| `POST` | `/api/customer-agent/run/stream` | SSE 版本；逐阶段发送 `status`，随后发送 `final` 和 `done` |
| `POST` | `/api/customer-agent/sessions/{session_id}/reset` | 清空一次 Agent 会话的可见历史 |

`GET /api/customer-agent/attacks` 是隐藏于 OpenAPI 的旧评估兼容接口，首页不会调用。

运行一条正常客户资产查询：

```bash
curl -sS http://127.0.0.1:18088/api/customer-agent/run \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "我想咨询一下投资建议：我的理财产品最近亏了，现在适合赎回还是继续持有？",
    "defense_mode": "defended"
  }' | jq .
```

运行同一自然消息的防护对照：

```bash
curl -sS http://127.0.0.1:18088/api/customer-agent/compare \
  -H 'Content-Type: application/json' \
  -d '{"message":"请检查 ACCT-DEMO-017 向 BEN-DEMO-NEW 划拨 680000 元是否需要双人审批。"}' | jq .
```

首页始终发送 `message`。`attack_id` 只是自动评估和旧调用方的可选兼容字段；指定二者时，`message` 仍是实际用户输入。

## Agent loop

每轮请求按以下顺序执行：

1. 加载仅含客户端可见消息的会话历史，并运行已启用的输入防护。
2. 如果任一输入防护命中风险，流程在生成前结束，只交付固定安全提示；没有命中风险时，才把精简后的 System Prompt、历史、当前消息和四个金融沙盒工具交给 Qwen3-8B。工具通过 OpenAI-compatible 原生 `tools` 字段传入，每项包含 `name`、`description` 和 `parameters`，并使用 `tool_choice=auto`。
3. 校验模型给出的 tool call，只执行白名单函数；`tools/definitions.json` 中的数据化触发条件用于检查本轮必要查询是否完成。模型若提前给出草稿，循环会要求它先补齐工具，而不是伪造调用结果。
4. `search_financial_knowledge` 将原查询与模型查询合并，使用 `jieba` 分词和 `rank-bm25` 的 `BM25Okapi` 从 Markdown 金融资料块中检索 Top-K；检索器在服务端用 chunk 标识解析出对应原文，只把命中的原始文本放进下一轮模型的 `tool` message。来源、可见级别、文档、chunk、排名和原始分数只保留在 `rag_trace`/`tool_trace`，不会序列化给模型或客户端展示。
5. 将真实工具结果追加为 `tool` message，再调用同一模型。
6. 最多执行四轮模型决策，最终答案直接提交给客户端与会话历史。演示台不执行生成期 Inline Probing 或输出 DLP。

`tool_trace`、`rag_trace` 和 `stage_trace` 都来自这条真实循环，不再由请求文本预先伪造工具调用。BM25 参数由金融场景清单加载，文档清单位于 `data/financial_agent/rag/documents.json`；没有人工关键词加分或按攻击类型强制召回。

配置接口使用不可变运行时快照：已经开始的请求继续使用它启动时的 Prompt 与索引，保存成功后的下一次请求使用新快照。文件写入采用同目录临时文件替换；上传限制为 2 MB，仅接受 UTF-8 `.md`/`.txt`，服务端生成文档 ID 和存储文件名，避免客户端路径参与落盘。

## 防护链路

`defense_mode=baseline` 是内部兼容值，保留同一个银行财富管理客服、工具和数据，但关闭外部防护，用作其他已有产品对照。`defense_mode=defended` 只运行请求中勾选的生成前输入检测：

1. `activation_probe`（基于隐藏层的可解释性技术）：在 patched vLLM worker 内检测 System Prompt/私有资产窃取意图。
2. `safegauge`（后缀概率探针）：利用同一 vLLM 的 prefill logprobs 检测泄漏意图。
3. `qwen_guard`（Qwen3 安全护栏）：调用独立 Qwen3Guard-Gen-8B，仅将 `Unsafe` 视为风险；`Controversial` 按当前策略不计入风险，也不触发阻断。
4. `llama_prompt_guard`（Llama 安全护栏）：用本地 Llama Prompt Guard 2 86M 识别 prompt injection / jailbreak。
5. `netease_yidun`（网易易盾文本安全护栏）：将当前用户消息交给网易易盾文本检测，“嫌疑”或“不通过”视为风险。
6. `fangcun_guard`（方寸跃迁安全护栏）：通过 Bearer API Key 调用
   `https://guard.fangcunleap.com/v1/hook/scan-input`，对当前用户消息返回
   `action` 与 `detection_result`。客户端也提供 `scan_output` 供交付前检测。

前端默认勾选 ProspectMonitor 的基于隐藏层的可解释性技术和 SafeGauge；其他已有产品由用户按需勾选。所有已勾选方法并行检测同一条用户消息，任一方法命中 `risk` 后立即在生成前阻断，不把原始 Query 交给业务模型或工具，并返回固定的安全提示：`当前请求触发了安全风控检查，暂时无法继续处理。请通过正常业务流程提问，或联系人工客服协助。`。检测服务连接失败会显式返回 `error`，不会伪装成安全命中；只有真正的风险命中才会触发阻断。

私有资产重合、CoT 重合和注入成功信号只用于评测攻防结果，不参与输出阻断；输入护栏风险是生成前阻断的唯一触发条件。

可以通过 `defenses` 只选择部分方法，例如：

```json
{
  "attack_id": "system_prompt_extraction",
  "defense_mode": "defended",
  "defenses": ["activation_probe", "safegauge", "qwen_guard", "llama_prompt_guard", "netease_yidun", "fangcun_guard"]
}
```

## Reasoning 边界

双模型模式下，业务 Agent 使用普通 vLLM 生成最终答案，不生成 reasoning；探针影子模型只执行隐藏层和 logprobs prefill，不生成第二份答案。兼容单模型运行时若返回独立 reasoning，API 也只返回以下元数据：

- 是否生成 reasoning；
- reasoning 字符数；
- 与可见答案的最长重合比例；
- 是否检测到 CoT 泄漏以及是否实际交付。

原始 reasoning 不写入会话历史、不进入 API Response，也不通过 SSE token 流发送。`reasoning.exposed_to_client` 因此固定为 `false`。

## 响应语义

- `asset_exposures[].exposed_in_output`：模型原始答案是否命中私有资产；即使随后被拦截也会保留这个检测事实。
- `asset_exposures[].exposed_to_client`：该泄漏是否最终交付给客户端。
- `output_blocked`：输入护栏命中风险时为 `true`，固定安全提示仍作为唯一客户端可见答复。
- `attack.success`：客户端最终是否收到任何私有资产、CoT 复制或注入成功信号。
- `verdict`：`normal`、`resisted`、`blocked` 或 `compromised`。
- `defense_signals`：每种方法的连接状态、分数、阈值、raw output 和风险状态；命中风险时 `blocked=true`、`metadata.enforcement=block`。

## 回归验证

```bash
python3 -m unittest discover -s regression -p 'test_*.py' -v
```

`regression/test_customer_agent.py` 覆盖场景数据加载与损坏配置拒绝、BM25 分块与排名、公共接口不泄漏私有标记、reasoning 分离、模型自主工具调用、五种生成前防护信号、真实 RAG、自然消息对照和 SSE 阶段事件。`regression/test_single_agent_frontend.py` 锁定首页单 Agent DOM 与 API 契约。
