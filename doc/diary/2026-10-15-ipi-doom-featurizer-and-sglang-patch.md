# ipi-doom featurizer / SGLang patch 完整交接（2026-10-15）

本交接面向把 **Qwen3-8B featurizer 和 SGLang patch** 集成到其他项目的人。
配套包：`ipi_doom_featurizer_bundle_2026-10-15.zip`。解压后保留目录结构；
运行手册见 [docs/featurize.md](../docs/featurize.md)，打包清单见包内 `metadata/file-list.txt`。

## 1. 当前交付范围和来源

本版本只有一个后端：**独立 SGLang FeatureServer + ZMQ client**。服务端持有
Qwen3-8B-FP8，客户端负责 prompt、并发和落盘；不包含 CLI 进程内启动 Engine 的
`sglang_direct` 后端，也不包含训练、标注、采集 pipeline 或原树的四卡实验编排脚本。

来源是 `follow-your-heart` 的 `2026-10-15-featurize-code-and-patch.md` 和同日 zip，
上游当时 HEAD 为 `2df78434a1e3b5abdc7a67f38e46400ff5701c02`，包还含该工作树的未提交修改。
旧命令中的 `--backend/--model-family/--num-gpus/--enable-split-saving` 已不适用，
本版不做模型族位置偏移，使用新的运行示例。原包保留为来源记录；**其他项目应使用本交接配套的 ipi-doom 包**，不要混入原包 CLI。
当前 ipi-doom 目录不是 Git checkout，不虚构本次交付的 commit ID。

本包源码自包含，没有指向原项目的源码 symlink/import/PYTHONPATH。Python/GPU/CUDA、
SGLang wheel、模型权重、输入数据和虚拟环境不在源码包内。

相对原包的变化：裁掉训练/标注/多模型和第二后端依赖；补齐本地 Python 闭包；
默认使用项目内 `.venv-featurize`；显式 `--retokenize` 支持其他模型采集的轨迹；
prompt 渲染异常不再静默跳过；合并 ZMQ response 只解析一次原始 tensor；
writer 有界异步落盘、完整 ID 行提交恢复；默认禁用 decode graphs；日志按约 1024 个样本汇报。

## 2. 先选集成边界：同一后端的两层接口

### 已有自己的 tokenizer、dataset 和 writer

只复用 `feature_protocol.py`、`sglang_remote_capture.py`、`hidden_states.py`，以及
服务端 `feature_server.py`、`feature_server_args.py` 和完整 patch。保留相应包的
`__init__.py`，或在新项目同步调整这些相对 import。客户端不需要 import SGLang/Engine。

下面是单批调用的最小接口；`token_ids` 必须属于**服务端同一个模型/tokenizer**。

```python
from types import SimpleNamespace
from follow_your_heart.probes.featurization.sglang_remote_capture import SGLangRemoteFeatureExtractor

# tokenizer/messages/tools 由宿主提供；无工具时 tools=[]。显式选 thinking 模式。
token_ids = tokenizer.apply_chat_template(
    messages, tools=tools, tokenize=True, add_generation_prompt=True,
    enable_thinking=True,  # 对应下方 CLI 示例的 FYH_ENABLE_THINKING=1
)
prompt = SimpleNamespace(token_ids=tuple(token_ids), decode_start_index=len(token_ids))
with SGLangRemoteFeatureExtractor(
    endpoint="ipc:///tmp/your-feature.sock",
    layer_ids=(4, 8, 12, 16, 20, 24, 28),
    selected_positions=(-1,),
    capture_dtype="bfloat16",
) as extractor:
    handle = extractor.submit([prompt])
    results = extractor.loop.run_until_complete(handle["task"])
    capture, = extractor.collect_results(handle, results)
    # capture.hidden_states: tuple of [positions, hidden] CPU tensors, one per layer
```

`submit()` 只排 task，**不会自己驱动 event loop**。上面是同步调用接口，拥有独立 loop；
若宿主已运行 asyncio loop，应按该接口重新接入宿主异步协调器，而非嵌套 run_until_complete。
高吞吐时保持一个 extractor/连接存活，持续 submit 并驱动 loop；不要每个请求重建 socket。
不需要使用本项目的 schema 或文件布局。

### 直接复用 prompt builder、CLI、流式协调器和 append store

带齐配套 zip 的 **19 个 Python 文件**，不要只复制 `probes/`：

