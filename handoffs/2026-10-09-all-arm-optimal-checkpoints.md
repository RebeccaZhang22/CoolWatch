# All-arm optimal probe checkpoints handoff

Date: 2026-10-09 (Asia/Shanghai)

## Scope and final state

The all-arm queue completed 45 training jobs and 45 held-out evaluations:

- arms: `arm1_ajonly`, `arm2_neverneg`, `arm3_swe`, `arm4_ota`, `arm5_neulab`
- configurations: linear p-all `L4/L16/L28`, MLP p-1 `L8/L12/L16`, MLP p-all `L4/L16/L28`
- seeds: `13`, `42`, `2026`
- eval faces per checkpoint: `heldout_neulab` (139,797), `heldout_ota` (238,509), `heldout_swe` (23,814)
- threshold: `0.9`
- feature normalization: `standard`
- sampling: `domain_balanced`

All eval queue jobs are terminal with return code zero. The complete machine-readable summary is in `results/all_arm_optimal_queue/analysis.json`; the protocol and split audit is in `results/all_arm_optimal_queue/protocol_audit.json`.

## Recommended checkpoint per arm

These are the configurations with the highest mean Neulab held-out F1 in this completed sweep. This is a post-hoc comparison result, so it must not be described as an untouched test-set model-selection result. For a strictly blind selection, choose using validation only and report the held-out score once.

| Arm | Recommended probe | Neulab held-out F1 | AUROC |
|---|---|---:|---:|
| `arm1_ajonly` | linear, p-all `L4/L16/L28` | `0.6244 ± 0.0228` | `0.7690 ± 0.0116` |
| `arm2_neverneg` | linear, p-all `L4/L16/L28` | `0.4755 ± 0.0121` | `0.7893 ± 0.0127` |
| `arm3_swe` | MLP, p-1 `L8/L12/L16` | `0.9015 ± 0.0060` | `0.9610 ± 0.0036` |
| `arm4_ota` | MLP, p-all `L4/L16/L28` | `0.9014 ± 0.0138` | `0.9636 ± 0.0083` |
| `arm5_neulab` | MLP, p-all `L4/L16/L28` | `0.9902 ± 0.0010` | `0.9993 ± 0.0003` |

## Checkpoint paths

Each selected configuration has three seed checkpoints. The checkpoint files preserve the feature composition, selected layers, normalization statistics, training seed, validation-selected epoch, and probe state dict.

### arm1_ajonly, linear p-all L4/L16/L28

```text
results/all_arm_optimal_queue/runs/arm1_ajonly__linear__pall_L4-16-28__s13/arch_linear__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm1_ajonly__linear__pall_L4-16-28__s42/arch_linear__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm1_ajonly__linear__pall_L4-16-28__s2026/arch_linear__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
```

### arm2_neverneg, linear p-all L4/L16/L28

```text
results/all_arm_optimal_queue/runs/arm2_neverneg__linear__pall_L4-16-28__s13/arch_linear__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm2_neverneg__linear__pall_L4-16-28__s42/arch_linear__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm2_neverneg__linear__pall_L4-16-28__s2026/arch_linear__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
```

### arm3_swe, MLP p-1 L8/L12/L16

```text
results/all_arm_optimal_queue/runs/arm3_swe__mlp__p-1_L8-16__s13/arch_mlp__feat_contiguous_concat__layer_8__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_08_12_16.pt
results/all_arm_optimal_queue/runs/arm3_swe__mlp__p-1_L8-16__s42/arch_mlp__feat_contiguous_concat__layer_8__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_08_12_16.pt
results/all_arm_optimal_queue/runs/arm3_swe__mlp__p-1_L8-16__s2026/arch_mlp__feat_contiguous_concat__layer_8__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_08_12_16.pt
```

### arm4_ota, MLP p-all L4/L16/L28

```text
results/all_arm_optimal_queue/runs/arm4_ota__mlp__pall_L4-16-28__s13/arch_mlp__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm4_ota__mlp__pall_L4-16-28__s42/arch_mlp__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm4_ota__mlp__pall_L4-16-28__s2026/arch_mlp__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
```

### arm5_neulab, MLP p-all L4/L16/L28

```text
results/all_arm_optimal_queue/runs/arm5_neulab__mlp__pall_L4-16-28__s13/arch_mlp__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm5_neulab__mlp__pall_L4-16-28__s42/arch_mlp__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
results/all_arm_optimal_queue/runs/arm5_neulab__mlp__pall_L4-16-28__s2026/arch_mlp__feat_arbitrary_concat__layer_4__concat_3__lr_0p0003__ep_10__pw_1__sample_domain_balanced/models/best_layers_04_16_28.pt
```

## Protocol caveats

The validation partitions exclude Neulab grid points and all train/val/held-out decision-point ID intersections are zero. However, the training domains are not all Neulab-free: arm1 has zero Neulab training rows, arm2–arm4 have 1,813 each, and arm5 has 86,614. Therefore “Neulab-blind” here means validation-blind selection; it is not an across-the-board zero-Neulab training protocol.

The arm5 p-all jobs initially hit CUDA OOM in the original batch-256 path. They were rerun with `batch_size=2048` while keeping architecture, layers, seed, optimizer, learning rate, weight decay, normalization, sampling, epochs, and threshold fixed. This deviation is recorded in `protocol_audit.json` and should be reported with any arm5 comparison.

## Reproduction and evaluation artifacts

```bash
cd /mnt/kpfs_qyang/djs/from-zhisuanyun-g03/follow-your-heart
/opt/miniconda3/envs/sglang-ready/bin/python scripts/probe_job_queue.py status --queue results/all_arm_optimal_queue/queue.json
/opt/miniconda3/envs/sglang-ready/bin/python scripts/probe_job_queue.py status --queue results/all_arm_optimal_queue/eval_queue.json
/opt/miniconda3/envs/sglang-ready/bin/python scripts/analyze_all_arm_optimal.py
```

Key artifacts:

- `results/all_arm_optimal_queue/queue.json`
- `results/all_arm_optimal_queue/eval_queue.json`
- `results/all_arm_optimal_queue/analysis.json`
- `results/all_arm_optimal_queue/report.md`
- `results/all_arm_optimal_queue/protocol_audit.json`
- `results/all_arm_optimal_queue/eval_*.jsonl`
