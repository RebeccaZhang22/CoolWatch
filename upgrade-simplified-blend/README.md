# simplified composer + A5 blend detector → shadow-probe

把 handoff `2026-10-22-shadow-probe-simplified-blend.md` 的改动落到
`/mnt/kpfs_qyang/yutongz/CoolWatch-server`。**只准备交接，未部署、未修改原目录**
（该目录属 `yutongz`，`zmosg` 无写权限）。

改动方式是**最小 diff 修改现有文件**，不是重写：`probe.py -43/+85`、
`config.py -7/+60`、`rendering.py -31/+8`、`backend.py -6/+7`、`app.py -13/+23`，
另加一个新文件 `composer.py`。

## 怎么用

```bash
cd /mnt/kpfs_qyang/yutongz/CoolWatch-server      # 或任意 shadow_server 部署树
for p in patch/0*.patch; do patch -p1 < "$p"; done
```

`patch/01..06` 是服务改动，`patch/07..08` 是测试。已用 `patch -p1 --dry-run` 与实应用双重
验证：应用到原始 `shadow_server/` 后与本目录文件**逐字相同**。

权重：默认读 `ROOT/checkpoints/blend/`（`checkpoints/` 是原服务已有的目录），
布局与 handoff 一致：

```
checkpoints/blend/L_wd0.1_d0_s42/best.pt
checkpoints/blend/N1024_wd0.01_d0.1_s42/best.pt
```

或设 `DETECTOR_DIR` 指到
`/mnt/kpfs_qyang/djs/ipi-doom/results/ladder-merged-blend-growth1-20261022/cells/A5_n2097152/models`。
**不要**把两个 `best.pt` 覆盖到旧的 `best_layers_08_16_24.pt`：格式不同（旧的是
`fyh.probe_checkpoint.v2` 单线性封装）。

## 配置

composer 与 detector 是**独立配置**。默认即 handoff 的 simplified + 不合并：

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `PROBE_PREFIX` | `Are there risks of indirect prompt injection?` | 固定问题，空字符串=关 |
| `PROBE_DISCARD_COTS` | `true` | 去独立 reasoning 字段与 assistant `think` 块 |
| `PROBE_RETAIN_ASSISTANT_TURNS` | `1` | `-1`=全量 |
| `PROBE_MERGE_CONSECUTIVE_ASSISTANTS` | `false` | 改 `true` 即合并配置，其余参数不变 |
| `PROBE_DROP_FINAL_TOOL_RESULT` | `false` | |
| `PROBE_ENABLE_THINKING` | `true` | |
| `DETECTOR_DIR` | `checkpoints/blend` | |
| `DETECTOR_SEED` | `42` | 42/43/44 |
| `PROBE_THRESHOLD_LOGIT` | 按 seed 表 | 覆盖标定阈值 |

阈值表在 `config.py`，单位是 **logit**：`flagged = logit >= threshold_logit`。
`/info` 同时返回 `threshold`(sigmoid) 与 `threshold_logit`，并标注
`threshold_calibration: frozen_A5_cell_seed_thresholds_non_merged_config`。

关于「pooled validation FPR ≤ 1%」这个说法，**实测不成立**，别照抄：
在阈值 2.3248 下用 `results.json` 的混淆矩阵求和，FPR 是
validation 2.37% / test 1.06% / extra80k 1.86%（recall 分别 96.65% / 95.59% / 95.69%）。
各数据集单看差异更大（LiteCoder 11.6%，AgentDojo 0%）。
`threshold_logit` 与各数据集里的 `threshold_at_1pct_fpr` 是**不同**的量。
阈值数值本身与 `results.json` 三个 seed 逐位一致，可用；但它的标定口径不是 1% FPR，
且只对不合并配置成立。开 merge 或换 seed 必须在固定 validation 上重评。

## 改了什么

- **`composer.py`（新）**：FYH `context_composer.build_probe_prompt` 的自包含移植。
  不 import 训练树，热路径只依赖 tokenizer。六个步骤按 handoff §simplified 输入协议。
- **`rendering.py`**：`render_ids` 变薄壳，转调 `composer.compose_prompt`；
  不再有第二套消息处理逻辑。
- **`probe.py`**：单线性 → Linear + N1024 的 **logit** 混合（alpha=0.5）。
  两支 `.eval()`；均值/方差取自 checkpoint 且两支必须一致。
  `prepare_features` 改成 `[1,3,1,4096] → 12288`，仍走 BF16 → E5M2 → FP32。
