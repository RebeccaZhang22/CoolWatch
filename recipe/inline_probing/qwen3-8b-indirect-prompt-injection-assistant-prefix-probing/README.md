# Qwen3-8B indirect-prompt-injection assistant-prefix probing

Recipe ID: `qwen3-8b-indirect-prompt-injection-assistant-prefix-probing`.

This is a self-contained Perspective Watch golden recipe for detecting indirect prompt
injection at the assistant-prefix boundary. It pins the rank-1 Qwen3-8B linear
probe selected from 14,544 layer/epoch/threshold candidates: checkpoint layer
4, epoch 10, and threshold 0.76.

## Label definition: what this probe detects

The target is `risk_faced` at an assistant decision point. For each injection
round, the positive example is the first assistant decision point whose
rendered prompt prefix already contains that injected content. Formally, for
injection message index `r` and assistant message index `a`, the decision point
is positive when `r < a` and it is the earliest decision point in that trace
for which this holds. A trace with multiple injection rounds may therefore
have one positive decision point per round.

Negative examples include clean and pre-injection decision points, plus later
assistant decision points after the same injection round has already been
faced. Consequently, this probe predicts the boundary event “the assistant is
facing newly visible injected content now.” It does **not** directly mean that
the attack succeeded, that actual security harm occurred, that injection is
visible at every later turn, or that the text merely resembles an injection.
The authoritative implementation is
`follow_your_heart.probes.collection.labels.build_protocol_label_rows`; the
machine-readable definition is in `recipe.json` under `task.labeling`.

The checkpoint layer maps to vLLM auxiliary layer 5. FYH calls the residual
stream output after zero-based block `N` layer `N`; vLLM auxiliary layer 0 is
the embedding output, so the same activation is auxiliary layer `N + 1`.

## Contents

- `probe.pt`: the linear probe checkpoint, SHA-256
  `41f1433346caebc8b2e9ff5640b44e3d162050d6ef7ffee45285badba4798b45`.
- `cases.jsonl`: 32 positive and 32 negative complete replay cases sampled
  across 16 strict grid points. Cases contain messages, tools, labels, expected
  prompt fingerprints, and reference scores. They do not contain token arrays,
  hidden states, or saved feature tensors.
- `vllm-0.25.1-overlay/`: the exact 14-file source overlay plus upstream and
  patched SHA-256 values in `manifest.json`.
- `patch-vllm.sh`: pure-Bash `apply`, `check`, and recoverable `restore` logic.
- `vllm_server_control_with_probe_enabled.sh`: controls a vLLM server that
  loads this probe at startup through `start`, `status`, and `stop`; the
  lifecycle and probe configuration logic lives directly in this Bash file.
- `example.sh`: a full 64-case online golden regression example.
- `recipe.json`: model-family, probe, runtime, provenance, and metric contract.

## Reference metrics

| Evaluation | Examples | AUROC | Average precision | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full strict offline | 31,207 | 0.999700 | 0.998675 | 0.975162 | 0.992346 | 0.983679 | 0.994072 |
| Golden sample online | 64 | - | - | 0.968750 | 0.968750 | 0.968750 | 0.968750 |

At threshold 0.76, full strict evaluation has TN=25,447, FP=142, FN=43,
and TP=5,575. The 64-case online reference has TN=31, FP=1, FN=1, and
TP=31. All 64 native prompt-token fingerprints match their collection inputs.

## Offline integrity check

From the Perspective Watch repository root:

```bash
python3 -m backend.watchers.inline_probing.golden_recipe
```

This checks the probe and cases hashes, checkpoint dimensions and model-family
position, sample balance, absence of serialized tokens/features, all overlay
hashes, and Python syntax of every patched vLLM source file.

## Install and patch vLLM 0.25.1

Install `uv`, then create a dedicated environment and install the exact vLLM
version from this recipe directory:

```bash
uv venv --python 3.12 ../../../.runtime/vllm-0.25.1-inline-probing
uv pip install \
  --python ../../../.runtime/vllm-0.25.1-inline-probing/bin/python \
  vllm==0.25.1
```

Apply the recipe overlay to that installed environment:

```bash
./patch-vllm.sh apply \
  --target ../../../.runtime/vllm-0.25.1-inline-probing/lib/python3.12/site-packages/vllm
```

The patch command verifies every pristine upstream file hash, saves a
recoverable backup beside `site-packages/vllm`, applies the overlay atomically,
compiles it, and verifies every patched hash. It refuses to overwrite an
unknown or partially modified installation.

To audit an installed environment directly:

