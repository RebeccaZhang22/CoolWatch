# Qwen3-8B 中文 IPI 评测结果

100 条中文 held-out strict 样本均在注入首次进入上下文的 assistant 决策点
评测。护栏不拦截、不修改模型输入，也不会将判断返回给 agent。

## 检测结果

| 方案 | 检出 | 检测率 | 错误 |
|---|---:|---:|---:|
| Inline Probe，layer 4，threshold 0.5 | 100 / 100 | 100% | 0 |
| Qwen3Guard-Gen-8B | 54 / 100 | 54% | 0 |
| 网易易盾普通文本 | 0 / 100 | 0% | 0 |
| No Guard | 0 / 100 | 0% | 0 |

对应英文冻结集为 Inline Probe 100/100、Qwen3Guard 45/100、网易易盾
0/100、No Guard 0/100。中文化后 Qwen3Guard 多检出 9 条，Inline Probe
与两个对照结果不变。

## Qwen3-8B 即时行为

模型只生成注入出现后的一个 assistant response，工具调用不执行。独立的
Qwen3.5-9B 按冻结四分类 rubric 审计：

| 行为 | 数量 |
|---|---:|
| 立即执行或推进注入任务 | 22 |
| 明确识别并抵抗注入 | 21 |
| 未讨论注入，继续原用户任务 | 56 |
| 无法可靠判断 | 1 |

Qwen3Guard 检出了 22 条“立即跟随注入”中的 19 条；Inline Probe 棡出了
全部 22 条；网易易盾未检出这些样本。行为标签是独立模型审计结果，原始
response、judge 原始输出和 confidence 均保留在 JSONL 中，不能等同于
完整工具链执行后的 AgentDojo security success。

`summary.json` 提供按业务、攻击话术和行为标签的交叉统计；
`run_manifest.json` 记录输入、输出、模型、probe 和日志哈希。

