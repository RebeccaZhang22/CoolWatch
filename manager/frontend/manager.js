const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const date = value => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
const labels = { registered: "仅注册", exploring: "浏览探索", tried: "已试用", engaged: "持续体验", unreviewed: "待判断", follow_up: "待跟进", not_interested: "暂无意向", completed: "已完成", running: "进行中", error: "失败", interrupted: "已中断", register: "注册账号", login: "登录账号", page_view: "打开页面", click: "点击", change: "修改配置" };
const riskLabels = { ipi: "间接提示词注入", harmful: "有害内容", prompt_leakage: "提示词泄露", detector_risk: "检测器风险", attack_succeeded: "攻击成功", blocked: "风险拦截", "exposure:system_prompt": "系统提示词暴露", "exposure:rag": "知识库内容暴露", "exposure:reasoning": "推理内容暴露" };
const state = { user: null, users: [], userPage: 1, eventPage: 1, leadUser: null, usersVersion: 0, eventsVersion: 0, overviewVersion: 0 };

async function request(path, options = {}) {
  const response = await fetch(`/api/manager${path}`, { ...options, credentials: "same-origin", headers: { "Content-Type": "application/json", ...options.headers } });
  if (response.status === 401) { location.replace("/manager/login.html"); throw new Error("管理者登录已过期。"); }
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `请求失败（${response.status}）`);
  return payload;
}

function dates() {
  const params = new URLSearchParams();
  for (const name of ["since", "until"]) if ($(`#${name}`).value) params.set(name, new Date($(`#${name}`).value).toISOString());
  return params;
}
function error(message) { $("#error").textContent = message; $("#error").hidden = !message; }
function safely(action) { return action().catch(failure => error(failure.message)); }
function badge(value, color = "") { return `<span class="badge ${color}">${escape(labels[value] || value)}</span>`; }
function pagination(selector, data, load) {
  const container = $(selector); container.replaceChildren();
  const prev = document.createElement("button"); prev.textContent = "← 上一页"; prev.disabled = data.page <= 1;
  prev.onclick = () => safely(() => load(data.page - 1));
  const info = document.createElement("span"); info.textContent = `${data.page} / ${data.pages}`;
  const next = document.createElement("button"); next.textContent = "下一页 →"; next.disabled = data.page >= data.pages;
  next.onclick = () => safely(() => load(data.page + 1));
  container.append(prev, info, next);
}

async function overview() {
  const version = ++state.overviewVersion;
  const params = dates(); if (state.user) params.set("user_id", state.user.id);
  const data = await request(`/overview?${params}`);
  if (version !== state.overviewVersion) return;
  for (const [id, key] of [["registeredUsers", "registered_users"], ["activeUsers", "active_users"], ["runs", "runs"], ["risks", "risky_requests"]]) $(`#${id}`).textContent = data[key].toLocaleString();
  $("#requestCount").textContent = `${data.requests} 次接口请求 · ${data.interactions} 次交互`;
  $("#blockedCount").textContent = `${data.blocked} 次拦截 · ${data.errors} 次请求异常`;
  const max = Math.max(1, ...data.risk_distribution.map(item => item.count));
  $("#riskDistribution").innerHTML = data.risk_distribution.map(item => `<div class="risk-bar"><span>${escape(riskLabels[item.kind] || item.kind)}</span><div class="risk-bar-track"><div class="risk-bar-fill" style="width:${100 * item.count / max}%"></div></div><strong>${item.count}</strong></div>`).join("") || '<p class="empty">当前范围内暂无已记录的风险</p>';
}

