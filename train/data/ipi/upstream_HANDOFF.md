# Qwen3-8B broad 线性探针 handoff（2026-09-11）

与 Qwen3.5-2B 打包（`qwen3_5_2b_broad_probes_20260910.zip`）同构：36 个逐层线性探针
（layer 0-35），用于在 AgentDojo 决策点上检测 prompt-injection 风险。

## 1. 概况

- 模型：Qwen3-8B（36 层，hidden 4096）。权重不在仓库 models/ 下，用 HF hub 快照或 `huggingface-cli download Qwen/Qwen3-8B`。
- 来源 run：`results/probe_traces/v2/agentdojo-20260430T015534Z-qwen3-8b-dp4/probes/broad_zero_val_final_ep5`（feature `default`，标注 `risk_faced`，
  broad 零验证集：linear, lr 1e-4, ep5, seed 42, standard 归一化）。
- 层号约定：探针 layer k 对应 HF `hidden_states[k+1]`（跳过 embeddings）。
- **token position**：qwen3 家族：featurize CLI 位置偏移为 0；采集时未传 chat_template_kwargs（开思考），Qwen3 模板尾部即 `<|im_start|>assistant\n`，**抓取位置 = T-1（assistant 后的换行）**。重放渲染用 `enable_thinking=True`。
- **canonical 层：layer 34**（held-out strict AUROC 0.9762，四组 mean 0.9668，
  选层依据 `results/figs/main-results-ep5-rescored-l34/rescore_ep5_best_layer.meta.json`）。

## 2. 目录结构

```
├── HANDOFF.md
├── standalone_score.py        # 独立推理脚本（仅依赖 torch）
├── cpu_minimal_example.py     # CPU 端到端示例（system + "hello" → 全层打分）
├── checkpoints/
│   ├── broad/                 # 36 层训练产物（逐字拷贝自 broad_zero_val_final_ep5）
│   ├── eval/broad_sweep/      # 每层 fyh.eval_groups.v1（strict/unseen_* AUROC）
│   ├── run_manifest.json      # trace root 采集 manifest
│   └── auroc_table.md         # 逐层 AUROC 表（同 §3）
```

## 3. 逐层 AUROC（risk_faced，held-out）

| layer | strict | unseen_attacks | unseen_suites | unseen_prompts |
|---:|---:|---:|---:|---:|
| 0 | 0.7462 | 0.9136 | 0.7473 | 0.9350 |
| 1 | 0.8513 | 0.9223 | 0.8560 | 0.9396 |
| 2 | 0.9052 | 0.9339 | 0.9065 | 0.9470 |
| 3 | 0.9486 | 0.9427 | 0.9485 | 0.9523 |
| 4 | 0.9530 | 0.9359 | 0.9537 | 0.9490 |
| 5 | 0.9495 | 0.9269 | 0.9511 | 0.9423 |
| 6 | 0.9121 | 0.9258 | 0.9169 | 0.9423 |
| 7 | 0.9052 | 0.9241 | 0.9084 | 0.9402 |
| 8 | 0.9461 | 0.9388 | 0.9475 | 0.9503 |
| 9 | 0.9598 | 0.9414 | 0.9578 | 0.9498 |
| 10 | 0.9754 | 0.9587 | 0.9722 | 0.9637 |
| 11 | 0.9742 | 0.9636 | 0.9693 | 0.9682 |
| 12 | 0.9663 | 0.9663 | 0.9645 | 0.9722 |
| 13 | 0.9656 | 0.9660 | 0.9625 | 0.9717 |
| 14 | 0.9464 | 0.9644 | 0.9480 | 0.9729 |
| 15 | 0.9542 | 0.9644 | 0.9514 | 0.9724 |
| 16 | 0.9571 | 0.9683 | 0.9554 | 0.9734 |
| 17 | 0.9545 | 0.9661 | 0.9527 | 0.9720 |
| 18 | 0.9672 | 0.9712 | 0.9628 | 0.9750 |
| 19 | 0.9461 | 0.9677 | 0.9413 | 0.9730 |
| 20 | 0.9580 | 0.9678 | 0.9517 | 0.9699 |
| 21 | 0.9487 | 0.9629 | 0.9395 | 0.9651 |
| 22 | 0.9607 | 0.9661 | 0.9572 | 0.9663 |
| 23 | 0.9693 | 0.9661 | 0.9615 | 0.9641 |
| 24 | 0.9705 | 0.9641 | 0.9641 | 0.9626 |
| 25 | 0.9721 | 0.9635 | 0.9648 | 0.9632 |
| 26 | 0.9700 | 0.9617 | 0.9623 | 0.9619 |
| 27 | 0.9686 | 0.9616 | 0.9612 | 0.9601 |
| 28 | 0.9640 | 0.9606 | 0.9562 | 0.9588 |
| 29 | 0.9640 | 0.9596 | 0.9560 | 0.9583 |
| 30 | 0.9660 | 0.9601 | 0.9566 | 0.9580 |
| 31 | 0.9603 | 0.9601 | 0.9517 | 0.9593 |
| 32 | 0.9662 | 0.9599 | 0.9601 | 0.9586 |
| 33 | 0.9708 | 0.9605 | 0.9647 | 0.9588 |
| **34** | 0.9762 | 0.9611 | 0.9708 | 0.9591 |
| 35 | 0.9734 | 0.9587 | 0.9675 | 0.9567 |

## 4. 推理用法

```bash
# 对特征分片打分（Qwen3-8B 用 --feature-name default）
python standalone_score.py \
    --checkpoint checkpoints/broad/arch_linear__feat_single_layer__layer_34__concat_3__lr_0p0001__ep_5/models/best_layer_34.pt \
    --feature-root <trace_root> --feature-name default --grid-point <gp_id> \
    [--labels <trace_root>/labels/risk_faced/labels.jsonl] [--output probs.jsonl]
```

公式：`p = sigmoid(((x - mean) / std) @ W + b)`，x 为上述位置的残差流，threshold 0.5。

## 5. 数据位置（源机器仓库内，不随包分发）

特征 `results/probe_traces/v2/agentdojo-20260430T015534Z-qwen3-8b-dp4/features/default/`；标签 `.../labels/risk_faced/labels.jsonl`；
决策点 `.../grid_points/<gp>/`；四设定其余探针
`.../probes/{narrow,expand_suite,expand_suite_attack}_zero_val_final_ep5/`（固定 layer 34）。

## 6. 验证记录（2026-09-11，源机器）

checkpoint 均为 `fyh.probe_checkpoint.v2`；`standalone_score.py` 与生产
`BatchedProbePredictor` 在真实特征分片上逐位一致（见构建日志）。
