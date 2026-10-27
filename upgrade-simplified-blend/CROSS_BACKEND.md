# 跨后端数值验证（未执行，待在有 GPU 的地方做）

handoff §验收3 明确要求：雨桐那套 InScope / FP8 kernel 与训练侧 featurizer 不同，
**同输入 logit 已观察到差约 1**，不能假定 bitwise parity，也不能据此重调阈值。

本地已完成的部分（CPU，用冻结缓存特征）：

| id | 本地复算 | 缓存/期望 | Δ |
| --- | --- | --- | --- |
| oracle_0 | −18.293034 | −18.293036 | 2.4e-06 |
| oracle_1 | +21.209938 | +21.209938 | 4.9e-08 |
| oracle_2 | −15.668348 | −15.668346 | 2.3e-06 |
| oracle_3 | +30.563431 | +30.563429 | 1.8e-06 |

20 条 audit 用例最大偏差 `5.25e-06`。**这只证明我移植的 composer + detector 数学对，
不证明 InScope engine 吐出来的特征与训练 featurizer 一致。**

## 必须在真实后端上做的三步

### 1. 起一个隔离实例（不要动现有 30000）

```bash
# 另开端口，避免影响线上
CUDA_VISIBLE_DEVICES=7 SGLANG_API_KEY=<your-key> \
python -m sglang.launch_server \
    --model-path /path/Qwen3-8B-FP8 \
    --port 30001 \
    --served-model-name Qwen3-8B-FP8
```

显存参考：一个 8B-FP8 实例约占 15–30 GiB。当前 7 卡仅剩约 113 GiB 空闲，
起之前先 `nvidia-smi` 确认，别挤掉线上服务。

### 2. 让 API 指向新实例并逐条对比

```bash
BACKEND_URL=http://127.0.0.1:30001 \
DETECTOR_DIR=/mnt/kpfs_qyang/djs/ipi-doom/results/ladder-merged-blend-growth1-20261022/cells/A5_n2097152/models \
MODEL_PATH=/path/Qwen3-8B-FP8 \
SHADOW_API_KEY=<your-key> \
python -m uvicorn shadow_server.app:create_app --factory --port 8303
```

再跑对比脚本（只读，不改阈值）：

```bash
python compare_backend.py --service http://127.0.0.1:8303
```

输出会给出每个 oracle 的 `local_logit` / `service_logit` / `Δ`，以及 |Δ| 中位数与最大值。

### 3. 判读标准（照 handoff，不要自己发明）

- **不要**因为 Δ 落在阈值附近就调阈值。
- **不要**假设原阈值仍等效。
- 应回到**固定 validation** 上用该后端的特征重算 FPR / recall，再决定部署用哪个 seed 和阈值。
- 已标定的三个阈值（logit）：seed42 `2.3247954845428467`、seed43 `1.7843475341796875`、
  seed44 `2.0362582206726074`。这些数值与 `results.json` 逐位一致，但**只在训练侧特征上标定过**。

## 关于「pooled validation FPR ≤ 1%」

handoff 这么写，但用 `results.json` 的混淆矩阵实算**对不上**，别照抄进文档：

| split | 阈值 2.3248 下实测 FPR | recall |
| --- | --- | --- |
| validation（10 数据集求和） | 2.3718% | 96.6507% |
| test（n=1,448,465） | 1.0633% | 95.5937% |
| extra80k（n=80,000） | 1.8550% | 95.6925% |

单数据集差异更大：LiteCoder-Terminal-SFT 11.6%，AgentDojo-remote 0%。

而且 `threshold_logit` 与各数据集的 `threshold_at_1pct_fpr` 是**两个不同的量**
（后者 seed42 在 10 个数据集上从 −8.233 到 13.987 不等）。

所以 `/info` 里我写的是
`threshold_calibration: frozen_A5_cell_seed_thresholds_non_merged_config`，
附一句说明 FPR 随 split 变化、不要假定 1%。**如果雨桐那边认为标定口径确实是 1% FPR，
需要他们给出对应的计算方式**，我这边按 `results.json` 复现不出来。

## 已经能自证的旁证

用 `blend-seed4X.pt` 里冻结的 `extra80k` logits，按各 seed 阈值判正例，
预测数与 `results.json` 的 `tp+fp` **逐 seed 完全一致**：

| seed | 预测正例 | 报告 tp+fp |
| --- | --- | --- |
| 42 | 39019 | 39019 |
| 43 | 38701 | 38701 |
| 44 | 38918 | 38918 |

说明权重加载、两支混合数学、阈值表三者自洽。
