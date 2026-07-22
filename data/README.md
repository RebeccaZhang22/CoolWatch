# RaccoonBench Prompt Data

This folder contains the system prompts and attack queries used in the local full attack run, exported as one JSON file per prompt.

## Layout

```text
data/
  manifest.json
  en/
    system_prompts/<system-name>/prompt.json
    attacks/<attack-set>/<attack-category>/<prompt-name>/prompt.json
  cn/
    system_prompts/<system-name>/prompt.json
    attacks/<attack-set>/<attack-category>/<prompt-name>/prompt.json
```

The English directory keeps RaccoonBench-style labels where possible. The Chinese directory uses translated display directory names. Stable canonical ids are stored inside each JSON file.

## Scope

- 196 system prompts from `GPTs50` and `GPTs146`
- 54 attack queries from the RaccoonBench full attack set
- Attack set composition: 44 singular attacks and 10 compound attacks

## Manifest

`manifest.json` records source metadata and indexes every generated `prompt.json` file. This index is useful for static frontends that cannot list directories at runtime.

## Shared Fields

- `id`: stable prompt/query id
- `source`: source dataset name
- `source_path`: original local RaccoonBench path
- `language`: `en` or `cn`
- `latest_eval`: aggregate result from `exp/raccoon_results_full/raccoon_20260719_181515`

## System Prompt Fields

- `name`: display name in the file language
- `name_en`: English name, present in Chinese files
- `full_system_prompt`: complete system prompt text
- `user_prompt`: core user-defined prompt text used as the extraction target in the local run

## Attack Fields

- `attack_set`: attack set label in the file language
- `attack_set_id`: stable canonical attack set id
- `attack_set_en` / `attack_set_cn`: paired translated attack set labels
- `category`: category label in the file language
- `category_id`: stable canonical category id
- `category_en` / `category_cn`: paired translated category labels
- `prompt_name`: RaccoonBench prompt file name
- `query`: attack query text
