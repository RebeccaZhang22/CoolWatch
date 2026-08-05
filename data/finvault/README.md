# FinVault audit data

This directory is the standalone, repository-safe FinVault dataset consumed by
the audit backend. Runtime code must not depend on the local `exp/FinVault`
checkout.

## Files

- `cases.jsonl`: 1,070 ordered cases (107 original attacks, 856 synthesized
  attacks, and 107 normal tasks), including Chinese display translations.
- `system_prompts.jsonl`: the exact 31 base-mode system prompts used by the
  experiments, plus their Chinese display translations.
- `manifest.json`: counts, provenance, and SHA-256 checksums.

## Case-to-prompt mapping

Every row in `cases.jsonl` is a complete query instance. Its `query_id` is
unique, and its `system_prompt_id` points directly to the row with the same
`system_prompt_id` in `system_prompts.jsonl`. `sample_index` joins the case to
the corresponding model and guard outputs under `results/audit_data`.

For example, `finvault-query-0000` uses `finvault-system-00`; the latter is the
base system prompt for sandbox scenario `00`.

The evaluation outputs remain under `results/audit_data/finvault_*`; this folder
contains source/display data rather than model outputs.