```bash
./patch-vllm.sh check \
  --target ../../../.runtime/vllm-0.25.1-inline-probing/lib/python3.12/site-packages/vllm
```

To restore the source files saved by `patch-vllm.sh apply`:

```bash
./patch-vllm.sh restore \
  --target ../../../.runtime/vllm-0.25.1-inline-probing/lib/python3.12/site-packages/vllm
```

The explicit target path can differ when the environment uses another Python
minor version.

## Start, inspect, and stop

Pick an idle GPU and start the server:

```bash
./vllm_server_control_with_probe_enabled.sh start --gpu 4
./vllm_server_control_with_probe_enabled.sh status
```

脚本默认加载本目录的间接提示词注入 checkpoint。要复用同一套 vLLM overlay
加载其他兼容 checkpoint，可传入其 `recipe.json`：

```bash
./vllm_server_control_with_probe_enabled.sh start \
  --probe-recipe ../qwen3-8b-system-prompt-leakage-placeholder/recipe.json \
  --state-dir ../../../.runtime/qwen3-8b-system-prompt-leakage-holder-server \
  --gpu 0
```

`--state-dir` 应与同机运行的其他 vLLM 实例区分开。System Prompt Leakage
holder 只验证 residual 捕获和融合通路，不是训练完成的检测器。

The recipe defaults to `Qwen/Qwen3-8B`, served name `qwen3-8b`, port 8013,
checkpoint layer 4, effective position -1, and threshold 0.76. `start` verifies
the patch and checkpoint before launch. It sets `VLLM_USE_V2_MODEL_RUNNER=0`,
because Qwen3 otherwise selects the v2 runner in vLLM 0.25.1 and bypasses this
v1 capture hook. It also fixes TP=1, PP=1, ubatching=off, speculative decoding
absent, asynchronous scheduling=off, and uses the public
`inline_probing_request` / `inline_probing` protocol only.

This is not a hot-plug controller. The probe checkpoint and capture
configuration are loaded while the vLLM workers start. Requests can opt in by
sending `inline_probing_request`, but changing, adding, or removing the loaded
probe requires stopping and restarting this dedicated server.

The patched `/v1/completions` route also accepts `inline_probing_request` for
raw token-id prompts. A request may therefore return prompt logprobs for a
SafeGauge suffix and an Inline Probe score from an explicit earlier prompt
token in one prefill. The request must be non-streaming, contain exactly one
token-id prompt, use `n=1`, and request returned token IDs.

## Perspective Watch live Agent integration

When this recipe server is used as Perspective Watch's agent model endpoint, the
AgentLoop attaches `inline_probing_request` to the actual assistant generation,
not to a separate probe-only request. The trigger is the first assistant
decision immediately following each newly appended batch of `tool` messages.
The request retains the complete tool result, messages, tool definitions, and
normal generation budget; the single response contains both the assistant
message and the typed `inline_probing` result. A generation without a new tool
result is reported as not triggered.

The runtime cannot know whether a tool result is injected before evaluating
the decision state, so this trigger applies to every new tool-result batch.
Offline experiment scoring uses frozen injection-round indices to select only
the known injected decision points.

Logs are written under `Perspective Watch/logs/YYYY-MM-DD/`. Runtime state owns
`run.pid`, `run.pgid`, and `run.json` under
`Perspective Watch/.runtime/qwen3-8b-inline-probing-server/`. `status` prints the exact
log path, loaded recipe, checkpoint ID, task, and stop command.

On hosts that need the NVIDIA forward-compatibility libraries, add:

```bash
./vllm_server_control_with_probe_enabled.sh start --gpu 4 \
  --cuda-compat-lib-dir /usr/local/cuda/compat
```

Stop the entire server process group after validation:

```bash
./vllm_server_control_with_probe_enabled.sh stop
```

## Usage example: online 32-positive + 32-negative regression

With the server ready on port 8013, run:

```bash
./example.sh
```

Optional positional arguments are `BASE_URL`, served model name, and output
path:

```bash
./example.sh \
  http://127.0.0.1:8013/v1 \
  qwen3-8b \
  results/qwen3-8b-inline-probing-golden.jsonl
```

Each case sends its message list and tool definitions to vLLM. The Qwen3-8B
server applies its tokenizer and chat template, captures a fresh layer-4
assistant-prefix activation through vLLM auxiliary layer 5, scores it, and
returns `inline_probing`. The regression verifies all 64 native prompt-token
fingerprints, the TN/FP/FN/TP reference counts, and score drift tolerance.
