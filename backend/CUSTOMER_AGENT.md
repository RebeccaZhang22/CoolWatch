# 客服助手-小航后端

默认场景位于 [`data/hanglvzongheng/`](../data/hanglvzongheng/README.md)。`scenario.json` 指定系统提示词、工具和 RAG 数据。系统提示词直接读取 `system_prompt.md`，不拼接其他策略文件。

## Agent 与工具

每轮模型请求分别传入 `messages` 和原生 `tools`，使用 `tool_choice=auto`。

- `search_knowledge(query)`：用 jieba 和 BM25 检索航旅资料，命中文本通过 `tool` 消息返回；分数、来源和片段标识保留在检索轨迹中。
- `search_knowledge`：从原始 RAG 语料召回片段。MU5107 间接注入演示仅在运行时 Tool Response 中插入载荷，不修改召回片段或源文件。
- `process_refund`、`change_ticket`、`send_sms`、`browse_webpage`：通过沙盒逻辑或 LLM 根据当前上下文和参数生成 JSON，不执行真实业务或访问真实网页。

工具返回后继续允许模型调用工具。模型给出普通回答即结束，不在循环中等待用户输入。最多执行 8 轮工具决策，达到上限后生成收尾答复。`tool_trace`、`rag_trace`、`stage_trace` 和 `raw_trajectory` 记录实际执行过程。`raw_trajectory` 每个 step 只包含一条新增消息，依次记录 system、user、assistant 工具调用、tool 响应和最终 assistant 答复；不保存累积的模型请求快照。历史消息会单独标记。

模拟工具复用 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`FINANCIAL_TOOL_MODEL` 和 `FINANCIAL_TOOL_TIMEOUT_SECONDS`，保持现有部署变量名称。工具模型默认 `deepseek-v4.1-flash`；RAG 本地检索不需要 API Key。

## 配置与防护

提示词编辑保存到 `agent/system_prompt.override.md`，优先于默认提示词。上传的 RAG 资料加入 `rag/documents.json`，并重建 BM25 索引。已开始的请求继续使用原快照，后续请求使用更新后的快照。文件替换、失败回滚和上传路径校验由运行时配置管理器负责。

场景无需攻击目录或评估配置文件。系统提示词、模型私有推理和 private RAG 的检测对象直接从已加载内容生成。private 标签用于泄漏检测，不等同于检索权限控制。旧攻击目录接口返回空列表；正常运行通过 `message` 提交请求。

`baseline` 关闭外部防护用于对照；`defended` 使用所选防护。Activation 检测在每轮模型决策前运行，检测上下文仅包含当前 agent loop 的主系统提示、本轮用户输入以及本 loop 已产生的工具调用和工具结果，不累计已完成的会话历史。业务模型仍保留正常会话历史。私有资产重合评估保留，独立 reasoning 不交付客户端。工具与上下文检测的执行逻辑不依赖额外场景配置目录。

## API 与启动

接口使用 ProspectMonitor 登录会话或 CLI Token。

| 接口 | 用途 |
| --- | --- |
| `GET /api/customer-agent` | 场景资料和提问示例 |
| `GET /api/customer-agent/health` | 模型可用状态 |
| `GET /api/customer-agent/profile` | 工具、知识源和防护能力 |
| `GET/PUT /api/customer-agent/config/system-prompt` | 查看或更新提示词 |
| `GET /api/customer-agent/config/rag` | 查看知识库配置 |
| `POST /api/customer-agent/config/rag/documents` | 上传 Markdown/TXT |
| `DELETE /api/customer-agent/config/rag/documents/{id}` | 删除上传资料 |
| `POST /api/customer-agent/run` | 执行一次 Agent 请求 |
| `POST /api/customer-agent/run/stream` | SSE 阶段事件及最终答复 |
| `POST /api/customer-agent/compare` | 同一消息的无防护与有防护对照 |
| `POST /api/customer-agent/sessions/{session_id}/reset` | 清空会话历史 |

启动：`./vllm_setups/run_agent_backend.sh`。修改磁盘上的场景配置后需重启后端；通过配置 API 保存的修改立即对后续请求生效。

示例请求：

```json
{
  "message": "CA1234 航班的行李规定是什么？",
  "defense_mode": "defended",
  "defenses": ["activation_probe", "safegauge"]
}
```

验证：`python -m unittest regression.test_hanglv_agent regression.test_customer_agent_replay -v`。
