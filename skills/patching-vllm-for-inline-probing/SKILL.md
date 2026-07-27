---
name: patching-vllm-for-inline-probing
description: Design, port, package, apply, audit, and validate version-specific vLLM patches for hidden-state capture and inline probing without assuming one vLLM release layout. Use when adding inline probing to a new vLLM version, adapting an existing patch across vLLM versions, reviewing patch completeness, building a hash-pinned overlay installer, or applying and verifying an existing versioned overlay. Includes completed vLLM 0.19.0 and 0.25.1 implementations as reference examples.
---

# Patch vLLM for inline probing

Treat each vLLM version as a separate port over a shared behavioral contract.
Reuse semantic invariants from completed ports; never assume filenames, runner
generation, scheduler state, or hidden-state interfaces remain stable.

## Select a completed example

- Inspect `examples/vllm-0.25.1/` when implementing synchronous, per-request
  inline scoring returned through the OpenAI response. It contains the actual
  12-file overlay, SHA manifest, and pure-Bash apply/check/restore tool.
- Inspect `examples/vllm-0.19.0/` when studying the earlier callback/durable
  capture design, direct model-family hooks, and pre-advance chunk interval.
  It contains the actual 10-file overlay, installer, and installer tests.
- Read both when porting to a new version. Compare the semantic data path, not
  whole-file diffs.

Treat these directories as immutable completed snapshots. Do not edit an
example to implement a third version; create a separate versioned port.

### vLLM 0.25.1 example

Trace `inline_probing_request` through OpenAI chat protocol/serving, engine and
scheduler request state, the v1 GPU runner's auxiliary hidden state, in-worker
linear scoring, and `inline_probing` response propagation. Notice that Qwen3
requires the v1 runner, checkpoint layer 4 maps to auxiliary layer 5, and the
completed runtime disables unsupported batching/scheduling modes.

### vLLM 0.19.0 example

Trace `IPI_AWARE_*` configuration and callback registration through direct
model-family residual-stream hooks, GPU-runner request correlation, and
background/durable capture delivery. Notice that its scheduled chunk is the
pre-advance interval
`[num_computed_tokens, num_computed_tokens + num_scheduled_tokens)` and that
capture mode forces a single pipeline batch.

## Define the contract first

Write down the required behavior before editing vendored source:

1. Specify request opt-in, response or capture result, errors, checkpoint
   identity, request identity, deadline, and streaming constraints.
2. Specify model family, residual-stream boundary, layer-number translation,
   prompt-relative position, dtype, normalization, and scorer contract.
3. Specify supported TP/PP, chunked prefill, ubatching, async scheduling,
   speculative decoding, CUDA graph, and concurrency modes. Reject modes that
   cannot preserve request-to-activation identity.
4. Decide whether the port provides capture-only delivery or synchronous
   inline scoring. Do not accidentally expose legacy field names through a new
   public protocol.

For CoolWatch synchronous probing, preserve only
`inline_probing_request` / `inline_probing` as the public API.

## Establish a pristine baseline

Pin an exact vLLM version and obtain its official wheel or tag in an isolated
directory. Determine the installed version from distribution metadata or
source constants without importing vLLM, because imports may initialize
GPU/NVML code.

Before modifying anything:

- record the upstream version, tag, and commit when available;
- hash every source file that the port will replace;
- identify new files separately;
- verify the target is entirely pristine or entirely patched;
- refuse unknown local edits and mixed states.

Never infer patch compatibility from a nearby semantic version.

## Trace the version's semantic path

Read the actual source and locate the current equivalents of:

```text
OpenAI request
  -> engine request state
  -> scheduler request/output state
  -> worker/model forward capture
  -> request-correlated scoring or delivery
  -> engine output
  -> OpenAI response
```

Confirm every serialization, multiprocessing, and batching boundary. Add the
minimum fields required to carry the request and result through those
boundaries. A process tree or symbol-name similarity is not proof that the
data path is complete.

At capture time, derive the scheduled token interval from that exact version's
scheduler semantics. Capture only when the resolved prompt target lies within
the current chunk. Verify layer numbering against the actual tensor returned
by the model or auxiliary hidden-state interface; do not reuse an offset from
another model family or vLLM version without an activation comparison.

## Package a versioned overlay

Keep each completed port in its own versioned overlay. Include:

- only changed and newly added source files;
- a machine-readable manifest with upstream and patched SHA-256 per file;
- exact supported vLLM version and upstream provenance;
- an apply/check tool that is idempotent and atomically replaces files;
- a recoverable backup/restore path when the integration requires restoration;
- syntax compilation and manifest-exhaustiveness tests.

Do not place a generic mutable patch beside multiple versions. The workflow is
version-agnostic; each emitted overlay remains version-exact.

## Validate in layers

Run CPU-only validation first:

1. Check manifest completeness and every overlay hash.
2. Apply to a pristine temporary target, check the patched state, and restore.
3. Verify idempotence and rejection of unknown or partially patched sources.
4. Test request/result propagation, failure behavior, chunk-bound math,
   position resolution, layer mapping, and model-family configuration.

Then run GPU validation:

1. Start the intended model with only supported scheduling modes.
2. Send a real OpenAI-compatible request through the full chat template and
   tokenizer path.
3. Require a finite score/logit or a durable correlated capture, according to
   the declared contract.
4. Compare prompt-token fingerprints and representative activation/score
   values with the source collection pipeline.
5. Run the bounded positive/negative golden sample when the recipe provides
   one; for the Qwen3-8B recipe this is 32 positive plus 32 negative cases.
6. Save commands, logs, GPU, model revision, hashes, and metrics.

Do not diagnose NVML, model download, or server startup failures as patch
contract failures until the same environment can start pristine vLLM.

## Apply an existing port

Use that port's own documented installer and manifest. Resolve the absolute
`site-packages/vllm` target without importing vLLM, stop processes using that
environment, run check before apply, apply once, then check again. Preserve
the installer report and backup.

Do not start a server or restore sources unless the user asks. Inline probing
is normally configured when workers start; per-request opt-in does not imply
checkpoint hot-plugging.

## Report

Report the exact vLLM version, upstream provenance, overlay location, changed
file count, target, commands, hashes or audit report, tests, online evidence,
and unsupported runtime modes. Clearly distinguish a source-integrity pass
from an end-to-end GPU readiness pass.
