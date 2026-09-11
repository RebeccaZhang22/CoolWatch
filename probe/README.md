# Runtime probes

The Probe Bank backend loads all three production risk detectors from this
directory. `vllm_setups/run_probe_bank_qwen35_2b.sh` is the canonical entry
point and accepts `PROBE_DIR` to override the whole directory.

| API risk | Runtime file | Implementation |
| --- | --- | --- |
| `harmful` | `content_safety/best_probe.pt` | `harmful/m1` linear probe and `harmful/m2` difference-in-means, fused with `max` |
| `prompt_leakage` | `prompt_leakage/best_probe.pt` | Unified multilayer MLP |
| `ipi` | `indirect_prompt_injection/best_layer_07.pt` | Broad layer-7 linear probe |

Individual paths can be overridden with `CONTENT_SAFETY_PROBE`,
`LEAKAGE_PROBE_CHECKPOINT`, and `IPI_PROBE_CHECKPOINT`.

The deployment entry point accepts up to 1,024 in-flight HTTP requests by
default and executes them in bounded microbatches of at most 64 requests.

`content_safety/convert_from_json.py` records the reproducible one-time import
from the original DetectorCore bank. The JSON source is not used at runtime.
