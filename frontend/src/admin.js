async function request(path) {
  const response = await fetch(path, { credentials: "include", headers: { Accept: "application/json" } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error?.message || "请求失败");
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[char]);
}

function dateLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString([], {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function renderPagination(container, page, pages, loader) {
  const nodes = [];
  const addButton = (label, target, disabled = false, current = false) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.disabled = disabled;
    if (current) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => loader(target));
    nodes.push(button);
  };
  addButton("上一页", page - 1, page <= 1);
  const visible = new Set([1, pages]);
  for (let value = Math.max(1, page - 2); value <= Math.min(pages, page + 2); value += 1) visible.add(value);
  let previous = 0;
  for (const value of [...visible].sort((left, right) => left - right)) {
    if (previous && value - previous > 1) {
      const dots = document.createElement("span");
      dots.textContent = "…";
      nodes.push(dots);
    }
    addButton(String(value), value, value === page, value === page);
    previous = value;
  }
  addButton("下一页", page + 1, page >= pages);
  container.replaceChildren(...nodes);
}

async function loadUsers(page = 1) {
  const rows = document.querySelector("#adminUsers");
  const status = document.querySelector("#usersStatus");
  try {
    const payload = await request(`/api/admin/users?page=${page}&page_size=10`);
    document.querySelector("#registeredUsers").textContent = String(payload.total);
    status.textContent = `共 ${payload.total} 位 · 每页 10 位`;
    rows.innerHTML = payload.users.map((user) => `
      <tr>
        <td class="admin-email">${escapeHtml(user.email)}</td>
        <td><span class="admin-role ${user.role === "admin" ? "admin" : ""}">${user.role === "admin" ? "管理员" : "成员"}</span></td>
        <td>${escapeHtml(dateLabel(user.created_at))}</td>
        <td>${escapeHtml(user.api_calls)}</td>
        <td><code title="${escapeHtml(user.id)}">${escapeHtml(user.id)}</code></td>
      </tr>`).join("");
    if (!payload.users.length) rows.innerHTML = '<tr><td colspan="5">暂无注册用户</td></tr>';
    renderPagination(document.querySelector("#usersPagination"), payload.page, payload.pages, loadUsers);
  } catch (error) {
    status.textContent = "加载失败";
    rows.innerHTML = `<tr><td colspan="5"><div class="admin-error">${escapeHtml(error.message)}</div></td></tr>`;
  }
}

function riskBadge(perRisk, key) {
  const value = perRisk?.[key];
  if (!value) return '<span class="admin-risk unknown">未检测</span>';
  const score = Number(value.score);
  const scoreLabel = Number.isFinite(score) ? `${(score * 100).toFixed(1)}%` : "—";
  return `<span class="admin-risk ${value.flagged ? "block" : "pass"}">${value.flagged ? "风险" : "通过"} · ${escapeHtml(scoreLabel)}</span>`;
}

async function loadLogs(page = 1) {
  const rows = document.querySelector("#adminLogs");
  const status = document.querySelector("#logsStatus");
  try {
    const payload = await request(`/api/admin/usage?page=${page}&page_size=10`);
    document.querySelector("#totalCalls").textContent = String(payload.total);
    document.querySelector("#blockedCalls").textContent = String(payload.blocked);
    status.textContent = `共 ${payload.total} 条 · 每页 10 条`;
    rows.innerHTML = payload.events.map((event) => `
      <tr>
        <td>${escapeHtml(dateLabel(event.created_at))}</td>
        <td class="admin-email">${escapeHtml(event.account_email || "未知账户")}</td>
        <td class="admin-query"><details><summary>${escapeHtml(event.query || "空消息")}</summary></details></td>
        <td>${riskBadge(event.per_risk, "harmful")}</td>
        <td>${riskBadge(event.per_risk, "prompt_leakage")}</td>
        <td>${riskBadge(event.per_risk, "ipi")}</td>
        <td><span class="admin-action ${event.action === "block" ? "block" : "pass"}">${event.action === "block" ? "已拦截" : event.action === "pass" ? "已放行" : escapeHtml(event.action || "—")}</span></td>
        <td>${escapeHtml(event.usage?.input_tokens ?? "—")}</td>
        <td><code title="${escapeHtml(event.request_id)}">${escapeHtml(event.request_id || "—")}</code></td>
      </tr>`).join("");
    if (!payload.events.length) rows.innerHTML = '<tr><td colspan="9">暂无 API 调用记录</td></tr>';
    renderPagination(document.querySelector("#logsPagination"), payload.page, payload.pages, loadLogs);
  } catch (error) {
    status.textContent = "加载失败";
    rows.innerHTML = `<tr><td colspan="9"><div class="admin-error">${escapeHtml(error.message)}</div></td></tr>`;
  }
}

async function initializeAdmin() {
  try {
    const payload = await request("/api/auth/me");
    if (payload.user?.role !== "admin") {
      window.location.replace("./account.html");
      return;
    }
    document.querySelector("#adminIdentity").textContent = payload.user.email;
    await Promise.all([loadUsers(), loadLogs()]);
  } catch {
    window.location.replace("./account.html");
  }
}

initializeAdmin();
