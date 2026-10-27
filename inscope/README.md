# InScope

可解释的间接提示注入（IPI）检测：在固定注入问题上取模型激活的最后 token 特征，
用一个线性模型 + 一个小 MLP 的 logit 混合给出风险分。

本目录是把原本混在一起的 `shadow_server` 拆成**契约 / 服务 / 客户端**三部分后的结果。
**逻辑未改**：composer、normalization、rendering 与迁移前逐字节相同；
probe、backend、app 的改动只是把字面量换成契约引用。验收数值与迁移前完全一致
（见下）。

## 三个包

| 包 | 作用 | 依赖方向 |
| --- | --- | --- |
| `packages/inscope_contract` | 冻结契约：特征维度、层号、位置、阈值、端点、schema | 无（只依赖 pydantic） |
| `packages/inscope_server` | FastAPI 服务 + detector + composer | → contract |
| `packages/inscope_client` | HTTP 客户端 `inscope.Client` | → contract |

**只允许向下依赖。** 客户端不 import 服务端代码，服务端不 import 客户端；
两边都只认 `inscope_contract`。这就是「契约拆分」的落点：任何跨进程数值
（`input_dim`、`capture_layers`、`selected_positions`、阈值）只有一个定义。

## 跑起来

```bash
export INSCOPE_MODEL_PATH=/path/Qwen3-8B-FP8
export INSCOPE_API_KEY=<你的 key>
export INSCOPE_ENGINE_URL=http://127.0.0.1:30000
export INSCOPE_DETECTOR_DIR=/path/to/A5_n2097152/models
export INSCOPE_DETECTOR_SEED=42

inscope-serve --host 0.0.0.0 --port 8302
```

两个进程：本服务（CPU）+ `sglang.launch_server`（GPU，`INSCOPE_ENGINE_URL` 指向它）。
服务启动时会 `GET /info` 校验 engine 的模型路径与 `qwen3` 架构，不一致直接拒绝，
不会带着错模型跑。

客户端：

```python
from inscope import Client

client = Client("http://127.0.0.1:8302", api_key="...")
result = client.detect([{"role": "user", "content": "..."}])
result.flagged, result.logit, result.threshold_logit
```

## 环境变量

全部以 `INSCOPE_` 为前缀。旧的 `SHADOW_*` / `PROBE_*` / `DETECTOR_*` / `BACKEND_URL`
**不再读取**，部署时要一起改。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INSCOPE_MODEL_PATH` | 必填 | Qwen3-8B-FP8 本地权重 |
| `INSCOPE_API_KEY` | 必填 | API Bearer token |
| `INSCOPE_ENGINE_URL` | `http://127.0.0.1:30000` | SGLang engine |
| `INSCOPE_DETECTOR_DIR` | `<repo>/checkpoints/blend` | 两支权重所在目录 |
| `INSCOPE_DETECTOR_SEED` | `42` | 42 / 43 / 44 |
| `INSCOPE_THRESHOLD_LOGIT` | 按 seed 表 | 覆盖标定阈值（logit 空间） |
| `INSCOPE_PROBE_PREFIX` | 固定注入问题 | 空字符串=关闭 |
| `INSCOPE_DISCARD_COTS` | `true` | |
| `INSCOPE_RETAIN_ASSISTANT_TURNS` | `1` | `-1`=全量 |
| `INSCOPE_MERGE_CONSECUTIVE_ASSISTANTS` | `false` | |
| `INSCOPE_DROP_FINAL_TOOL_RESULT` | `false` | |
| `INSCOPE_ENABLE_THINKING` | `true` | |
| `INSCOPE_MAX_INPUT_TOKENS` | `40959` | 超限 413，不截断 |
| `INSCOPE_MAX_INFLIGHT` | `16` | 超出 429 |
| `INSCOPE_REQUEST_TIMEOUT` | `60` | 超时 504 |

## 契约红线

这些值改了就等于改协议，必须同步 engine、checkpoint 和文档，并重新标定阈值：

```
capture_layers   = (9, 17, 25)        # 源码 block 号 +1
block_indices    = (8, 16, 24)
selected_positions = (-1,)            # 问题前缀的最后一个 token
feature_shape    = (1, 3, 1, 4096)
input_dim        = 12288              # 3 × 1 × 4096
schema_version   = inscope.feature_capture.v1
site             = block_output
encoding         = float_list
quantization     = bfloat16 -> float8_e5m2 -> float32
```

detector：`z = 0.5·z_linear + 0.5·z_mlp`，`score = sigmoid(z)`，
`flagged = z >= threshold_logit`（**logit 空间比较**）。

阈值（logit）：seed42 `2.3247954845428467`、seed43 `1.7843475341796875`、
seed44 `2.0362582206726074`。只标定过 `merge=false` 配置。

## 验收

```bash
export PYTHONPATH=$PWD/packages/inscope_contract:$PWD/packages/inscope_server
python scripts/verify_contract_migration.py   # 迁移前后必须一致
python scripts/verify_app.py                  # 端点与响应契约
```

实测与迁移前**逐位相同**：token IDs 20/20、特征最大偏差 `5.25e-06`、
四个 oracle 偏差 ≤2.4e-06、阈值不变、merge 开关行为不变。

## 还没做

1. **跨后端数值未验证**。以上都基于冻结缓存特征。InScope/FP8 kernel 与训练侧
   featurizer 同输入 logit 差可达约 1，必须在真实后端上复核，不能假定 bitwise 一致。
2. **阈值标定口径待确认**。原文档写「pooled validation FPR ≤ 1%」，但用
   `results.json` 混淆矩阵实算为 2.37%（test 1.06%、extra80k 1.86%），
   且 `threshold_logit` 与各数据集的 `threshold_at_1pct_fpr` 是两个不同的量。
   阈值数值本身可用，但这个描述需要雨桐确认。
3. **未提交**。当前是修改阶段，`git status` 里 `inscope/` 仍是未跟踪目录。