- `follow_your_heart/__init__.py`。
- `probes/{__init__.py,cli.py,utils.py}` 和整个 `probes/featurization/`。
- `runtime/{__init__.py,message_content.py,reasoning.py}`。
- `data_collection/{__init__.py,schema.py,decision_points.py,injection_text.py}`。

`data_collection.schema` 的 import 会先执行包 `__init__`，后者 eager import
`decision_points` 和 `injection_text`；这两个文件即使不直接调用也不能漏。
`runtime/__init__.py` 的其他导出是 lazy，不需要把采集 client、AgentDojo vendor 或训练模块带来。

全链路：

```text
CLI 扫描排序 grid points，逐点读取源 JSONL
 → DecisionPointRecord → CPU producer 渲染/按真实长度过滤
 → SGLangRemoteFeatureExtractor：持久 DEALER，按 RID 分派返回
 → FeatureServer：ROUTER → Engine.async_generate(feature-only prefill)
 → SGLang typed feature output → raw tensor rows
 → 单 writer 线程 → L*.bin + ids.jsonl → 原子 manifest.json
```

这是逐 **grid point** 流式，不是整个源文件逐行恒定内存：一个 point 的源行和
DecisionPointRecord 仍全部读入内存，不跨 point 预加载。

## 3. 环境和最短启动步骤

限定 **Linux、Python 3.12、SGLang 0.5.18、Qwen3-8B-FP8**。
当前 GPU smoke 只验证了单 GPU、TP=1；不要扩张为 TP>1、PP 或其他模型已验证。

在解压目录执行：

```bash
uv venv --python 3.12 .venv-featurize
uv pip install --python .venv-featurize/bin/python 'sglang==0.5.18' pytest
.venv-featurize/bin/python patches/sglang-0.5.18-fyh-direct/apply.py

# 选择可用 GPU，并在外部机器改成本机权重路径。
export FYH_FEATURE_GPU=0
export FYH_FEATURE_MODEL=/absolute/path/to/Qwen3-8B-FP8
scripts/run_qwen3_feature_server.sh start
scripts/run_qwen3_feature_server.sh status
# ready: yes 后再启动；IPC socket 出现只表示已经 bind，不是独立 health RPC。

FYH_ENABLE_THINKING=1 scripts/featurize.sh start \
  --root /absolute/path/to/frozen-traces \
  --feature-name qwen3_8b_prefix_cot \
  --retokenize \
  --probe-prefix 'Are there risks of indirect prompt injection?' \
  --layer-ids 4 8 12 16 20 24 28
scripts/featurize.sh status
scripts/featurize.sh stop
scripts/run_qwen3_feature_server.sh stop
```

SGLang 提供 torch、transformers、msgspec、pyzmq 等依赖。已使用的运行环境为
SGLang 0.5.18 / torch 2.13.0+cu130 / transformers 5.12.1 / msgspec 0.21.1 /
pyzmq 27.2.0。新空环境的 `uv pip install --dry-run 'sglang==0.5.18'` 已成功解析；
**未完成从新环境实际安装到 GPU 推理的一体化验证**。

不要把根目录基础环境与 SGLang 环境混为一谈：`pyproject.toml` 的 optional
`featurize` 是 client 依赖，不安装/patch SGLang；`uv sync --extra featurize` 不是
server 安装命令。脚本通过本地 PYTHONPATH 导入源码，无需 `pip install .`。

wrapper 默认 Python 为解压目录的 `.venv-featurize/bin/python`；
`FYH_SGLANG_PYTHON` 可显式指定其他**已匹配并打 patch**的 Python。
`FYH_SGLANG_ROOT` 是安装器的 **venv 根路径**，不是 site-packages 路径；
两者要指向同一个环境。日志在 `logs/<date>/`，状态在 `.runtime/`。

## 4. SGLang patch：必须完整迁移

目录名字 `sglang-0.5.18-fyh-direct` 是历史名字，不表示本交付还提供 direct 后端。
安装器原地覆盖下面 **13 个 runtime 文件**（相对 `sglang/srt/`）：

