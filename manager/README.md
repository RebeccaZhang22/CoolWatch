# CoolWatch 独立管理中心

管理者相关的前端、认证、统计接口、数据、配置和测试统一放在项目顶层 `manager/`。
它既可独立运行，也可由演示服务加载同一套模块；独立启动不导入 `backend`、不加载模型。

```text
manager/
├── frontend/             管理登录页、统计界面、样式、浏览器脚本
├── app.py                独立 FastAPI 服务入口
├── api.py                管理 API
├── auth.py               独立管理者账号、密码与会话
├── console.py            页面托管、访问控制、历史管理接口兼容
├── config.py             管理服务配置（只读取 manager/.env）
├── activity_store.py     操作、请求、风险与意向标签数据库
├── activity_middleware.py 服务端请求与 SSE 采集
├── telemetry.py          演示用户浏览器打点接收接口
├── integration.py        原演示服务的接入入口
├── user_directory.py     只读查询已有注册用户与历史 CLI 日志
├── tests/                管理功能回归测试
├── data/                 数据库、运行日志、本地凭证（Git 忽略）
├── .env.example          管理服务配置模板
├── requirements.txt      独立服务的轻量依赖
└── start.sh              独立启动脚本
```

## 启动

在项目根目录执行：

```bash
./manager/start.sh
```

默认监听 `0.0.0.0:18089`，入口为 `http://服务器地址:18089/manager/login.html`。
本机可用 `http://127.0.0.1:18089/`。不需要前端构建，也不需要启动 GPU 服务。
脚本默认使用项目 `.venv/bin/python`，没有该解释器时回退到 `python3`。

```bash
MANAGER_HOST=127.0.0.1 MANAGER_PORT=18090 ./manager/start.sh
# 可指定独立环境；需要的依赖见 manager/requirements.txt
MANAGER_PYTHON=/path/to/python ./manager/start.sh
```

`GET /health` 返回管理服务就绪状态。前端和管理 API 使用同一端口，不需要 CORS 或 API 代理。

## 管理者账号

管理者账号不参与普通用户注册，不接受演示 Cookie、CLI Token 或普通账号的历史 admin 角色。
交互创建账号或更新密码：

```bash
.venv/bin/python -m manager.auth --email owner@example.com
```

密码至少 8 位。默认不创建固定账号或密码，账号创建后无需重启管理服务。
可将 `manager/.env.example` 复制为 `manager/.env`，用 `MANAGER_EMAIL` 和
`MANAGER_PASSWORD` 在启动时开通账号。CLI 更新密码后应同步删除或更新环境中的旧密码，
避免下次启动覆盖。`backend/.env` 不再管理管理员配置。

管理者凭证持久化到 `manager/data/manager.db`；Cookie 为 `pm_manager_session`，
HttpOnly、SameSite=Strict、HTTPS 下 Secure，有效期 8 小时。
退出或修改密码会撤销服务端会话。登录按来源和账号分别限制每 15 分钟 10 次失败。
反向代理部署应正确配置受信任的代理地址。

## 数据与原项目接入

- `manager/data/activity.db` 保存打点、Request、响应、风险和意向备注，使用 SQLite WAL。
- 普通用户账号仍以原项目 `.runtime/prospectmonitor.db` 为唯一数据源。
  独立管理服务通过只读连接查询 ID、邮箱、角色、注册时间，不读取密码或登录凭证。
- 原有 `backend/app.py` 只调用 `manager.integration.install_demo_tracking` 和账号事件钩子。
  其余管理实现、访问控制和页面托管全部位于本目录。两个进程读取同一管理数据目录。
- 浏览器点击采集脚本仍在用户演示前端 `frontend/src/telemetry.js`，向演示服务提交
  `/api/telemetry/events`；独立管理端不接受普通用户认证或打点写入。
- 重启演示 Web 服务后打点生效，独立管理端立即可见新增记录，无需重启管理端或模型。
- 原 `:18088/manager/`、`/admin.html` 和历史 `/api/admin/*` 兼容入口在演示服务加载
  接入代码后仍可用，但只接受独立管理身份。

如更改 `MANAGER_DATA_DIR`，演示进程和管理进程应读取同一 `manager/.env` 或相同环境设置。
相对目录以 `manager/` 为基准。`MANAGER_USER_DB` 与 `MANAGER_USAGE_LOG` 可指定普通用户
数据库和历史 CLI 日志的只读位置。只有 `manager/frontend/` 对外托管，`data/` 不可经 HTTP 下载。
本次目录整理将上一版 `.runtime/manager.db`、`.runtime/activity.db` 移至 `manager/data/`，
原有用户认证数据库保持原位置。

## 功能与统计口径

- 查看注册账号、注册时间、最近活跃、完成试用次数、风险请求数。
- 点击用户查看操作时间线；按时间、类型、请求内容、风险、会话筛选和分页。
- 请求详情包括发送的 JSON、模型最终响应、工具调用、风险类型、检测器、阶段、
  分数、阈值和拦截状态；对照实验保留 baseline/defended 分支。
- 活跃程度分为“仅注册 / 浏览探索 / 已试用 / 持续体验”，基于所选时间范围。
  持续体验指完成至少 5 次模型/检测请求，或至少在 2 个 UTC 日期完成请求。
  意向由团队手动标记“待判断 / 待跟进 / 暂无意向”，可添加备注，不自动推断。
- 风险按请求去重，一次请求可包含多类风险。禁用探针、选择攻击案例或检测器报错
  不会单独产生风险命中。HTTP 200 的 SSE error 也记为失败，缺少最终结果的流记为中断。
- 已有用户可立即显示；启用前未采集的交互无法回溯。历史 CLI 日志不重复导入，
  可使用独立管理会话访问 `/api/admin/usage`。

服务端从用户认证状态归属请求，不信任浏览器上报的用户 ID、时间或风险。
SSE 逐块透传；采集故障不阻断业务。浏览器打点包含页面打开、按钮/链接/折叠面板点击、
下拉框、开关和数值参数变化，通过 Agent session_id 关联请求；支持批量、重试和去重。
浏览器关闭、断网或拦截脚本时可能缺失 UI 打点。`?demo=1` 的静态 mock 模式不打点。

不采集密码输入、自由文本草稿、完整请求头、Cookie、Token 或上传二进制文件。
JSON 明确命名的凭证字段递归脱敏；已发送的 prompt 和模型响应会保存，无法自动识别
自然语言中的所有秘密。上传记录保存接口、内容类型与字节数。
JSON 请求上限 256 KiB，普通响应或单个 SSE 事件上限 2 MiB，超限会标注。
管理统计不改变原有共享模型、配置与 HR 工具状态，也不新增租户隔离或自动清理策略。

## 验证

```bash
.venv/bin/python -m unittest discover -s manager/tests -v
node --check manager/frontend/manager.js
node --check frontend/src/telemetry.js
```

测试涵盖登录体系隔离、会话撤销/过期、限速、跨站写请求、用户归属与去重、SSE、
风险与工具详情、持久化与筛选分页，以及独立服务启动、真实数据读取、数据目录不可下载。
模型结果使用固定响应，仅验证采集契约，不用于评估风险检测准确率。
