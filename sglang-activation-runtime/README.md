# SGLang 请求级隐藏状态采集

独立实现，基于 **官方 SGLang 0.5.19 wheel**，通过校验过的源码补丁加入采集通路。不调用原项目的 `sglang_fe` / `sglang_det`，不使用 forward hooks 或落盘中转，不修改原来的 SGLang 安装。服务可以混合处理不同层、不同位置及不采集的并发请求。

改动原理、并发处理和 probe 接入过程见 [实现说明](../doc/diary/2026-10-12-sglang-activation-capture.md)。

## 启动

此工作区已准备好 `.source`（独立源码）和 `.venv`（独立解释器环境）。环境只读复用现有环境中的 Torch/CUDA 等依赖；SGLang 自身从本目录 `.source` 加载。`python` 和 `serve` 清理旧的外部模型入口及 PYTHONPATH，不加载原特征提取方案。

在本目录运行：

```bash
CUDA_VISIBLE_DEVICES=0 ./serve \
  --model-path /mnt/kpfs_qyang/yutongz/models/Qwen3-8B \
  --host 127.0.0.1 --port 31080 \
  --mem-fraction-static 0.8 \
  --max-total-tokens 4096 --max-running-requests 16 \
  --context-length 2048 --chunked-prefill-size 256 \
  --cuda-graph-bs-decode 1 2 4 8 16
```

GPU、端口和容量按实际部署调整；此示例不会由安装工具自动启动。Qwen3.5 使用官方模型入口，传其模型路径即可，无需设置外部模型包。`serve` 会设置 `SGLANG_ACTIVATION_CAPTURE=1`；直接使用 Engine 时在创建 Engine **之前**设置该环境变量。

## 请求与响应

```python
import requests

result = requests.post("http://127.0.0.1:31080/generate", json={
    "text": "Explain why the sky is blue.",
    "sampling_params": {"max_new_tokens": 32, "temperature": 0},
    "return_logprob": True,
    "activation_capture": {
        "targets": [
            {"layer": 9, "site": "block_output"},
            {"layer": 19, "site": "ffn_output"}
        ],
        "tokens": {"prompt": "last", "generated": "processed"},
        "encoding": "base64"
    }
}, timeout=120).json()

print(result["text"])
chunks = result["meta_info"]["activations"]["chunks"]
```

- `layer`：从 **0** 开始。9 表示第十个 decoder block。每个请求可以换层，无需重新加载模型或重新捕获 decode graph。
- `ffn_output`：完成必要通信后的 FFN 分支输出，不含残差。
- `block_output`：FFN 输出加残差之后、下一层归一化之前。末层也不包含模型最终 norm。
- `tokens.prompt`：`all`、`last`、`none` 或绝对 token 位置列表，例如 `[0, 15, 31]`；默认 `last`。
- `tokens.generated`：`none` 或 `processed`；默认 `none`。
- `encoding`：默认 `base64`，保留模型 dtype 的原始值；`float_list` 适合小结果调试。无隐式降精度。

每个 chunk 包含 `layer`、`site`、`positions`、`token_ids`、`shape`、`dtype`、`data` 和实际执行方式 `execution`。位置是**分词后的完整输入序列位置**，包括 tokenizer 添加的特殊 token。张量形状为 `[tokens, hidden_size]`，每个被选 token 的所有维度都会返回。

```python
import base64
import torch

chunk = chunks[0]
values = torch.frombuffer(
    bytearray(base64.b64decode(chunk["data"])),
    dtype=getattr(torch, chunk["dtype"]),
).reshape(chunk["shape"])
```

**生成 token 对齐：**`processed` 返回已经作为模型输入执行过 forward 的生成 token 的状态。它不是“用于预测该 token 的前一个位置的状态”。正常自回归生成结束时最后一个输出 token 尚未再次执行 forward，因此通常不包含它；本实现不会为补最后一个状态悄悄增加推理。若需要完整序列包括末 token 的状态，可把完整 token IDs 作为新 prompt，选择 `prompt: all` 再计算。

原生流式请求设置 `stream: true`。`activations.stream_delta` 为 true，每个 chunk 只发送一次，客户端按 `(layer, site, position)` 汇总。非流式请求返回完整累积结果。空采集范围返回空 chunks；不要求采集的请求不返回 activations 字段。

## Engine 与 OpenAI API

`Engine.generate()` / `async_generate()` 支持同名 `activation_capture` 参数。批量输入可传一个公共配置，也可传与请求数量相同的配置列表，其中 `None` 表示该请求不提取。

OpenAI SDK 通过 `extra_body={"activation_capture": ...}` 传入。支持 `/v1/completions` 和 `/v1/chat/completions`：

- 非流式：`choices[i].activations`。
- completion 流：`choices[i].activations`。
- chat 流：`choices[i].delta.activations`，可能是独立的数据事件。

文本、logprobs 和官方 `return_hidden_states` 通路保持独立。新功能不复用或覆盖 EAGLE 的内部 hidden states。

## 并发与性能设计