| 文件 | 必要作用 |
| --- | --- |
| `ftd_activation.py` | 解析 feature spec、capture 开关、512-token cache recompute 常量 |
| `models/qwen3.py` | 请求选层、选位置、dtype cast、CPU capture payload |
| `models/qwen2.py` | Qwen3Model 的实际父类 forward；抓残差、选行、提前停止 |
| `model_executor/model_runner.py` | capture 状态与 graph 路由 |
| `managers/io_struct.py` | SGLang 内部 typed FeatureRecord/FeatureBatchOutput |
| `managers/scheduler_components/batch_result_processor.py` | 保留中间 prefill chunk 的捕获行 |
| `managers/scheduler_components/output_streamer.py` | 合并 chunk、按请求位置重排、编码 raw batch |
| `managers/detokenizer_manager.py` | typed batch 透传 |
| `managers/tokenizer_manager.py` | 按 RID 完成 feature 请求 |
| `managers/scheduler.py` | feature-prefill 调度链路和快照已有修改 |
| `entrypoints/engine.py` | 服务端依赖的 Engine 生命周期和 shutdown |
| `model_executor/runner/prefill_cuda_graph_runner.py` | 固定 spec/bucket graph，selected-row 索引和 replay |
| `model_executor/runner_backend/breakable_cuda_graph_backend.py` | 按捕获行数分配 graph shared output buffer |

**只复制 runtime/ 仍不完整。** `apply.py` 另外对安装环境的 4 个文件做锚点编辑：

| 文件 | 修改与原因 |
| --- | --- |
| `managers/schedule_policy.py` | 限制 prefix cache match，不跳过所选位置及其重算前缀 |
| `managers/schedule_batch.py` | request 自身 prefix match 同样受限，两处都要修改 |
| `model_executor/forward_batch_info.py` | 携带完整 `origin_input_ids` 长度，负位置不能相对当前 chunk 解析 |
| `managers/tp_worker.py` | `fyh_feature_only` 时输入长度公式从 `max_req_len-5` 改为 `max_req_len+1` |

两处 cache 限制为 `max(0, earliest_selected_absolute_position - 511)`。
512-token 重算是当前实现策略，不是对所有 kernel/cache/graph 的数值等价保证。
普通无 graph 分支直接调用 `Engine(**engine_args)`；`fyh_feature_only=True` 只在
使用 `FeatureServerArgs` 的 graph 分支显式传入，不应宣称默认分支启用了 tp_worker 长度特例。

安装器固定写入 `<venv>/lib/python3.12/site-packages`；不安装 SGLang，也不自动校验其
版本。先复制 13 文件，再改锚点，**不是事务安装**。锚点不匹配时应停止使用该目标环境、
从匹配的专用环境重新安装；没有自动 rollback。不要覆盖承载其他项目修改的共享服务环境。
改变 patch 的相对位置时显式给 `FYH_SGLANG_ROOT`，不要依赖默认路径推导。

## 5. SGLang 内部请求契约与捕获数值语义

FeatureServer 内部的核心调用是：

```python
spec = request_key(request)
result = await engine.async_generate(
    input_ids=request.input_ids,
    rid=request.rid,
    extra_key=spec,
    sampling_params={"max_new_tokens": 0, "temperature": 0},
)
```

`extra_key` 必须为 `fyh-feature:` + JSON，只含
`layer_ids / selected_positions / capture_dtype`。**不要把 RID、完整 token IDs 或样本路径
塞进 spec**：否则相同规格的请求无法正常组 batch。token IDs 和 RID 已经是独立请求字段。

外部层号是 **0-based decoder block 输出残差**，不是 embedding=0 的 HF hidden_states
索引。Qwen3 wrapper 将它转为内部 `layer+1`；forward 抓 `hidden_states + residual`，
在最大所选层之后提前退出，不做最终 RMSNorm、LM head、sampling/decode。
即使选择最后一个 block，也不要把它当作最终 RMSNorm 后的 HF last_hidden_state。

位置非负为完整 prompt 的绝对 token 下标；负值为 `full_prompt_length + position`。
捕获按请求位置顺序输出；records 的 positions 保留请求值（包括负数），不是改写后的绝对下标。
层须非空严格递增，位置整数须非空、不重复；`0` 与 `-N` 等可能指向同一绝对位置，
协议只检查整数值唯一。高层 builder 检查位置越界；raw client/server 不提供完整的
模型层数/位置范围预检，调用者应给合法范围。

返回 dtype 只是捕获行的最后一次 cast。**FP32 transport 不表示 FP32 权重或中间计算**，
也不能恢复 FP8/BF16 已丢失的精度。存储 BF16 又会发生一次转换。

## 6. ZMQ wire contract 和错误行为

