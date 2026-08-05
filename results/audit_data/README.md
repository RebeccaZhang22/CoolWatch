# 审计数据目录

`results/audit_data/` 是开源演示读取的冻结审计数据入口。逐条案例和护栏结果使用 JSONL；FinVault 原始执行报告保留 JSON。所有 manifest 只引用仓库内相对路径。

## 固定目录契约

```text
results/audit_data/
├── catalog.jsonl
└── <audit_id>/
    ├── audit_manifest.jsonl
    ├── cases.jsonl
    ├── guard_results/
    │   └── <guard_id>.jsonl
    ├── behavior_results.jsonl      # 可选，模型行为
    ├── behavior_judgments.jsonl    # 可选，行为判定
    └── summary.jsonl               # 可选，冻结汇总
```

- `catalog.jsonl`：每行描述一个可用审计任务，便于发现数据集。
- `audit_manifest.jsonl`：单行文件，记录模型、语言、来源和文件映射。
- `cases.jsonl`：每行一个冻结案例，是跨护栏复用的主键来源。
- 系统提示词提取的 `cases.jsonl` 同时是 No Guard 基线，不再复制为 `guard_results/no_guard.jsonl`。
- `guard_results/*.jsonl`：按 `case_key` 或 `decision_point_id` 与案例连接。
- `summary.jsonl`：派生汇总；可以从 cases 和 guard results 重建。

配置文件仍可使用普通 JSON；所有实验记录和结果表必须使用 JSONL。
FinVault 的模型执行报告来自其原始评测器，保留普通 JSON 格式；前端发布的 Guard、SafeGauge 和汇总记录使用 JSONL。

训练与评测脚本不在最小开源闭包内。后端通过 `GET /api/audit/catalog` 暴露当前数据目录，前端通过审计接口只读这些冻结文件。
