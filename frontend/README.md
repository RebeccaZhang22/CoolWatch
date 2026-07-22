# CoolWatch 前端演示

这是按照 `doc/需求文档.md` 实现的前端页面。默认会请求本地 FastAPI 后端 `http://127.0.0.1:8000/api/chat`。

## 运行

```bash
python3 -m http.server 4173 --directory frontend
```

然后访问：

```text
http://127.0.0.1:4173
```

## 目录

```text
frontend/
├── index.html
└── src/
    ├── app.js
    ├── mock-data.js
    └── styles.css
```

`app.js` 负责页面状态和交互，`api.js` 负责后端适配，`mock-data.js` 负责场景、攻击模板和 mock 兜底数据。

## 对接 FastAPI

页面默认请求 FastAPI。如果需要临时回到 mock 模式，在 `index.html` 引入 `app.js` 之前注入：

```html
<script>
  window.AGENT_GUARD_USE_MOCK = true;
</script>
```

前端会向 `POST /api/chat` 发送需求文档中定义的请求体，并附带当前场景、编辑后的 System Prompt 和文档配置。