ROUTER/DEALER、MessagePack；不是 OpenAI HTTP endpoint。默认使用本地 IPC，
协议本身没有认证、加密或模型握手，部署边界由集成方提供。

请求 `FeaturePrefillRequest`：

| 字段 | 语义 |
| --- | --- |
| `rid` | 同一 FeatureServer 全部连接中、所有同时在途请求唯一；推荐 UUID，官方 client 已使用 UUID |
| `input_ids` | 已渲染/编码的完整非空 prompt token IDs |
| `selected_positions` | 有序位置 tuple，默认示例 `(-1,)` |
| `layer_ids` | 非空、严格递增的 0-based decoder block IDs |
| `capture_dtype` | `bfloat16` / `float16` / `float32` |

响应 `FeatureBatchOutput`：schema=`fyh.feature_batch.v1`，携带 `batch_seq/rids/records`、
`layer_ids`、`shape=(rows,layers,hidden)`、`dtype`、contiguous `hidden_bytes`。
每条 record 有 `rid,row_start,row_count,positions,complete`；按 row slice 取出对应样本。
SGLang 内部 typed structs 与对外 MessagePack structs 是两套类型，FeatureServer 在边界转换，
不要直接序列化内部对象替代外部协议。

结果可能乱序，且服务端可在约 1 ms 窗口把同一 DEALER 的多个完成结果合并发送。
按 **RID** 分发，不能依赖提交顺序、batch_seq 或“一次 recv 对应一个请求”。
当前 client 将每个合并 raw batch 解析一次，再将行视图分发给各 RID。
同一连接使用固定 capture spec；服务端合并输出要求 layers/dtype/hidden width 一致。

错误帧为 `b"fyh-error:" + UTF-8 message`，不携带 RID；收到后该连接的**全部 pending**失败。
渲染错误、收到的错误帧、反序列化错误和 writer 错误会令当前 point 失败，不写完成 manifest。
**没有 request timeout、重试、server 存活探测或模型一致性检查**；server 消失可能一直等。
CLI `--model` 只决定本地 tokenizer/config/输出标签，必须人工与服务端权重对应。

## 7. Prompt 构建：迁移最容易误用的部分

输入高层 schema 最少要能构建 DecisionPointRecord：`decision_index`、
`assistant_message_index`、`decision_point_id`、`trace_id`、`assistant_message`、
`replay_request_kind="openai_chat"`、`replay_request={messages,tools}`、可选 prompt IDs 和 metadata。
CLI 兼容已有扁平行的 `request_kind/request_payload`；详见 `schema.py:DecisionPointRecord.from_dict`。
原消息中的 tools、tool_call_id 和 tool_calls 都属于模板输入，不应只拼接纯文本对话。

- 默认 full、无 prefix/discard/retokenize、有 stored IDs：原样复用 IDs，**不验证 tokenizer**。
  返回 prompt.text 为空，不代表没有 prompt。
- 其他模型（包括当前 Qwen3.8）采集的轨迹必须显式 `--retokenize`：用 Qwen3-8B tokenizer
  重渲染 messages/tools、忽略 source IDs。这是在 Qwen3-8B 上做 forward，不是还原原模型隐层。
- Prefix 独立 `encode(add_special_tokens=False)`，直接拼在 canonical template 边界后；
  不是把 prefix 放回 messages 重套模板。默认 `-1` 指 prefix 最后一个 token。
- 非 retokenize 的 full prefix 模式检查 stored IDs 以 canonical IDs 开头，再截去其后
  已捕获的 assistant 尾部；不匹配报错。discard-CoT 可改变模板，允许使用重渲染结果。
- 模板 `add_generation_prompt=True`；只有 `FYH_ENABLE_THINKING=1` 开启 thinking，默认关闭。
  该开关只影响重新渲染，不影响 stored-ID fast path。
- `--discard-cots` 递归删 `reasoning/reasoning_content` 字段，**不删除 content 中的
  `<think>...</think>` 字符串**。
- compact 保留所有 system/user、最新一条 assistant、最新一条 tool，保持原顺序；
  **不是最后一个完整 tool-call group**。
- `--max-prompt-tokens` 按最终渲染长度过滤。`--max-points=N` 是每个 point 源文件前 N 条非空 JSON 记录。

## 8. 并发、cache 和 graph 配置