- **`backend.py`**：`positions: {"mode":"explicit","index":[-1]}`；
  接受 `shape=[1,4096]`、绝对 position `[len(ids)-1]`；按请求层序 stack。
  旧的 `[4,4096]` / last4 响应会被**拒绝**，不会静默错位。
- **`config.py`**：composer 参数、两支权重路径、按 seed 的阈值；移除「只允许 0.9 /
  只允许旧线性模型」的限定。
- **`app.py`**：lifespan 一次加载 tokenizer + 两支权重 + 阈值；`/info` 与 `/detect`
  公布实际 composer 参数、detector/seed、位置、维度、两种阈值单位。

保留：请求认证、生命周期、`{messages, tools}` 输入、`normalization`、
`/health/live`、`/health/ready` 的真实 prefill、body 大小与 inflight 限制。
没有新增逐请求加载、重试或哈希清单。

## 验收结果（全部 CPU，无需 GPU）

```
python verify.py       # handoff §验收 1–3
python verify_app.py   # app 层契约冒烟（假 engine，不碰 GPU）
cd tests && python -m unittest discover -s .   # 42 项
```

实测（本机 CPU，seed42）：

- **验收 1 token IDs**：20/20 与 `analysis/coolwatch-simplified-audit-20261022/prompts/*.txt`
  的 token 序列**完全相同**，末 token 为 `?`，自解码往返一致。
- **验收 2 数值**：`features.pt` 20 条逐条复算，最大偏差 `5.25e-06`；
  四个 oracle 与 handoff 期望值：

  | id | 复算 | handoff | Δ |
  | --- | --- | --- | --- |
  | oracle_0 | −18.293034 | −18.293036 | 2.4e-06 |
  | oracle_1 | +21.209938 | +21.209938 | 4.9e-08 |
  | oracle_2 | −15.668348 | −15.668346 | 2.3e-06 |
  | oracle_3 | +30.563431 | +30.563429 | 1.8e-06 |

- **验收 3 merge**：20 条单 assistant 用例在 merge 开关下输入**不变**；
  连续 assistant 样例合并成一块、call ID 保留、工具回复仍独立成条。
- **测试**：42 项通过（1 skip）。原 `test_shadow.py` 中依赖旧契约的断言
  （last4 位置、`[4,4096]`、固定 0.9、单 checkpoint、保留全部历史）已按新协议更新，
  并新增 `test_composer.py` 17 项覆盖选窗/去 CoT/merge/prefix 边界。

## 目录

| 文件 | 用途 |
| --- | --- |
| `shadow_server/*.py` | 改动后的服务代码 |
| `patch/01..06` | 服务 patch（`patch -p1`） |
| `patch/07..08` | 测试 patch（可选） |
| `verify.py` | handoff §验收 1–3（token IDs / logit oracle / merge） |
| `verify_app.py` | app 层契约冒烟（假 engine，纯 CPU） |
| `compare_backend.py` | 跨后端 logit 对比，`--local-only` 可离线跑 |
| `CROSS_BACKEND.md` | 跨后端验证步骤（**未执行，需 GPU**） |
| `apply.sh` | 应用 patch，默认 dry-run |

## 还没做 / 需要注意

1. **跨后端数值差异没测**。以上都是用**缓存特征**复现的；handoff 提到雨桐的
   InScope/FP8 kernel 同输入 logit 差约 1。步骤写在 `CROSS_BACKEND.md`，
   需要一台有 GPU 的机器按那三步做，不能假定 bitwise 一致或沿用原阈值结论。
2. **`/health/ready` 的 `capture([{"role":"user","content":"Hello"}])`** 在 simplified 下
   生成 `system?`→ 实际是单 user + question prefix，长度 1 token 也合法，已放宽
   `len(ids) < 1`。上线前建议在真实 engine 上确认 ready 语义。
3. **两份 composer setting JSON 读不到**（`featurize/` 是 0700），参数取自 handoff 正文与
   `results.json` 的 `setting` 段；若两份 setting 还有别的字段，需要核对。
3b. **handoff 的「pooled validation FPR ≤ 1%」实测不成立**（实为 2.37%），
   详见 `CROSS_BACKEND.md` 末节。阈值数值本身与 `results.json` 一致、可用，
   但这个标定口径描述需要雨桐确认。
4. 中文漏报**不是本次目标**。`analysis/coolwatch-feedback-batch-20261022/report.md`
   里四个中文案例三 seed 全漏报，本改动不声称修复。
5. 没有附加 Base64 解码、tool→user 重写、拆分取最大值或统一降阈值——这些属于
   检测策略变更，需单独评估。