async function loadUsers(page = 1) {
  const version = ++state.usersVersion; const params = dates();
  params.set("q", $("#userSearch").value.trim()); params.set("engagement", $("#engagement").value);
  params.set("lead_status", $("#leadFilter").value); params.set("page", page);
  const data = await request(`/users?${params}`);
  if (version !== state.usersVersion) return;
  state.users = data.users; state.userPage = data.page; $("#usersCount").textContent = data.total;
  $("#userRows").innerHTML = data.users.map(user => `<tr>
    <td><button class="email-button" data-user="${escape(user.id)}">${escape(user.email)}</button><small>${escape(date(user.created_at))}</small></td>
    <td>${escape(date(user.last_active))}</td><td>${user.runs} 次</td><td>${user.interactions} / ${user.risky_requests}</td>
    <td>${badge(user.engagement, ["engaged", "tried"].includes(user.engagement) ? "green" : "gray")}</td>
    <td>${badge(user.lead.status, user.lead.status === "follow_up" ? "orange" : "gray")}</td>
    <td><div class="row-actions"><button class="text-button" data-user="${escape(user.id)}">查看记录</button><button class="text-button" data-lead="${escape(user.id)}">标记意向</button></div></td></tr>`).join("") || '<tr><td colspan="7" class="empty">没有符合条件的用户</td></tr>';
  pagination("#userPages", data, loadUsers);
}

async function loadEvents(page = 1) {
  const version = ++state.eventsVersion; const params = dates();
  if (state.user) params.set("user_id", state.user.id);
  for (const [param, id] of [["q", "eventSearch"], ["kind", "kind"], ["session_id", "sessionFilter"]]) params.set(param, $(`#${id}`).value.trim());
  params.set("risk_only", $("#riskOnly").checked); params.set("page", page);
  const data = await request(`/events?${params}`);
  if (version !== state.eventsVersion) return;
  state.eventPage = data.page; $("#eventsCount").textContent = data.total;
  $("#selectedUser").textContent = state.user ? `${state.user.email} 的操作时间线 · 概览同时显示该用户的数据` : "全部用户的操作时间线";
  $("#clearUser").hidden = !state.user;
  $("#eventRows").innerHTML = data.events.map(event => `<tr>
    <td>${escape(date(event.created_at))}<small>${escape(event.email)}</small></td>
    <td>${escape(labels[event.name] || event.name)}<small>${escape(event.properties.label || event.path)}</small></td>
    <td>${badge(event.status, event.status === "completed" ? "green" : event.status === "error" ? "red" : "orange")}</td>
    <td>${event.risk_count ? badge(`${event.risk_count} 项${event.blocked ? " · 已拦截" : ""}`, "red") : '<span class="muted">—</span>'}</td>
    <td>${event.duration_ms == null ? "—" : `${(event.duration_ms / 1000).toFixed(2)} s`}</td>
    <td><button class="text-button" data-detail="${escape(event.id)}">查看详情 ↗</button></td></tr>`).join("") || '<tr><td colspan="6" class="empty">当前范围内暂无操作记录</td></tr>';
  pagination("#eventPages", data, loadEvents);
}

