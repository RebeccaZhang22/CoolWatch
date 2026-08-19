# 法规条款 Agent 后端

这套 API 把首页收束到固定的「法规条款 Agent」。它使用 Qwen3-8B、法规版本工具和 BM25 RAG。用户直接提交自然消息；模型在多轮 Agent loop 中自行决定是否调用 `search_legal_corpus`、`get_legal_document` 或 `compare_legal_versions`，工具结果以标准 `tool` message 回到下一轮模型决策。

所有辖区、法规、机关、文号、文档和泄漏标记都是合成演示数据，不构成真实法律意见。首页不要求用户先选择攻击类型；Profile、RAG Trace 和 reasoning 报告不会返回私有资产原文。

## 场景配置

## 登录与 CLI Token

法规 Agent API 使用 ProspectMonitor 账号登录。浏览器通过 HttpOnly session cookie 访问演示台；CLI 使用登录后生成的 Token：

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

当前场景内容统一放在 [`data/legal_regulations_agent/`](../data/legal_regulations_agent/README.md)，入口是 `scenario.json`。完整 System Prompt、reasoning 策略、时态版本 Skill、法规 RAG、对话建议、评估样例和工具都从这里加载。原 [`data/customer_agent/`](../data/customer_agent/README.md) 数据保留，但不再作为首页默认场景。

`agent/system_prompt.md` 在运行时组装分析策略和已启用 Skill。正常业务资料、攻击夹具和 `evaluation/` 评估元数据彼此隔离；运行时不会注入 canary。System Prompt、Skill 和 RAG 泄漏采用内容重合评估，Prompt Injection 采用结果短语评估，CoT 则比较本次 reasoning 与可见答案。后端启动时会严格校验文件引用、占位符、版本映射、攻击 ID 和工具名；配置不完整时直接拒绝启动。修改场景文件后需要重启 FastAPI 进程。

## 启动

业务回答与安全探针使用两个彼此独立的模型服务。普通 vLLM 只负责面向用户的 Agent 回答；带 Activation Probe 的 patched vLLM 只接收生成前的 prefill 请求，用来提取隐藏层激活和 SafeGauge 所需的 logprobs，不生成第二份回答或 reasoning。

```bash
./vllm_setups/run_customer_agent_qwen3_8b.sh start
./vllm_setups/run_customer_agent_qwen3_8b.sh status
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
./vllm_setups/run_customer_agent_qwen3_8b.sh stop
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
| `POST` | `/api/customer-agent/run` | 让 Agent 处理任意消息，可选 baseline 或 defended |
| `POST` | `/api/customer-agent/compare` | 对同一条消息独立运行 baseline 和 defended |
| `POST` | `/api/customer-agent/run/stream` | SSE 版本；逐阶段发送 `status`，随后发送 `final` 和 `done` |
| `POST` | `/api/customer-agent/sessions/{session_id}/reset` | 清空一次 Agent 会话的可见历史 |

`GET /api/customer-agent/attacks` 是隐藏于 OpenAPI 的旧评估兼容接口，首页不会调用。

运行一条正常法规查询：

```bash
curl -sS http://127.0.0.1:18088/api/customer-agent/run \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "截至 2026-08-11，发生重大数据安全事件后应在多久内报告？",
    "defense_mode": "defended"
  }' | jq .
```

运行同一自然消息的防护对照：

```bash
curl -sS http://127.0.0.1:18088/api/customer-agent/compare \
  -H 'Content-Type: application/json' \
  -d '{"message":"2025 年 9 月发生的事件适用 72 小时还是 48 小时？"}' | jq .
