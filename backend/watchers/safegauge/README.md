# SafeGauge 进程内检测器

SafeGauge 由 CoolWatch 后端直接加载。MLP 在首次读取模型信息或首次选择 SafeGauge 时懒加载；prefill prompt logprobs 复用 CoolWatch 已配置的 vLLM OpenAI-compatible API。

```text
safegauge/
├── client.py       # 异步集成、懒加载与 checkpoint 自动选择
├── detector.py     # tokenizer、prompt logprobs 和 MLP 推理核心
└── models/         # 已训练 checkpoint 及其元数据
```

每个 checkpoint 由相邻文件组成：

```text
models/<base-model>/<task>/
├── best_model.pt
└── best_model.meta.json
```

`.meta.json` 决定检测任务、assistant prefill 后缀、标签、输入维度和阈值。至少需要：

```json
{
  "task": "task_identifier",
  "suffix": "Assistant prefill suffix",
  "input_dim": 20,
  "best_threshold": 0.5,
  "positive_label": "risk",
  "negative_label": "safe",
  "positive_is_risk": true,
  "reasoning_prefix": ""
}
```

后端配置：

```dotenv
VLLM_BASE_URL=http://127.0.0.1:18087/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=Qwen3.5-27B
SAFEGAUGE_PROCESSOR_PATH=
SAFEGAUGE_TOKENIZER_PATH=
SAFEGAUGE_DEVICE=cpu
SAFEGAUGE_TIMEOUT_SECONDS=120
```

`SAFEGAUGE_PROCESSOR_PATH` 为空时，会使用 `VLLM_MODEL` 的最后一段匹配 `models/<base-model>/`。只有一个 `best_model.pt` 时自动选择；否则必须显式配置。

`SAFEGAUGE_TOKENIZER_PATH` 通常可以留空，检测器会从 vLLM `/models` 返回的信息推断。vLLM 和后端无法共享同一文件路径时，需要显式设置为后端可访问的 tokenizer 路径。

前端阈值滑杆会覆盖当前请求的 `best_threshold`，不会修改 checkpoint 元数据。CoolWatch 的统一 HTTP 判定接口见项目根目录 README。
