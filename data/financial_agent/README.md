# 邮储银行财富知识助手演示数据

这是一个基于公开资料的邮储银行财富知识问答场景，用于回答基金、理财、黄金、利率、保险、客户分层和客服渠道问题，并演示针对 System Prompt、Skill、隐藏推理和运行时 RAG 上下文的安全防护。知识库不包含真实客户账户或交易数据。


## 场景内容

- `agent/system_prompt.md`：Agent 的系统消息，定义能力、工具调用方式和保密边界；
- `rag/psbc/`：BM25 公开知识库，包含 40 份来源文档和一份常见问题汇总；
- `tools/definitions.json`：公开知识检索工具 `search_financial_knowledge` 的调用定义与必要检索条件；
- `conversation_starters.json`、`attacks/catalog.json`：前端入口和安全演示用请求；
- `evaluation/protected_assets.json`：需要保护的 reasoning、Skill 和 System Prompt 资产；RAG 窃取则按本轮实际召回的 chunk 动态判定。

## 工具执行

运行时链路为：业务模型读取 System Prompt 和用户请求 → 调用 BM25 公开知识检索 → 读取召回片段 → 输出带来源和日期说明的最终答复。系统不连接真实银行账户，也不会执行转账、申购、赎回或其他交易操作。

## 更换场景

后端默认从本目录加载。若要切换到另一份兼容的场景数据，可在 `backend/.env` 设置 `CUSTOMER_AGENT_DATA_ROOT`。
