# 运行数据与模型清单

本文件说明交付目录为何保留各类非代码文件，以及前端通过哪个后端模块使用它们。

| 路径 | 用途 | 读取方 |
|---|---|---|
| `results/audit_data/` | 三类实验审计的冻结结果、各护栏判定与 FinVault 8B/32B 报告 | `backend/experiment_audit.py` |
| `data/finvault/` | FinVault query、System Prompt、中文翻译和正常任务 | `backend/experiment_audit.py`、`backend/finvault_replay.py` |
| `data/system_prompt_extraction/` | 系统提示词泄露演示使用的 18 个银行提示词与 55 条攻击 query | `backend/scenarios.py`、`backend/attack_library.py` |
| `evaluations/qwen3_8b_held_out_strict_injected_round_100_samples_zh/` | 间接提示词注入审计的冻结中文 case | `backend/experiment_audit.py` |
| `results/activation_probe/finvault-qwen3-{8b,32b}/` | FinVault 前端逐 case 结果、摘要和两种模型的实时 checkpoint | 审计 API；checkpoint 由 `backend.activation_probe_server` 按模型加载 |
| `results/activation_probe/prompt-extraction-qwen3-{8b,32b}/` | 提示词泄露前端统计所需预测和两种模型的实时 checkpoint | 审计 API；checkpoint 由 Activation Probe 服务按模型加载 |
| `results/suffix_probe/*/probe/` | 四个任务/模型组合的 SafeGauge MLP 与运行元数据 | `backend/watchers/safegauge/client.py` |
| `case_studies/pdf_white_text_car_loan_injection/` | Case Study 的 PDF、固定轨迹与四种护栏结果 | `backend/case_studies.py` |
| `recipe/inline_probing/` | 间接注入 Inline Probing 的 vLLM patch、probe 和回归 case | patched vLLM、`backend/watchers/inline_probing/` |

不保留：`exp/`、训练/数据处理 `scripts/`、隐藏层 feature tensor、SafeGauge 特征 JSONL、训练集副本、历史 `guard_detection`、实验迭代、运行日志、缓存、真实 `.env` 和原仓库 Git 元数据。

## Checkpoint 路由

SafeGauge 路由由“任务 × 模型”唯一确定：

| 任务 | Qwen3-8B | Qwen3-32B |
|---|---|---|
| FinVault 高风险任务 | `finvault-qwen3-8b-financially-malicious-action/probe/model.pt` | `finvault-qwen3-32b-financially-malicious-action/probe/model.pt` |
| 系统提示词泄露 | `prompt-extraction-qwen3-8b-system-prompt-leakage/probe/model.pt` | `prompt-extraction-qwen3-32b-system-prompt-leakage/probe/model.pt` |

Activation Probe 路由同样由“任务 × 模型”确定：

| 任务 | Qwen3-8B | Qwen3-32B |
|---|---|---|
| FinVault 高风险任务 | `finvault-qwen3-8b/best_probe.pt` | `finvault-qwen3-32b/best_probe.pt` |
| 系统提示词泄露 | `prompt-extraction-qwen3-8b/probe/best_probe.pt` | `prompt-extraction-qwen3-32b/probe/best_probe.pt` |

冻结审计展示直接读取逐 case 预测；实时演示服务通过 `--model` 选择并加载对应 8B 或 32B 的两个 checkpoint。
