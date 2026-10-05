# Benchmark 来源与使用范围

本目录集中保存基准来源、冻结测试集和历史回归；不是所有文件都能直接送入 judge。可执行数据清单为 `catalog.json`，原始攻击字符串需要先配齐上下文。

| 风险 | 引用基准 / 来源 | 本地数据 | 限制 |
|---|---|---|---|
| harmful | AgentHarm 衍生有害请求、上下文增广及正常请求 | `harmful/probe_holdout/test.jsonl`：1,860 条 | 本项目固定留出集，不是官方完整评测；来源清单见 `../../../train/data/harmful/source_manifest.json` |
| prompt_leakage | Raccoon 中文材料、LeakGauge、原 protected_asset_theft 数据及工具上下文增广 | `prompt_leakage/probe_holdout/test.jsonl`：5,060 条 | 保留原始标签与划分；来源见 `../../../train/data/prompt_leakage/source_manifest.json` |
| prompt_leakage | Raccoon 中文场景和攻击模板 | `prompt_leakage/raccoon_zh/` | 原始素材，需组装完整上下文 |
| prompt_leakage | LeakGauge 的系统提示及 RAG 泄露材料 | `prompt_leakage/leakgauge_demo/` | 原始素材与来源说明见子目录 README |
| prompt_leakage | 本地合成盗取审计 | `prompt_leakage/theft_large_v1/`：10,000 条 | 历史合成测试，不代表真实线上攻击 |
| prompt_leakage | 外部审计及已知问题回归 | `prompt_leakage/external_audits/` | external_attack 512、natural_safe 395、reported_short 232、reported_rag_tool_context 5；已知问题不代表独立泛化 |
| ipi | AgentDojo 冻结注入决策点，中文翻译版 | `ipi/agentdojo_100_zh/cases.jsonl`：100 条 | 仅含注入正例，不能用于估计误拦率；来源与设置见其 README、case_manifest 和 settings |

标签使用 `original_frozen` 历史口径。特别是原泄露数据含公开内容导出负例，与最新“RAG 内容导出均算泄露”要求不同。复现旧模型时保持原数据；按新业务口径评估应使用明确标注的新版本，不能混合后宣称统一准确率。场景自建案例在 `../in-the-wild/`，训练与验证集在 `../../../train/data/`。