1. 请求配置沿官方请求、调度、ForwardBatch 通路传递。每次 forward 单独构造 token 行计划，不修改全局层选择列表。
2. Prefill 按目标层聚合实际需要的行，用一个 Triton kernel 完成选择、可选残差相加和输出复制。只取最后一个 token 时不保存整个 prompt 的向量。
3. Decode 在每层预置一个采集 kernel，GPU 选择表决定该批次哪些行写到哪里。表的地址与输出缓冲区稳定，支持同一 CUDA Graph 内动态换层、不同请求同时选不同层；无需为层组合重捕获图。
4. 未选择的层只检查目的位置，不读取完整向量。开启采集能力的服务在 decode graph 中仍有这些检查 kernel 的固定成本，并非零开销。
5. 在 forward stream 上复制 decode 输出快照，防止下一次 graph replay 覆盖正在传回 CPU 的结果。复用官方 pinned-memory 异步 D2H 和完成事件，每个 forward 批量复制。
6. TP 的模型通信仍由所有 rank 正常执行，只有 rank 0 采集和传回已完成通信的完整激活。EAGLE/采样 observer 的输出使用不同字段。
7. 结果通过原有进程通信返回。Scheduler 批量转原始字节，TokenizerManager 负责 base64；非流式请求只在完成时编码，避免周期性重复编码整个历史。
8. 前缀复用最多推进到最早尚未采集的 prompt token。全 prompt 采集通常需要重算；只取最后 token 时保留之前的可用缓存。分块预填充逐块累积，重算后去重。

**当前性能边界：**有实际采集行的 prefill batch 使用 eager forward，保留批处理和 chunked prefill；无采集行的 batch 可以走官方 prefill graph。Decode 保留 CUDA Graph。Qwen3.5 的跨层延迟 MLP all-reduce 在此模式下改为明确的层内通信，以确保 FFN 输出语义；这可能影响其原有融合收益。

完整向量输出有不可消除的带宽成本。例如 4096 tokens × 2 targets × 4096 dimensions × BF16 = 64 MiB 原始数据，base64 还会增大约三分之一。高并发优先使用明确的 token 位置或 `prompt: last`。

容量开关：

| 环境变量 | 默认 | 含义 |
|---|---:|---|
| `SGLANG_ACTIVATION_CAPTURE` | `0` | 必须在服务启动前开启 |
| `SGLANG_ACTIVATION_MAX_TARGETS` | `8` | 每请求最多几个 `(layer, site)` |
| `SGLANG_ACTIVATION_MAX_BYTES` | `134217728` | 每请求原始激活预算，按 FP32 保守估算，超限返回错误 |

同时用 SGLang 的 `max-running-requests` 控制在途请求总量。Decode 缓冲区随并发容量、目标数上限和 hidden size 线性增长。

## 支持边界

模型适配包含 Qwen2/Qwen3、Llama、**Qwen3.5 Dense** 的 FFN/block 位置；数值验证的具体模型及并行配置见 `validation.json`。支持 CUDA、文本输入、普通自回归生成、chunked prefill、常规 TP 和并发请求。

**Qwen3.5 MoE 暂不开放**：小型 BF16 MoE 对照测试有约 0.6% 的元素超过当前误差阈值，原因尚未确定，启动时明确拒绝，避免把未通过验证的适配当作可用版本。`Qwen3.5-35B-A3B` 属于这个范围；Qwen3.5-9B/27B 是 Dense。测试模型构造工具保留 MoE 复现配置，后续需要独立解决。

未接入 speculative decoding、PP、DP attention、context/sequence parallel、two-batch-overlap、PD 分离、session 和 beam search。这些组合会明确拒绝，避免返回错误的 token 或分片。多模态输入暂不接受。稀有量化/融合配置未经过完整验证，不应把某一模型的结果推广到所有后端。

## 重建与维护

- `upstream.json`：官方 wheel 的版本、文件名和 SHA-256。
- `patches/activation-capture.patch`：对官方文件的可审阅修改。
- `src/sglang/srt/activation_capture/`：新功能的独立实现。
- `.source/`：忽略进版本控制的完整工作副本，可直接编辑调试。
- `.venv/`：独立解释器；不修改所借用的依赖目录。

在全新副本中重建：

```bash
python tools/bootstrap.py \
  --wheel /path/to/sglang-0.5.19-cp311-cp311-manylinux_2_34_x86_64.whl \
  --dependency-python /path/to/a/compatible/python
```

校验不匹配的 wheel 会拒绝应用。已有 `.source` 也会拒绝覆盖，避免丢失源码修改。更新源码后通过 `tools/export_patch.py --wheel ...` 导出上游修改；新增模块保存在 `src/`，调试前复制到 `.source/sglang/srt/activation_capture/`。

## 测试

```bash
CUDA_VISIBLE_DEVICES=0 ./python tests/test_capture.py
./python tools/build_test_model.py --architecture qwen3
CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=2 ./python tests/integration_engine.py
CUDA_VISIBLE_DEVICES=0,1 ACTIVATION_TEST_TP=2 OMP_NUM_THREADS=2 \
  ./python tests/integration_engine.py
```

`build_test_model.py` 无网络生成小型官方架构模型；集成测试与 Transformers 逐 token 对照，覆盖混合请求、两种采集位置、层切换、缓存、chunk、流式增量、长非流式输出和 decode graph。GPU 同时有其他任务时，吞吐量只是当前共享环境的观测值。

`tests/http_api.py` 验证明确启动在 localhost:39183 的测试服务。`tests/benchmark_model.py` 使用本机 Qwen3-8B 测量真实模型的采集开销；不自动停止或修改任何已有服务。