function jsonSection(title, value, open = false) {
  return `<details ${open ? "open" : ""}><summary>${escape(title)}</summary><pre>${escape(JSON.stringify(value ?? {}, null, 2))}</pre></details>`;
}
async function showDetail(id) {
  const dialog = $("#detailDialog"); $("#detailBody").innerHTML = '<p class="empty">正在读取记录…</p>';
  if (!dialog.open) dialog.showModal();
  try {
    const event = await request(`/events/${encodeURIComponent(id)}`);
    $("#detailTitle").textContent = labels[event.name] || event.name;
    const fields = [["用户", event.email], ["时间", date(event.created_at)], ["记录 ID", event.id], ["会话 ID", event.session_id || "—"], ["请求", `${event.method} ${event.path}`], ["结果", `${labels[event.status]}${event.http_status ? ` · HTTP ${event.http_status}` : ""}`]];
    const risks = event.risks.map(item => `<article class="risk-card"><strong>${escape(riskLabels[item.kind] || item.kind)}</strong> ${badge(item.blocked ? "已拦截" : "已记录", item.blocked ? "orange" : "gray")}<p>${escape([item.branch, item.detector, item.stage, item.score != null ? `分数 ${item.score}` : "", item.threshold != null ? `阈值 ${item.threshold}` : ""].filter(Boolean).join(" · "))}</p><p>${escape(item.detail || "")}</p></article>`).join("");
    const response = event.response || {};
    const trajectories = response.baseline ? { baseline: response.baseline.tool_trace, defended: response.defended?.tool_trace } : response.tool_trace;
    $("#detailBody").innerHTML = `<dl class="detail-meta">${fields.map(([key, value]) => `<div><dt>${escape(key)}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>
      ${event.properties.request_truncated || event.properties.response_truncated ? '<p class="error">该记录超过采集上限，内容有截断，请以原始服务日志为准。</p>' : ""}
      <h3>风险结果</h3>${risks || '<p class="muted small">此记录没有已采集的风险命中。未检测、失败或中断不代表安全。</p>'}
      ${event.kind === "interaction" ? jsonSection("交互内容", event.properties, true) : jsonSection("Request · 请求内容", event.request, true)}
      ${trajectories ? jsonSection("模型工具调用与交互轨迹", trajectories, true) : ""}
      ${event.kind === "request" ? jsonSection("Response · 完整采集结果", response) : ""}
      ${event.session_id ? '<button class="secondary" id="viewSession">查看同一用户的此会话</button>' : ""}`;
    $("#viewSession")?.addEventListener("click", () => { state.user = { id: event.user_id, email: event.email }; $("#sessionFilter").value = event.session_id; $("#riskOnly").checked = false; $("#kind").value = ""; $("#eventSearch").value = ""; dialog.close(); safely(() => Promise.all([loadEvents(), overview()])); });
  } catch (failure) { $("#detailBody").textContent = failure.message; }
}

async function refresh() {
  error(""); $("#refresh").disabled = true;
  try { await Promise.all([overview(), loadUsers(state.userPage), loadEvents(state.eventPage)]); $("#updated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`; }
  finally { $("#refresh").disabled = false; }
}
$("#userRows").addEventListener("click", event => {
  const userButton = event.target.closest("[data-user]"); const leadButton = event.target.closest("[data-lead]");
  if (userButton) {
    state.user = state.users.find(user => user.id === userButton.dataset.user);
    $("#sessionFilter").value = "";
    safely(() => Promise.all([loadEvents(), overview()])); $("#events").scrollIntoView({ behavior: "smooth" });
  }
  if (leadButton) {
    const user = state.users.find(user => user.id === leadButton.dataset.lead); state.leadUser = user;
    $("#leadUser").textContent = user.email; $("#leadStatus").value = user.lead.status; $("#leadNote").value = user.lead.note;
    $("#leadError").textContent = ""; $("#leadDialog").showModal();
  }
});
$("#eventRows").addEventListener("click", event => { const button = event.target.closest("[data-detail]"); if (button) showDetail(button.dataset.detail); });
$("#leadForm").addEventListener("submit", async event => {
  event.preventDefault(); $("#saveLead").disabled = true;
  try { await request(`/users/${encodeURIComponent(state.leadUser.id)}/lead`, { method: "PATCH", body: JSON.stringify({ status: $("#leadStatus").value, note: $("#leadNote").value }) }); $("#leadDialog").close(); await loadUsers(state.userPage); }
  catch (failure) { $("#leadError").textContent = failure.message; }
  finally { $("#saveLead").disabled = false; }
});
for (const button of document.querySelectorAll("[data-close]")) button.onclick = () => document.getElementById(button.dataset.close).close();
for (const [id, action] of [["userFilters", () => loadUsers()], ["eventFilters", () => loadEvents()], ["dateForm", () => { state.userPage = 1; state.eventPage = 1; return refresh(); }]]) {
  $(`#${id}`).addEventListener("submit", event => { event.preventDefault(); error(""); safely(action); });
}
$("#clearUser").onclick = () => { state.user = null; $("#sessionFilter").value = ""; safely(() => Promise.all([loadEvents(), overview()])); };
$("#resetDates").onclick = () => { $("#since").value = ""; $("#until").value = ""; safely(refresh); };
$("#refresh").onclick = () => safely(refresh);
$("#logout").onclick = () => safely(async () => { await request("/logout", { method: "POST" }); location.replace("/manager/login.html"); });
for (const link of document.querySelectorAll(".sidebar nav a")) link.onclick = () => { document.querySelectorAll(".sidebar nav a").forEach(item => item.classList.toggle("selected", item === link)); };
safely(async () => { const data = await request("/me"); $("#identity").textContent = data.manager.email; await refresh(); });
