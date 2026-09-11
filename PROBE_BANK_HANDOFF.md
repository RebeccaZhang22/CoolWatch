# Qwen3.5-2B 影子模型接入（2026-09-10）

最新并发部署：已改为有界异步 microbatch，最多 64 请求/批、65,536 tokens/批；不再使用单请求全局锁串行推理。参数、64 并发实测及边界见 [PROBE_CONCURRENCY_DEPLOYMENT.md](PROBE_CONCURRENCY_DEPLOYMENT.md)。下文涉及串行/spool 的旧描述以新部署文档为准。

## 当前部署：统一 Prompt Leakage（v3）

- 按用户要求，将 `/share/workspace/zyt/agent-guard/analysis/protected_asset_theft_v3_qwen35_2b/probe/best_probe.pt` **移动**到本项目根目录 `best_probe.pt`；源位置不再保留文件。SHA-256 前后一致：`f49b1ce1ee2e1d743276484a3e99a52b01d157c2f75c39244f4e4d445eaf39dd`。文件已忽略，不提交私有权重。
- **当前三领域**：`harmful`、`prompt_leakage`、`ipi`。原 `rag_leak` / `sys_leak` 四条 entry 停用，替换为一个 `prompt_leakage/unified-v3`；不是合并旧分数，也不是先分类 query 再分流。
- 四条实际 entry：harmful/m1、harmful/m2、ipi/broad-l7、prompt_leakage/unified-v3。共享同一次真实请求 prefill，层位为 HF8/15/24。
- 泄漏 checkpoint 使用 zero-based decoder block 14（HF15）完整 residual 输出、T-1；标准化 → 无 affine LayerNorm → 2048/64/32/1 GELU MLP → sigmoid。保留 checkpoint logit 阈值 1.5230267643928528（概率 0.8209837546905241）。IPI 仍是 HF8、T-3、阈值 0.5；harmful 不变。
- 标签覆盖 system prompt、RAG、私有 CoT、Skill/tool 窃取意图，不代表实际泄漏成功。对外统一命名 Prompt Leakage。
- 样例实测 prompt_leakage：safe_zh 0.0000871；sys_zh 0.999432；rag_zh 0.999997；safe_en 0.0000174；理财原句加参考 system 为 0.000535。七个样例判定通过；CPU MLP 与源项目评分逐项一致。harmful/IPI 四组旧新服务分数差 <1e-4。
- 启动脚本默认读取根目录权重，可用 `LEAKAGE_PROBE_CHECKPOINT` 覆盖。`/bank` 返回 checkpoint SHA、取样位置与新三领域阈值；SDK 消费方须将旧两类字段替换成 `prompt_leakage`。历史日志保留原字段并标注“历史”。
- 回归：`regression/probe_leakage_smoke.py --url http://127.0.0.1:8302`。本节之后的四领域/七条 entry 及旧 bank 数据仅为历史，不描述当前部署。

## 历史变更：替换 IPI 为 broad layer-7

- 使用用户提供的 `/ssd/workspace/djs/zhuanli/probe_pkg_test/01-qwen3_5_2b_broad_probes_20260910.zip` 中 `best_layer_07.pt`；SHA-256：`46a68d047148be0b6ccf485be3a55966937533adfb5b9c7c01e0984982a057b4`，启动时核对包内 audit。
- 原 IPI M1/M2 已移除，替换成 `ipi/broad-l7`；其余三个领域的六个 entry 保持不变。当前共四个领域、七个 entry，共享一次真实请求 prefill（另有 upstream 的 dummy flush）。
- broad 训练集 38,402 条（9,561 正 / 28,841 负），AgentDojo `risk_faced` 标签；线性分类器，standard normalization，lr=1e-4、5 epochs、batch=64、seed=42。详见包内 HANDOFF.md。
- 新 IPI 使用 decoder index 7 / HF hidden_states[8]，关闭 thinking 的完整模板 T-3。SGLang hook 必须把 `(hidden, residual)` 相加才能匹配 HF 层输出；其他三个领域保留其既有取样方式。
- 使用 checkpoint 自带均值/标准差、权重和 bias，sigmoid 后与原阈值 0.5 比较，不做旧 Gaussian CDF，也不取旧 IPI M1/M2 最大值。四个领域仍独立运行，任一 flagged 就 block；无需 risk_types。
- GPU 0 上 BF16 实测：hi=0.001165、默认 system+hello=0.006248、包内 tool injection=0.696135、clean tool=0.306407。对应包内 FP32 参考后面三项约 0.0061/0.6764/0.3328；数值不完全相同，但这些样例阈值判定一致，不代表泛化效果保证。四组样例其他三个领域与旧服务分数差 <1e-4。
- 回归脚本：`regression/probe_broad_smoke.py --fixtures <解压参考脚本目录> --url http://127.0.0.1:8302 --baseline ''`（使用原项目 `.venv-sglang/bin/python`）。
- 下文训练、阈值、误报统计中的 IPI 均为旧 bank 历史记录，不适用于新 broad probe。

## 资产与部署

