# ProspectMonitor 前端

前端使用原生 HTML、CSS 和 JavaScript modules，无构建步骤。生产和本地演示均由 FastAPI 同源托管，避免浏览器直接访问模型服务造成 CORS、凭证和网络暴露问题。

```bash
./vllm_setups/run_probe_vllm_qwen3_8b.sh start
./vllm_setups/run_customer_agent_backend.sh
```

只查看静态审计页时仍可使用 `./start-perspective-watch.sh`；完整首页防护演示需要上面的 patched Qwen3-8B 服务。

先访问 `login.html` 注册或登录；登录后会进入 CLI Token 页面，再通过链接进入 ProspectWatch。Token 仅用于 CLI/API 调用，`index.html` 演示台使用浏览器会话 Cookie，不直接读取 Token。

首页 `index.html` 是单一「机构财富管理与资金风控 Agent」工作台：

- 保留原演示台的顶部三入口、左侧配置栏、中央聊天区和右侧详情抽屉；
- 左侧「Agent 配置」只管理模型、vLLM 端口和生成参数；其下的「上下文配置」分别提供 System Prompt 编辑，以及 RAG 文档上传、查看和删除；
- 「新聊天」会清空当前上传的临时 RAG 文档，内置金融语料库不受影响；
- 用户直接输入自然消息，不选择场景类别或攻击类型；
- 首页对话建议聚焦正常的财富管理业务问题；RAG 窃取和外部注入攻击仍可通过隐藏评估接口调用；
- 每轮调用 `/api/customer-agent/run/stream`，实时显示 Agent loop 阶段；
- 页面将生成前检测分为两类：我们的方案（基于隐藏层的可解释性技术）和护栏（包含 Qwen3Guard、网易易盾、方寸跃迁三种市面已有产品）；后缀概率探针与 Llama 安全护栏保留后端兼容能力但不在首页显示；
- 默认启用我们的方案，护栏默认关闭；勾选护栏可一次启用全部竞品，也可以展开后分别选择，右侧结果仍保留各检测器的独立信号；
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
