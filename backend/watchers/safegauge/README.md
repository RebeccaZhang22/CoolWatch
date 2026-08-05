# SafeGauge 进程内检测器

SafeGauge 由 Perspective Watch 后端直接加载。MLP 在首次读取模型信息或首次选择 SafeGauge 时懒加载；prefill prompt logprobs 复用 Perspective Watch 已配置的 vLLM OpenAI-compatible API。

```text
safegauge/
├── client.py       # 按任务与模型路由、异步集成和懒加载
└── detector.py     # tokenizer、prompt logprobs 和 MLP 推理核心
```

每个 checkpoint 由相邻文件组成：

```text
results/suffix_probe/<task-and-model>/probe/
├── model.pt
└── model.meta.json
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

演示服务按场景任务和用户选择的模型加载独立 checkpoint：

| 场景任务 | Qwen3-8B | Qwen3-32B |
|---|---|---|
| `financially_malicious_action` | `results/suffix_probe/finvault-qwen3-8b-financially-malicious-action/probe/model.pt` | `results/suffix_probe/finvault-qwen3-32b-financially-malicious-action/probe/model.pt` |
| `system_prompt_leakage_intent` | `results/suffix_probe/prompt-extraction-qwen3-8b-system-prompt-leakage/probe/model.pt` | `results/suffix_probe/prompt-extraction-qwen3-32b-system-prompt-leakage/probe/model.pt` |

任务路由优先于旧的全局 `SAFEGAUGE_PROCESSOR_PATH`，确保 FinVault 和提示词泄露不会共用 checkpoint。没有传任务时，才使用该显式路径或 `models/<base-model>/` 的兼容自动发现逻辑。

`SAFEGAUGE_TOKENIZER_PATH` 通常可以留空，检测器会从 vLLM `/models` 返回的信息推断。vLLM 和后端无法共享同一文件路径时，需要显式设置为后端可访问的 tokenizer 路径。

前端阈值滑杆会覆盖当前请求的 `best_threshold`，不会修改 checkpoint 元数据。Perspective Watch 的统一 HTTP 判定接口见项目根目录 README。