```

首页始终发送 `message`。`attack_id` 只是自动评估和旧调用方的可选兼容字段；指定二者时，`message` 仍是实际用户输入。

## Agent loop

每轮请求按以下顺序执行：

1. 加载仅含客户端可见消息的会话历史，并运行已启用的输入防护。
2. 把 System Prompt、历史、当前消息和三个法规沙盒工具交给 Qwen3-8B，使用 `tool_choice=auto`。
3. 校验模型给出的 tool call，只执行白名单函数；`tools/definitions.json` 中的数据化触发条件用于检查本轮必要查询是否完成。模型若提前给出草稿，循环会要求它先补齐工具，而不是伪造调用结果。
4. `search_legal_corpus` 将原查询与模型查询合并，使用 `jieba` 分词和 `rank-bm25` 的 `BM25Okapi` 从 Markdown 条款块中检索 Top-K；工具结果携带版本、效力状态、生效区间、文档、chunk、排名和原始分数。`as_of_date` 由后端从原始用户问题解析，未给日期时使用请求当天，不接受模型自行编造日期。
5. 将真实工具结果追加为 `tool` message，再调用同一模型。
6. 最多执行四轮模型决策，最终答案直接提交给客户端与会话历史。演示台不执行生成期 Inline Probing 或输出 DLP。

`tool_trace`、`rag_trace` 和 `stage_trace` 都来自这条真实循环，不再由请求文本预先伪造工具调用。BM25 参数由法律场景清单加载，文档清单位于 `data/legal_regulations_agent/rag/documents.json`；没有人工关键词加分或按攻击类型强制召回。

配置接口使用不可变运行时快照：已经开始的请求继续使用它启动时的 Prompt 与索引，保存成功后的下一次请求使用新快照。文件写入采用同目录临时文件替换；上传限制为 2 MB，仅接受 UTF-8 `.md`/`.txt`，服务端生成文档 ID 和存储文件名，避免客户端路径参与落盘。

## 防护链路

`defense_mode=baseline` 保留同一个法规 Agent、工具和数据，但关闭外部防护，用作真实对照。`defense_mode=defended` 只运行请求中勾选的生成前输入检测：

1. `activation_probe`（隐藏层激活探针）：在 patched vLLM worker 内检测 System Prompt/私有资产窃取意图。
2. `safegauge`（后缀概率探针）：利用同一 vLLM 的 prefill logprobs 检测泄漏意图。
3. `qwen_guard`（Qwen3 安全护栏）：调用独立 Qwen3Guard-Gen-8B，将 `Unsafe` 或 `Controversial` 视为风险。
4. `llama_prompt_guard`（Llama 安全护栏）：用本地 Llama Prompt Guard 2 86M 识别 prompt injection / jailbreak。
5. `netease_yidun`（易盾文本安全）：将当前用户消息交给网易易盾文本检测，“嫌疑”或“不通过”视为风险。

前端默认勾选 ProspectMonitor 的 Activation Probe 和 SafeGauge；三种 baseline 由用户按需勾选。所有已勾选方法并行检测同一条用户消息，风险命中会记录为 `risk`，但采用 `observe_only` 策略继续把原始 Query 交给业务模型和工具。检测服务连接失败会显式返回 `error`，不会伪装成安全命中。

私有资产重合、CoT 重合和注入成功信号只用于评测攻防结果，不参与输出阻断。

可以通过 `defenses` 只选择部分方法，例如：

```json
{
  "attack_id": "system_prompt_extraction",
  "defense_mode": "defended",
  "defenses": ["activation_probe", "safegauge", "qwen_guard", "llama_prompt_guard", "netease_yidun"]
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
- `output_blocked`：保留用于响应兼容；当前旁路观测链路固定为 `false`。
- `attack.success`：客户端最终是否收到任何私有资产、CoT 复制或注入成功信号。
- `verdict`：`normal`、`resisted`、`blocked` 或 `compromised`。
- `defense_signals`：每种方法的连接状态、分数、阈值、raw output 和风险状态；命中风险时 `blocked=false`、`metadata.enforcement=observe_only`。

## 回归验证

```bash
python3 -m unittest discover -s regression -p 'test_*.py' -v
```

`regression/test_customer_agent.py` 覆盖场景数据加载与损坏配置拒绝、BM25 分块与排名、公共接口不泄漏私有标记、reasoning 分离、模型自主工具调用、五种生成前防护信号、真实 RAG、自然消息对照和 SSE 阶段事件。`regression/test_single_agent_frontend.py` 锁定首页单 Agent DOM 与 API 契约。
