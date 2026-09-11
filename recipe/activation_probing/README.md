# Activation Probe inside patched vLLM

This recipe loads the current trained Activation Probe checkpoint directly
inside the patched vLLM GPU worker. No checkpoint conversion or second
Transformers model is required.

The production recipe is Qwen3-8B v16: it captures block outputs 21/22/23,
standardizes and concatenates them, then scores them with a small MLP. The
historical single-layer linear recipes are archived under
`aborted/activation_probing/legacy_recipes/`.

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

Then configure ProspectMonitor:

```dotenv
ACTIVATION_PROBE_BACKEND=vllm
ACTIVATION_PROBE_VLLM_BASE_URL=http://127.0.0.1:8013/v1
```

The backend selects the Qwen3-8B `prompt` route and sends its explicit
`probe_id` and checkpoint SHA-256. The response is rejected if the probe ID,
checkpoint ID, or layer differs from the selected route.

For Qwen3-8B customer and legal Agents, the `prompt` route uses the v16
multilayer MLP unified theft probe covering System/Developer Prompt, private
RAG, private CoT, and private Skill/tool disclosure intent. Older
prompt-extraction, FinVault and standalone-service implementations are kept
only under `aborted/activation_probing/`.
