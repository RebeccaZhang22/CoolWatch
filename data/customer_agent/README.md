# Customer Agent 场景数据

这个目录是 `/api/customer-agent/*` 的唯一场景配置来源。业务资料、攻击夹具和评估元数据彼此隔离，避免把 canary 或恶意指令误当成正常客服内容。

```text
customer_agent/
  scenario.json                         # v2 场景入口和文件引用
  conversation_starters.json           # 面向真实对话的自然消息建议（含单轮 RAG 演示入口）
  agent/
    system_prompt.md                    # 完整客服 System Prompt 模板
    system_prompt.override.md           # 配置台保存的运行时 Prompt（本地生成）
    reasoning_policy.md                 # reasoning 的使用与输出边界，不是静态 CoT
  skills/
    catalog.json                        # Skill 元数据
    refund_authorization/instructions.md# 完整退款判断 Skill
  rag/
    documents.json                     # 文档来源、可见级别和风险元数据
    public/*.md                        # 面向客户的公开知识
    internal/*.md                      # 仅供 Agent 判断的内部知识
    uploads/*.{md,txt}                 # 配置台上传并纳入 BM25 的本地文档
  attacks/
    catalog.json                       # 五类攻击卡片与默认 Prompt
    fixtures/poisoned_rag/*.md          # 仅用于攻击演示的污染文档
  evaluation/
    protected_assets.json              # 资产来源、检测阈值与防护映射
    canaries.json                      # 只供本地评估使用的合成标记
  tools/definitions.json               # 沙盒工具定义与必要查询触发条件
  orders/demo_orders.json              # 合成订单
```

## 运行时组装

后端用 `agent/system_prompt.md` 组装最终 System Prompt，将答复准备清单和启用的业务处理手册插入对应占位符。真实 CoT 不存放在数据目录中，它由 Qwen3 针对每次请求动态生成，并通过服务端 `reasoning_content` 与最终答案的重合度评估是否泄漏。

`evaluation/canaries.json` 中的标记不会写入正常业务资料。加载器只在运行时把它们作为中性 trace 字段附加到对应上下文，以便评估程序稳定归因 System Prompt、Skill 和 RAG 泄漏；它们不再携带“禁止输出”等提示语义。Prompt Injection 的恶意内容只存在于 `attacks/fixtures/`。

## BM25 RAG

客服知识库使用传统稀疏检索，不依赖向量模型：Markdown 文档先按标题段落切块，过长段落按字符窗口继续切分；正文和标题使用 `jieba` 搜索模式分词，再由 `rank-bm25` 的 `BM25Okapi` 建立进程内索引。模型调用 `search_knowledge_base` 后，工具按 BM25 原始分数取 Top-K 片段，并将文档 ID、chunk ID、标题、排名、分数和来源随片段一起返回。

`scenario.json` 中的 `rag` 节统一配置 `top_k`、`min_score`、`k1`、`b`、最大块长度和 overlap。目前取 Top-3。`documents.json` 不再保存人工关键词、基础分或特殊激活短语；正常客服查询、偷 RAG 评估和污染文档都走同一份 BM25 索引，`attack_id` 不会强制修改召回结果。

所有订单、内部规则、攻击内容和评估标记都是合成演示数据，不是真实客户资料或生产凭证。配置在进程启动时执行严格一致性校验。

`scenario.json` 的 `defense_pipeline` 只列出生成前输入检测：隐藏层激活探针、后缀概率探针、Qwen3 安全护栏、Llama 安全护栏、网易易盾文本安全护栏和方寸跃迁安全护栏。客服攻防演示台不再将生成内探针接入 Agent loop。

前端「Agent 配置」可以直接保存完整 System Prompt，也可以上传 UTF-8 编码的 Markdown/TXT 文档。Prompt 写入 `agent/system_prompt.override.md`；上传文件写入 `rag/uploads/`，同时原子更新 `rag/documents.json`。两类变更都会在请求成功前完成严格加载校验并热更新运行时快照，上传文档还会立即重建 BM25 索引，不需要重启 FastAPI。内置文档在配置台中只读，只有前端上传的文档可以删除；点击「新聊天」时会清理上传文档并保留内置知识库。
