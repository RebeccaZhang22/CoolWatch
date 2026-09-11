# 实验审计本地数据

本目录保存实验审计页面使用的数据副本。前端不读取项目外部路径。

- `evaluation_summary.json`：页面使用的精简指标；内容安全部分为明确标注的 Mock 数据。
- `system_prompt_summary.json`：System Prompt 泄漏的原始汇总副本。
- `rag_summary.json`：RAG 泄漏的原始汇总副本。
- `leakgauge_activation_report.md`：LeakGauge 激活评测报告副本。
- `layer_auroc_domain_adapted.csv`：间接提示词注入域适应后的逐层 AUROC。
- `layer_auroc_domain_adapted.png`：逐层 AUROC 图表。

间接提示词注入页面展示 Layer 7 在 10% trace 域适应、90% trace 留出评测协议下的结果。内容安全 Mock 数据不得作为正式实验结论引用。
