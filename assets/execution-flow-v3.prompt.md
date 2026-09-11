# 执行过程：接入模型可解释性检测

工具：内置 image_gen（imagegen skill）；编辑目标：execution-flow-v2.png。
输出：execution-flow-v3.png；网页使用 frontend/assets 下的副本，保留旧版。

依据：backend/customer_agent.py 的 _run_input_guards 在 _run_model_tool_loop 前执行；probe_bank 路径接收用户输入，由独立检测模型提取表征并评分。命中风险返回固定安全提示，通过才进入业务流程。本图表示启用防护时的流程，不表示扫描完整 RAG 上下文或读取业务模型隐藏层。

## 最终提示词

+Edit the supplied execution-flow diagram for a Chinese product website. Image 1 is the edit target. Preserve its clean white background, thin teal/slate outlines, flat icons, dark Chinese typography, generous spacing and WIDE landscape composition (~2.6:1). Redesign placement as necessary to add the actual guard integration, with perfectly legible Chinese text. No outer title, no decorative paragraphs.
CRITICAL technical topology: The current deployed guard checks the USER INPUT before any business model execution or retrieval. It uses an independent detector model, extracting its internal representations and running probes, not hidden states from the business model. Do NOT imply scanning full RAG context or extracting business-model states.
Arrange two horizontal bands.
Upper band: left node "用户输入" feeds a pale green highlighted rounded group with heading "我们的方法 · 模型可解释性". Inside this group a horizontal chain of THREE nodes: "检测模型" (smaller sublabel "独立于业务模型") → "内部表征提取" → "风险评分". Then an arrow from this group to a decision diamond "风险判定". From the decision, a short rightward branch labeled "命中风险" leads to a muted red node "拦截 · 安全提示". The other branch labeled "通过" goes DOWN to the business-flow band. There MUST be no bypass path from input to business execution.
Lower band inside a subtle pale teal outline group headed "业务执行": The approved user input enters the "对话上下文" node (small chips "system", "user", "tool"). A compact "System Prompt" / "身份与规则" node on the left feeds this context. Below the context inputs include a compact RAG chain: "RAG 知识库" → "BM25 检索" → "相关片段" → context via upward arrow "tool 消息". From context rightward: "业务模型" → "最终回答". This entire lower group is gated by the "通过" arrow, so both RAG and business generation run only after approval. Include only these necessary labels, no ports, no model version names, no additional defense products. Strong visual hierarchy highlighting the green guard group as the newly added element; business flow remains clear and secondary. Avoid intersecting arrows. Keep output wide and compact, suitable for a webpage diagram that can be opened at full size.
