# Perspective Watch 前端

前端使用原生 HTML、CSS 和 JavaScript modules，无构建步骤。生产和本地演示均由 FastAPI 同源托管，避免浏览器直接访问模型服务造成 CORS、凭证和网络暴露问题。

```bash
./start-perspective-watch.sh
```

入口页面：

- `index.html`：攻防演示台
- `audit.html`：实验审计
- `cases.html`：Case Study 清单
- `case-study.html`：风险越权流程对比
- `indirect-replay.html`：间接提示词注入冻结轨迹回放

`src/api.js` 负责后端适配和 SSE 流式响应，`src/app.js` 负责演示台交互，`src/audit.js` 负责审计数据展示，`src/method-details.js` 是两处页面共用的方法说明。

页面默认请求当前 origin。仅在纯静态 UI 开发时，可在载入 `app.js` 前设置：

```html
<script>
  window.AGENT_GUARD_USE_MOCK = true;
</script>
```
