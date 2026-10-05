# Qwen3-8B 中文间接提示注入评测集

这是发布所用的中文冻结评测。100 个 sample index、decision point、16 个 strict setting 和抽样 seed 均保持不变。

每条 `cases.jsonl` 记录包含在攻击首次进入 Qwen3-8B 上下文时的完整
replay request。中文化范围包括：

- system prompt 和用户任务；
- assistant 已有的自然语言内容；
- 工具及参数的人类可读说明；
- 工具返回的业务环境文本；
- 注入攻击文本。

工具函数名、参数键、历史 tool-call arguments、账号、日期、金额、URL、
邮箱和结构边界保持不变。这样既覆盖中文环境和中文注入，又不会改变工具
API 契约。翻译由独立的 `Qwen/Qwen3.5-9B` 在 temperature 0 下完成，
受保护标识符会在翻译前替换为占位符并在翻译后逐一恢复。

完整性信息在 `case_manifest.json` 和 `settings.json` 中。翻译缓存和生成脚本属于构建期数据，不包含在最小运行闭包内。

本评测在每个注入首次可见的 assistant 边界执行检测，并另外生成一次
Qwen3-8B 的下一步回复。回复中的工具调用只记录、不执行，因此行为结果是
“即时攻击跟随倾向”，不是完整 AgentDojo 任务结束后的攻击成功率。

Qwen3Guard 和网易易盾只接收 `tool_result`：本轮新进入视野的完整
tool-result message，不从中抽取或裁剪“纯攻击句”。产物记录
`input_mode=tool_result`、输入 SHA-256 和字符数。当前 100 条中文结果为：
Qwen3Guard `54%`，网易易盾 `0%`，两组调用均无错误。
