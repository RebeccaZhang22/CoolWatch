# Probe 训练数据

按风险类别保存，每行一条原始 JSON 样本。拟合只使用 `train.jsonl`，阈值和模型选择使用 `validation.jsonl`；测试数据独立放到 `../../evaluation/dataset/benchmark/`。

| 风险 | train | validation | 独立 test |
|---|---:|---:|---:|
| harmful | 7,766 | 1,952 | 1,860 |
| prompt_leakage | 13,228 | 3,972 | 5,060 |
| ipi | 未取得 | 未取得 | AgentDojo 100 条审计样本，不能代替训练数据 |

harmful 来自原有害请求上下文增广和正常请求；prompt_leakage 来自原 19,580 条加 2,680 条工具上下文样本。原始标签、split 和每行内容保持不变。类别目录的 `manifest.json` 记录当前路径、数量与哈希，`original_inventory.json` 和 `source_manifest.json` 保留历史来源。

**标签版本差异：** 原训练集含“允许的公开材料导出”负例，与用户最新“任何 RAG 内容导出均算泄露”的业务规则冲突。当前保存的是已上线模型的历史训练数据，不代表已按新规则重标或重训。新规则的场景评估见 `../../evaluation/dataset/in-the-wild/`。

IPI 只有上游训练来源记录和权重，完整训练会话、标签及特征未随包提供。未用演示测试样本冒充训练数据。历史 `.runtime/` 数据和特征缓存保留用于复现，不作为当前规范入口。
