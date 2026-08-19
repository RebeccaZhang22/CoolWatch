# Activation Probe inside patched vLLM

These recipes load the existing trained Activation Probe checkpoints directly
inside the patched vLLM GPU worker. No checkpoint conversion or second
Transformers model is required.

The four historical checkpoints use one residual-stream block output and a
linear scorer. The Qwen3-8B customer-Agent default is v16: it captures block
outputs 21/22/23, standardizes and concatenates them, then scores them with a
small MLP. Both paths share the same auxiliary-hidden-state executor, and the
multi-probe registry can load several compatible recipes for one model server.

The runtime is pinned to vLLM `0.25.1`. Install and apply the overlay first by
following the [Inline Probing setup](../inline_probing/qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/README.md).
The same runtime restrictions apply: TP=1, PP=1, v1 model runner, eager mode,
and no asynchronous scheduling, ubatching, or speculative decoding. All recipes
passed to one server must target the same model revision and hidden width.

Qwen3-8B customer-Agent example (IPI + v16 multilayer unified theft probe):

```bash
LAUNCHER=recipe/inline_probing/qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/vllm_server_control_with_probe_enabled.sh

"$LAUNCHER" start \
  --state-dir .runtime/qwen3-8b-multiprobe-server \
  --model .runtime/models/Qwen3-8B \
  --served-model-name qwen3-8b \
  --gpu 4 \
  --probe-recipe recipe/inline_probing/qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/recipe.json \
  --probe-recipe recipe/activation_probing/qwen3-8b-theft-unified-v16-multilayer-mlp/recipe.json
```

Qwen3-32B example (both Activation Probes):

```bash
"$LAUNCHER" start \
  --state-dir .runtime/qwen3-32b-activation-multiprobe-server \
  --model .runtime/models/Qwen3-32B \
  --served-model-name qwen3-32b \
  --gpu 4 \
  --port 8014 \
  --gpu-memory-utilization 0.95 \
  --max-model-len 2048 \
  --max-num-batched-tokens 2048 \
  --probe-recipe recipe/activation_probing/qwen3-32b-finvault/recipe.json \
  --probe-recipe recipe/activation_probing/qwen3-32b-prompt-extraction/recipe.json
```

The 32B command above is an A800-80GB single-GPU validation profile. Adjust the
memory and sequence limits for the deployment GPU, while keeping TP=1 for this
overlay.

Then configure ProspectMonitor:

```dotenv
ACTIVATION_PROBE_BACKEND=vllm
ACTIVATION_PROBE_VLLM_BASE_URL=http://127.0.0.1:8013/v1
```

Use port `8014` in the example configuration when running the 32B command.

The backend selects a probe by `model + scenario_category`, sends its explicit
`probe_id` and checkpoint SHA-256, and preserves the standalone service's
`add_special_tokens` behavior. The response is rejected if the probe ID,
checkpoint ID, or layer differs from the selected route.

For Qwen3-8B customer and legal Agents, the `prompt` route uses the v16
multilayer MLP unified theft probe covering System/Developer Prompt, private
RAG, private CoT, and private Skill/tool disclosure intent. The older
prompt-extraction and FinVault recipes remain available for historical
evaluation and compatibility.

The legacy standalone service remains available with
`ACTIVATION_PROBE_BACKEND=standalone`.
