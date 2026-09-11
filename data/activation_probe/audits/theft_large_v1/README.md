# Activation Probe 大规模窃取审计集 v1

这是面向当前法规条款 Agent 的单轮合成审计集，只评估
`theft-unified-qwen3-8b-v16-multilayer-mlp` Activation Probe，不调用
SafeGauge 或其他护栏。

## 数据规模

- 10,000 条规范化后唯一的用户请求；
- 5,000 条窃取攻击：System Prompt、私有 RAG、私有 CoT、私有
  Skill/tool 各 1,250 条；
- 3,000 条主题相近的 hard negative；
- 1,000 条法规 Agent 分布内正常问题；
- 1,000 条通用正常问题；
- 中英文各占 50%，正负类各占 50%。

攻击数据本身有 5,000 条，多于 v16 说明中严格测试集的 3,888 个总样本。

## 切分和阈值

`calibration` 与 `audit` 按模板族切分，同一模板族不会跨集合。误伤率约束阈值
只能在 `calibration` 上选择，再应用到 `audit`；不得查看 `audit` 标签后回调阈值。

## 文件

- `cases.jsonl`：冻结审计请求与标签；
- `manifest.json`：数据构成、哈希、标签定义、Agent/Probe 版本和历史 query
  精确重合检查。

## 适用边界

这是组合模板生成的合成压力测试，不等同于独立采集的真实流量。主审计固定使用当前
法规条款 Agent 的渲染后 System Prompt，因此也不能替代跨 System Prompt 的泛化评测。
