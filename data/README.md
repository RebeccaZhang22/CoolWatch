# RaccoonBench Prompt Data

This folder contains the self-contained inputs used by the published demo.

## Layout

```text
data/
  TRAINING_DATA.md
  customer_agent/
    scenario.json
    agent/
    skills/
    rag/
    attacks/
    evaluation/
    tools/
    orders/
  legal_regulations_agent/
    scenario.json
    agent/
    skills/
    rag/
    attacks/
    evaluation/
    tools/
    examples/
  finvault/
    cases.jsonl
    system_prompts.jsonl
    manifest.json
  system_prompt_extraction/cn/
    system_prompts/<system-name>/system_prompt.md
    attacks/<attack-set>/<attack-category>/<prompt-name>/prompt.json
```

The prompt-extraction directory uses Chinese display names. Attack metadata keeps stable canonical ids.

`data/customer_agent/` 是统一客服 Agent 的运行时场景配置，包含可组合的 System Prompt、Skill、Reasoning Policy、RAG、自然对话建议、工具和合成订单；攻击样例与 canary 单独放在评估链路中，不参与首页场景选择。目录结构与修改规则见 [Customer Agent 场景数据](customer_agent/README.md)。

`data/legal_regulations_agent/` 是版本化法律条款 RAG 的合成演示数据，包含历史版、修订决定、现行整合版、实施办法、草案、变更事件流和时态检索用例。所有法规均为虚构内容；结构说明见 [法律法规条款 Agent 场景数据](legal_regulations_agent/README.md)。

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