CPU producer 的渲染结果队列容量为 3；GPU 请求通过一条持久连接异步在途；
单 writer 线程约每 1024 个完成样本写一批，至多一批排队写入。
默认在途高/低水位是 `5242880 / 3145728` **输入 token 个数**，不是字节或吞吐率。
无其他 inflight 时单个超过水位的 prompt 仍放行，因此不是硬内存上限。

不要混淆三个层次：ZMQ transport batch、client inflight window、SGLang scheduler
`max_prefill_tokens`。服务端默认 max_prefill_tokens=262144、max_running_requests=2048、
max_queued_requests=8192；用 `FYH_MAX_PREFILL_TOKENS / FYH_MAX_RUNNING_REQUESTS /
FYH_MAX_QUEUED_REQUESTS` 调整。仅测到一个请求的日志不是满批吞吐证明。
服务端通过 active_spec 条件锁允许同 spec 并行，不同 spec 等待切换。

默认 radix cache 关、chunked_prefill_size=-1、decode/prefill CUDA graphs 关。
`FYH_FEATURE_RADIX_CACHE=1` 启用 cache；
`FYH_FEATURE_CHUNKED_PREFILL_SIZE` 设置 chunk size；
`FYH_FEATURE_CUDA_GRAPH=1` 启用 prefill graph，decode graph 仍关闭。
chunked prefill 需要同时包含中间 chunk 行保留、完整 prompt 长度、最终按 requested positions
重排这三个改动，缺一不可。

Graph specialization 固定 **layers + positions + dtype**，graph eligibility 会精确比较
整个 extra_key 字符串，并受 SGLang 原生条件限制。wrapper 暴露 graph layers/positions/buckets，
但其 graph dtype 默认 BF16；client FP32 capture 不会使用该 BF16 specialization。
若要创建 FP32 graph，使用 server CLI 的 `--graph-capture-dtype float32`。
`FYH_FEATURE_LAYERS` 的默认 graph 层为 4/8/12/16/20/24/28，CLI 默认捕获则是全部 32 层，
**不能把两者默认值当成相同**。显式传层。graph buckets 是 prefill token-shape 配置，
不是 client window。

多 server：每个实例都设独立 GPU、endpoint、`FYH_FEATURE_SERVER_STATE_DIR`，默认 server
状态目录不会随 GPU 改变。多 client：独立 `FYH_FEATURE_JOB`；避免两个 writer 写同一点。
权重默认路径是本机绝对路径，迁移机器必须设置 `FYH_FEATURE_MODEL`。

## 9. 存储、顺序、续跑与冻结输入

```text
<root>/grid_points/<point>/decision_points.jsonl
<root>/features/<feature-name>/<point>/
  L4.bin ... L28.bin       # raw BF16 [N, P, H]，每层单文件
  ids.jsonl               # 与每层样本轴严格对应的完成顺序
  shape.json              # hidden_size、rows_per_example
  config.json             # model/layers/positions/模板和过滤配置
  manifest.json           # 非空 point 的完成标记，最后原子 replace
```

实际保存顺序是**请求完成顺序**，不是源 JSONL 行序。按 `manifest.decision_point_ids`
或 ids.jsonl 连接 labels/源样本，不能靠行号。输出不生成任何 attack/safety labels。

每批先写全层 binary，再追加 IDs。完整、以换行结束的 ID 行是续跑提交边界。
恢复时截掉 ID 残缺末行及 binary 超出已提交数的尾部；已提交层丢失/过短报错。
没有 fsync，因此这是**进程中断恢复**语义，不承诺断电持久性。

未完成 point 会比较配置，变化时报错；**manifest 已存在时 CLI 在检查 config 前直接跳过**。
输入 root 应冻结；source 新增行、换模型/模板/位置/过滤条件均使用新 feature name。
空 point 或全部被长度过滤时不写完成 manifest，下次仍扫描。

reader `load_feature_payload(root, point, name, layer_indices=...)` 默认返回 FP32
`[N,L,P,H]`；指定 `position_index` 后返回 `[N,L,H]`，并同步缩小 selected_positions。
审计脚本按源非空行数检查数量覆盖、输出 IDs 内部唯一、样本数/位置和 binary 大小；
它不比较源 ID 集合，也不核对 manifest IDs 与 ids.jsonl 的顺序，不能单独证明样本身份对齐。
它不是内容哈希或数值对齐工具。
使用长度/数量过滤时，完整源覆盖审计自然不再适用。

