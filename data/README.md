# RaccoonBench Prompt Data

This folder contains the self-contained inputs used by the published demo.

## Layout

```text
data/
  TRAINING_DATA.md
  finvault/
    cases.jsonl
    system_prompts.jsonl
    manifest.json
  system_prompt_extraction/cn/
    system_prompts/<system-name>/system_prompt.md
    attacks/<attack-set>/<attack-category>/<prompt-name>/prompt.json
```

The prompt-extraction directory uses Chinese display names. Attack metadata keeps stable canonical ids.

## Scope

- 18 banking system prompts
- 55 prompt-extraction attack queries
- 1,070 FinVault cases and 31 FinVault system prompts

## Attack Fields

- `attack_set`: attack set label in the file language
- `attack_set_id`: stable canonical attack set id
- `attack_set_en`: canonical English attack-set label
- `category`: category label in the file language
- `category_id`: stable canonical category id
- `category_en`: canonical English category label
- `prompt_name`: RaccoonBench prompt file name
- `query`: attack query text

## FinVault

`data/finvault/` is a self-contained export for the financial-agent audit UI. See `data/finvault/README.md` for its schema. Runtime code does not read any `exp/` checkout.

### Probe training data

`finvault/cases.jsonl` 是源案例目录，不是可以直接训练的二分类数据。
如何展开逐轮对话、进行语义标注、按 source group 切分并生成
SafeGauge/Activation Probe 共用监督数据，见 [TRAINING_DATA.md](TRAINING_DATA.md)。