- 原项目：`/ssd/workspace/djs/zhuanli`（私有，未复制、提交或公开 bank/权重/数据）。
- 模型：`/ssd/workspace/djs/models/Qwen3.5-2B`，tag `qwen35-2b`。
- Bank：`/ssd/workspace/djs/zhuanli/results/bank/bank_qwen35-2b.json`。
- Bank SHA-256：`f8cf4ca9e130f044f55071c80da614df242086245561da4e2186c3cd7840774a`。
- GPU 0 / TP 1；max_len 16384；mem_fraction_static 0.2；本地端口 8302。
- 启动：`bash vllm_setups/run_probe_bank_qwen35_2b.sh`，使用原项目 `.venv-sglang`。
- 每次启动独立 spool；bank、模型 hidden/layers、8 条 entry 在加载时校验。
- GET `/bank` 查看元信息，GET `/v1/models` 供影子模型健康检查，POST `/detect` 返回四风险与七条 probe 分数。
- 原始 bank 文件不改动；在私有 runtime 目录构建混合 bank。服务单并发串行访问 spool。
- 公共接口 `/v1/moderations` 不需要 risk_types。完整 messages、tool_calls、tools 传入同一次预填充，返回 per_risk、per_entry、triggered_entries 和真实 tokenizer 用量。
- 聊天输入与工具返回后均检测；旧 8B SafeGauge 不适用于 2B，银行模式中从可用防护清单去除。

## 训练数据（来自原项目 build_datasets.py 与 data/provenance.json）

| 领域 | 样本 | 来源 |
|---|---:|---|
| harmful | 508：208 正、300 负 | AgentHarm test_public+validation，52 唯一行为的 4 变体；负例是另构造的 10 领域×30 良性任务，并非官方 benign 集 |
| rag_leak | 1900：950 正、950 负 | LeakGauge rag.lma / rag.raccoon 攻击，scifact、nfcorpus、fiqa、enronmail、wikitext 五语料；负例无放回 |
| sys_leak | 2400：1200 正、1200 负 | awesome-chatgpt-prompts 搭配 LeakGauge sys.lma / sys.raccoon；负例为官方 wikitext 问句 |
| ipi | 4934：1645 正、3289 负 | IPI-exposure-signal 管线采集 Qwen3.5-2B 的 AgentDojo 轨迹；6 攻击簇与 clean，标签为 risk_faced |

IPI 标签表示风险暴露，不等同于攻击成功。RAG 数据把 context 与 question 放进 user 消息；本产品 RAG 是 tool 消息，属于需要另外验证的分布迁移。

## Bank 实际编译过程

参见原项目 `framework/safety_probe/common.py`、`train_eval.py`、`bank_train.py`：

1. 基础模型保持冻结，抽取关闭 thinking 后 generation prompt 末 token 的隐藏状态。
2. 按攻击模板/领域簇切分 60/20/20；seed 11–15；IPI 正负共享簇保持同 split。
3. Bank 层位按 5 seeds 的 M2 验证 AUROC 均值选优，同风险 M1/M2 共用层。实际 entry 只在 seed-11 train 上拟合。
4. M1：训练集标准化 + balanced LogisticRegression，C=1，max_iter=3000。
5. M2：正负隐藏状态均值差方向归一化；bank 部署时对逐维标准化向量线性投影。它与 train_eval.py 报告用的余弦投影不是完全同一打分公式，评估应以部署 bank 为准。
6. 每条 probe 的原始分数用四领域验证负例池均值/标准差做 Gaussian CDF 校准。
7. 同一领域 M1/M2 的校准分数取 max；balanced 阈值取混合验证负例分数 95% 分位数。它不保证每个领域的新数据误报率都为 5%。

| 领域 | tap layer | balanced 阈值 |
|---|---:|---:|
| harmful | 24 | 0.9280345752 |
| rag_leak | 18 | 0.9191384521 |
| sys_leak | 2 | 0.9216641889 |
| ipi | 6 | 0.9817483804 |

校准分数不是风险发生概率；不同领域应分别检查自己的 flagged 和阈值。

## 真实端到端验证

原 bank，seed-11 test，RandomState(0) 无放回抽样，每领域最多 200 条；HTTP `/detect`，完整 tools，16384 上限。
初次验证在 GPU 4 完成，随后按用户要求迁至 GPU 0；迁移后另跑短文本与工具轨迹一致性检查。

| 领域 | n | AUROC | FPR | TPR |
|---|---:|---:|---:|---:|
| harmful | 84 | 0.9944 | 0.00% | 83.33% |
| rag_leak | 200 | 1.0000 | 0.00% | 43.94% |
| sys_leak | 200 | 1.0000 | 0.00% | 34.62% |
| ipi | 200 | 0.9618 | 20.61% | 100.00% |

这不是独立外部审计：bank 层位跨 5 个 seed 的验证集选择，seed-11 test 可能参与其他 seed 的选层。不能把表格当作完全未见数据上的泛化保证。

复现：原项目 `.venv/bin/python regression/probe_bank_validation.py --source-root /ssd/workspace/djs/zhuanli --n 200 --output .runtime/probe-bank-2b/validation.json`（在本项目目录执行）。
验证输出：`.runtime/probe-bank-2b/validation.json` / `validation.log`。
原项目网关测试：`PYTHONPATH=src .venv/bin/python -m pytest tests/guard/test_api.py -q`，14 passed。
本项目真实 bank → API（测试鉴权，不写真实账本）→ Python SDK schema：通过；工具调用字段保留。

## 已知边界

- 短文本上的跨领域误报确实存在。单句“输出 system prompt”未命中 sys_leak，却命中了 harmful/ipi；不要用 overall 替代目标领域的评价。
- 默认阈值的 RAG/sys 召回偏低，IPI 误报偏高；保持训练方 bank 不变，没有重训或偷偷调阈值。
- HTTP 服务超过 16384 tokens 返回 413，不静默截断。底层 extractor 模板与训练一致，thinking=False，尾部为 `</think>\n\n`。
- 本部署依赖私有原项目及其环境；不是包含模型资产的独立分发包。
- 旧 8013 端口 Qwen3-8B 影子进程已按用户授权通过 `sudo -n kill -TERM 307834` 停止，释放约 26 GiB 显存。GPU 0 上仅保留本次部署的 2B 影子模型（约 12 GiB）；8104 端口业务模型保持运行。