## 10. 验证证据、未验证范围与验收步骤

已记录的验证：

| 项目 | 证据和范围 |
| --- | --- |
| 整个 ipi-doom tests（已有匹配 feature runtime） | 167 passed，6 个原有失败；原有失败是 test_client 四项与 collect_agentdojo_traces 两项 |
| 基础 uv 环境 tests | 141 passed，7 个 optional-dependency skips，同 6 个原有失败 |
| 本包八个聚焦测试 | 27 passed；解压目录独立运行，验证 Python 源码闭包 |
| CPU 集成测试 | 真 ZMQ，模拟服务响应，覆盖 RID 乱序归位、writer、resume、渲染异常/长度过滤；不是 GPU 模型测试 |
| GPU smoke | 1 个 point 的 3 个真实采集 DPs，Qwen3-8B-FP8、TP1、7 层，四设置全部通过 |
| 输出 | 单位置 `[3,7,1,4096]`、四位置 `[3,7,4,4096]`；有限值、BF16 store、完成后跳过 |
| 最终默认服务 | FP32 transport→BF16 store 与 BF16 transport 在这 3 样本上逐值完全相同；wrapper start/status/stop 已运行 |
| 安装器 | 复制已有匹配环境的 4 个锚点文件到 scratch 目标，安装器连续执行两次，13 文件落地；不代表干净上游文件首次安装验证 |

包内 `results/featurize_smoke/2026-10-15/{validation.json,final_default_validation.json,source.json}`
是历史验证证据。它们的绝对数据路径/command 是原机器记录，需要迁移后替换；包不含那三条
完整输入和二进制特征。不要把这些 JSON 当作在接收方机器刚刚运行过的结果。

GPU 验证借用了已有匹配 runtime。没有独立 HF/full-hidden reference 对齐证明，没有验证
radix/chunk/graph 的所有组合、TP>1、PP、其他模型；没有本项目吞吐 benchmark。
原树“四卡约 57 DP/s、96.5K prompt tokens/s”的历史窗口不适用于本包性能声明。

接收方最低验收：

1. 先在解压目录运行聚焦测试（需要 pytest 和 client 依赖）：

   ```bash
   PYTHONPATH="$PWD" .venv-featurize/bin/python -m pytest tests/ -q
   ```

   本 zip 只带八个 featurizer 测试，预期 27 passed；完整 ipi-doom checkout 的六个
   baseline failure 不应混淆为这个子集可接受的新失败。
2. 安装完整 patch，确认目标 Python import 的是这次 patch 的文件；不要 patch 一个环境、
   却用另一个 Python 启服务。
3. 用本地模型、1 个冻结 point 的少量 DPs，分别跑 prefix/last4/discard/compact，
   检查 shape、finite、BF16 大小；将输出 ID 集合与所选源 ID 集合比较（过滤时使用预期子集），
   再按 ID 恢复顺序。重复执行应跳过完成项。
4. 若自己的集成会用 cache/chunk/graph，分别与 cold eager 基准比较再开；
   本包没有代替这些配置的接收方验收。

## 11. 包的内容、更新与排查入口

zip 包含上述 19-file Python 闭包、完整 patch、三个运行/审计脚本、打包脚本、八个测试、
pyproject/uv.lock/pytest.ini、本交接和运行手册、历史验证 JSON、无哈希的文件清单/来源元数据。
不含 `.env`、凭据、venv、模型、原始 dataset、raw feature binaries、logs、无关采集/训练源码。

重打包：在 ipi-doom 根目录运行 `uv run python scripts/package_featurize.py`。
优先检查：

- 未连上：endpoint 是否一致、server 是否 ready；没有 timeout，不应等它自行报连接超时。
- 没捕获行/字段：是否装齐 13 runtime + 4 anchor；是否走 `fyh-feature:` + prefill-only。
- negative positions/chunk 错位：完整长度 anchor、chunk payload 保留与最终重排。
- 输出行数/graph 错：graph spec（包括 dtype）和 selected-row graph runner/backend。
- prefix mismatch：source IDs 是否来自另一 tokenizer，是否应显式 retokenize。
- 完成点不增行：冻结输入/manifest 的跳过语义；改 feature name。

本交接关键点经三个只读子代理分别核查 featurizer 契约、SGLang patch、打包闭包，
再由主代理对照源码与解压测试整合；此次更新没有额外启动 GPU 任务。
