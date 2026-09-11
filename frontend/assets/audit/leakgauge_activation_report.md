# Prompt Leakage Activation Probe on LeakGauge Demo

## 结论

当前 `probe/prompt_leakage/best_probe.pt` 在 LeakGauge `sys_mixed/unseen_all`
上的迁移测试结果较好：攻击样本 TPR 为 **96.88%**，正常样本 FPR 为
**1.24%**，AUROC 为 **0.9977**。在固定阈值下，整体 F1 为 **0.9782**。

这说明该 probe 对这批 system-prompt extraction 攻击有较强区分能力；但这
是跨数据集/跨方法的迁移评估，不是原始训练集上的官方复现结果。

同一 checkpoint 在 LeakGauge `rag_mixed/unseen_all` 上也完成了测试：RAG
攻击 TPR 为 **95.88%**，benign FPR 为 **0.00%**，AUROC 为 **1.0000**，F1
为 **0.9789**。这说明它对本批 RAG context extraction 数据也有较强迁移
能力，但 RAG 结果不能与 system-prompt 结果直接合并解读。

## 测试范围

- 数据：`.other/leakgauge/data_input/sys_mixed/`
- split：`unseen_all`
- attack：1,600 条
- benign：1,536 条
- 总计：3,136 条
- 数据来源：LeakGauge demo 的 system-prompt 数据，经其
  `scripts/data_prepare.py --mode sys --large` 生成
- 被测 checkpoint：`probe/prompt_leakage/best_probe.pt`
- 推理服务：本项目 Probe Bank，Qwen3.5-2B，GPU 0，HTTP `127.0.0.1:8302`
- Prompt leakage threshold：`0.8209837546905241`

## 指标

| 指标 | 结果 |
|---|---:|
| TP | 1,550 |
| FN | 50 |
| TN | 1,517 |
| FP | 19 |
| Accuracy | 97.80% |
| Precision | 98.79% |
| Recall / TPR | 96.88% |
| FPR | 1.24% |
| F1 | 97.82% |
| AUROC | 0.9977 |

## RAG `unseen_all` 结果

- 数据：`.other/leakgauge/data_input/rag_mixed/`
- attack：4,800 条；benign：2,400 条；总计 7,200 条
- TP：4,602；FN：198；TN：2,400；FP：0
- Accuracy：97.25%
- Precision：100.00%
- Recall / TPR：95.88%
- FPR：0.00%
- F1：97.89%
- AUROC：1.0000
- 攻击平均 score：0.9727；benign 平均 score：0.0003

## 运行复现

启动 Probe Bank：

```bash
CUDA_VISIBLE_DEVICES=0 bash vllm_setups/run_probe_bank_qwen35_2b.sh
```

运行评估：

```bash
python .other/run_leakgauge_demo_eval.py \
  --data-dir .other/leakgauge/data_input/sys_mixed \
  --backend probe_bank \
  --base-url http://127.0.0.1:8302 \
  --splits unseen_all \
  --output-dir .other/leakgauge_eval_activation
```

逐样本结果在 `.other/leakgauge_eval_activation/predictions.jsonl`，汇总在
`.other/leakgauge_eval_activation/summary.json`。

## 解释与限制

1. 该 checkpoint 是 Qwen3.5-2B hidden-state activation probe；它不是
   LeakGauge/SafeGauge 的 suffix-logprob probe。
2. LeakGauge demo 的 `unseen_all` 只是公开 demo 数据上的 holdout 组合，不能
   代替严格的论文 test split。
3. 当前结果使用 checkpoint 已保存的固定阈值，没有在 LeakGauge 数据上重新
   调阈值，因此更接近真实迁移测试。
4. system 与 RAG 结果使用不同的数据构造和隐私目标，已在本报告中分节
   展示，不能把两者简单合并成一个指标。
