# 演示台前端

这是面向普通用户和开发者的攻防演示台。管理者使用独立的 [`manager/`](../manager/README.md) 控制台查看用户活动、请求与风险记录。

首页底部的建议按钮仅来自 `data/hanglvzongheng/conversation_starters.json`，前端不额外添加或过滤案例。点击只把完整问题填入输入框，可继续编辑；用户自行点击“运行 Agent”或按 Enter 后才发送请求。修改该配置后需重启后端。

前端使用原生 HTML、CSS 和 JavaScript modules，无构建步骤。生产和本地演示均由 FastAPI 同源托管，避免浏览器直接访问模型服务造成 CORS、凭证和网络暴露问题。

```bash
# 在项目根目录执行；启动前按根目录 README 配好 backend/.env
bash vllm_setups/run_agent_backend.sh      # 演示台，默认 http://0.0.0.0:18088/login.html
bash manager/start.sh                      # 管理控制台，http://0.0.0.0:18089/manager/
```

只查看静态审计页时仍可使用 `./start-perspective-watch.sh`；完整首页防护演示需要当前 inscope-service 单风险检测实例和独立的业务模型服务。探针未连接时页面显示“检测服务未就绪”，防护模式请求会被拒绝执行，不会退回无防护生成。

先访问 `login.html` 注册或登录；登录后直接进入 `index.html` 演示台。开发者中心提供 CLI/API Token，演示台使用浏览器会话 Cookie，不直接读取 Token。

首页 `index.html` 是统一的 Agent 工作台，默认场景为「客服助手-小航」，也可在左侧切换到「HR 简历筛选」：

- 保留原演示台的顶部三入口、左侧配置栏、中央聊天区和右侧详情抽屉；
- 左侧「Agent 配置」只管理模型、vLLM 端口和生成参数；其下的「上下文配置」分别提供 System Prompt 编辑，以及 RAG 文档上传、查看和删除；
- 「新聊天」会清空当前上传的临时 RAG 文档，内置航旅语料库不受影响；
- 用户直接输入自然消息，不选择场景类别或攻击类型；
- 首页对话建议包含三条普通航旅问题，以及系统提示词窃取、RAG 旅客信息泄露和间接提示词注入三类合成攻击案例；
- 每轮调用 `/api/customer-agent/run/stream`，实时显示 Agent loop 阶段；
- Agent Loop 展示每轮生成前检测、模型生成、环境工具执行及返回下一轮的过程，保留各轮检测结果与拦截位置；等待期间通过心跳显示耗时；
- 页面将生成前检测分为两类：我们的方案（InsScope Detect）和护栏（包含 Qwen3Guard、护栏 A、护栏 B 三种市面已有产品）；后缀概率探针与护栏 C 保留后端兼容能力但不在首页显示；
- 默认启用我们的方案，护栏默认关闭；只有后端报告为可用的方法才会被预选（当前为单风险探针），护栏勾选可一次启用全部竞品，竞品列表默认展开，可收起后再展开并分别选择，右侧结果仍保留各检测器的独立信号；
- 检测风险名称来自 `/api/customer-agent/health` 的 `enabled_risks`，页面不再写死某类风险；
- `/api/customer-agent/compare` 的两次独立运行对照目前没有界面入口，只能通过 API 调用；
- 右侧只展示本轮防护信号、工具/RAG 轨迹、reasoning 元数据和客户端泄漏结果；RAG 轨迹包含 BM25 Top-K、原始分数和 chunk ID。

HR 场景使用 `/api/customer-agent/hr` 下的接口，可通过 `/index.html?scenario=hr` 直接进入；旧 `hr.html` 自动跳转。输入区的文件选择器支持添加内置简历和测评资料，模型通过工具读取所选文件。场景切换建立新会话，HR 候选人档案保存在本地 SQLite 中。案例、工具及数据边界见 [HR 演示说明](../data/hr_agent/README.md)。

其他独立审计入口：

- `audit.html`：实验审计
- `cases.html`：Case Study 清单
- `case-study.html`：风险越权流程对比
- `indirect-replay.html`：间接提示词注入冻结轨迹回放

`src/api.js` 负责场景 API 和 SSE 响应，`src/app.js` 负责工作台与场景切换，`src/agent-flow.js` 管理运行流程状态，`src/workspace-files.js` 提供 HR 资料选择器，`src/customer-agent.css` 是首页样式。旧审计页面继续使用各自脚本与共享样式。

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

## 独立管理者视图

`../manager/frontend/login.html` 和 `../manager/frontend/index.html` 使用独立登录体系，不进入用户工作台或开发者中心。`src/telemetry.js` 负责浏览器交互打点，请求与风险由服务端采集。开通账号及数据范围见 [管理中心说明](../manager/README.md)。
