# IPI 训练数据来源

状态：当前未取得完整训练数据，不能直接从本目录重训。

线上权重是 `probe/qwen3-8b/indirect_prompt_injection/best_layer_22.pt`，
来自上游 AgentDojo `broad_zero_val` 训练，标签为 `risk_faced`。

上游运行目录（相对于源机器仓库）：

```text
results/probe_traces/v2/agentdojo-20260430T015534Z-qwen3-8b-dp4/
```

重训所需的上游内容包括：

- `features/default/`：激活特征；
- `labels/risk_faced/labels.jsonl`：标签；
- `grid_points/`：对话与决策点；
- 训练样本选择与分组划分记录。

`upstream_HANDOFF.md`、`upstream_run_manifest.json` 是归档包原样提供的来源材料，
不是完整训练集。运行清单中的轨迹/决策点计数不能直接当作最终训练样本数。
项目的 `data/ipi_replay/` 仅是演示回放案例，也不是本 probe 的训练集。
