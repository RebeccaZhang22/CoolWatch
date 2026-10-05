# Demo 前端

首页底部的建议按钮仅来自 `data/hanglvzongheng/conversation_starters.json`，前端不额外添加或过滤案例。点击只把完整问题填入输入框，可继续编辑；用户自行点击“运行 Agent”或按 Enter 后才发送请求。修改该配置后需重启后端。

前端使用原生 HTML、CSS 和 JavaScript modules，无构建步骤。生产和本地演示均由 FastAPI 同源托管，避免浏览器直接访问模型服务造成 CORS、凭证和网络暴露问题。

```bash
./vllm_setups/run_probe_bank_qwen3_8b.sh
./vllm_setups/run_customer_agent_backend.sh
```

只查看静态审计页时仍可使用 `./start-perspective-watch.sh`；完整首页防护演示需要Probe Bank 和独立的业务模型服务。

先访问 `login.html` 注册或登录；登录后会进入 CLI Token 页面，再通过链接进入 ProspectWatch。Token 仅用于 CLI/API 调用，`index.html` 演示台使用浏览器会话 Cookie，不直接读取 Token。

首页 `index.html` 是单一「客服助手-小航」工作台：

- 保留原演示台的顶部三入口、左侧配置栏、中央聊天区和右侧详情抽屉；
- 左侧「Agent 配置」只管理模型、vLLM 端口和生成参数；其下的「上下文配置」分别提供 System Prompt 编辑，以及 RAG 文档上传、查看和删除；
- 「新聊天」会清空当前上传的临时 RAG 文档，内置航旅语料库不受影响；
- 用户直接输入自然消息，不选择场景类别或攻击类型；
- 首页对话建议包含三条普通航旅问题，以及系统提示词窃取、RAG 旅客信息泄露和间接提示词注入三类合成攻击案例；
- 每轮调用 `/api/customer-agent/run/stream`，实时显示 Agent loop 阶段；
- 页面将生成前检测分为两类：我们的方案（基于隐藏层的可解释性技术）和护栏（包含 Qwen3Guard、护栏 A、护栏 B 三种市面已有产品）；后缀概率探针与护栏 C 保留后端兼容能力但不在首页显示；
- 默认启用我们的方案，护栏默认关闭；勾选护栏可一次启用全部竞品，竞品列表默认展开，可收起后再展开并分别选择，右侧结果仍保留各检测器的独立信号；
- 可用同一条消息调用 `/api/customer-agent/compare` 做两次独立运行对照；
- 右侧只展示本轮防护信号、工具/RAG 轨迹、reasoning 元数据和客户端泄漏结果；RAG 轨迹包含 BM25 Top-K、原始分数和 chunk ID。

其他独立审计入口：

- `audit.html`：实验审计
- `cases.html`：Case Study 清单
- `case-study.html`：风险越权流程对比
- `indirect-replay.html`：间接提示词注入冻结轨迹回放

`src/api.js` 只负责 Customer Agent API 和 SSE 响应，`src/app.js` 只负责单 Agent 工作台交互，`src/customer-agent.css` 是首页独立样式。旧审计页面继续使用各自脚本与共享样式。

页面默认请求当前 origin。仅在纯静态 UI 开发时，可在载入 `app.js` 前设置：

```html
<script>
  window.AGENT_GUARD_USE_MOCK = true;
</script>
```

## Demo 默认配置与案例

- Agent temperature 每次页面加载为 1，本轮手动调整只在当前页面生效。
- 产品名称为 Demo，业务场景为客服助手-小航；所有攻击案例中的旅客、订单和链接均为合成演示数据。
- 竞品显示为护栏 A/B/C/D，Qwen3Guard 保留原名；内部检测器 ID 不变。
- 三个攻击案例显示为“系统提示词窃取”“RAG 旅客信息泄露”和“间接提示词注入”。
- IPI 案例通过 MU5107 延误公告检索到合成攻击文档，模拟外部资料伪造办理指令；工具只连接演示 Mock，不会执行真实退票或发送通知。
- 真实模型复测入口：`python -m regression.retest_demo_cases --output diagnostics/demo-live`。temperature=1 的生成结果会波动，检测结论以每次完整返回为准。
