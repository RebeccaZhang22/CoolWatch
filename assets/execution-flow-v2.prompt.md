# 横向执行流程图

工具：内置 image_gen；编辑目标：execution-flow-v1.png；输出：execution-flow-v2.png。保留旧图，网页使用 frontend/assets 下的副本。

## 最终提示词

Edit this diagram into a much WIDER, shorter landscape layout, approximately 2.6:1 aspect ratio. Preserve the exact Chinese labels, clean white background, teal/slate palette, thin arrows and flat icons. Redesign placement rather than stretching existing pixels. Upper left: two small stacked nodes 'System Prompt' / '身份与规则' and '用户输入' / '当前问题'. Lower left, beneath these inputs: a compact horizontal RAG pipeline 'RAG 知识库' → '分词 · BM25 检索' → '相关片段'. User input has a short arrow to the retrieval step labeled '基于问题检索'. Move the '对话上下文' box to the center-right, containing small role labels 'system' 'user' 'tool'. Both input nodes feed this context box; the RAG snippets feed it from below with arrow labeled 'tool 消息'. From the context box extend a clear horizontal chain to its right: '模型处理' → '最终回答'. All three of these main nodes must be aligned horizontally, NOT vertically. No arrows from RAG into System Prompt. Keep generous but not excessive spacing, minimal margins, avoid crossing arrows, large legible typography and restrained outlines. No outer title, caption, paragraphs, or numbered step cards. The result must be a polished compact wide flowchart suitable for a website section, not a portrait chart.
