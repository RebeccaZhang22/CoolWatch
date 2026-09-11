const base = window.AGENT_GUARD_API_BASE ?? window.location.origin;
const tokenKey = "prospectmonitor.cli_token";

async function request(path, options = {}) {
  const response = await fetch(`${base}${path}`, { ...options, credentials: "include", headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "请求失败");
  return payload;
}

function saveToken(token) {
  if (token) sessionStorage.setItem(tokenKey, token);
}

let tokenVisible = false;
let toastTimer;

function maskedToken(token) {
  if (!token) return "Token 已生成，请重新登录或重置 Token";
  if (token.length <= 12) return "•".repeat(token.length);
  return `${token.slice(0, 6)}${"•".repeat(Math.min(32, token.length - 10))}${token.slice(-4)}`;
}

function renderToken(token) {
  const tokenNode = document.querySelector("#token");
  const toggle = document.querySelector("#toggleToken");
  tokenNode.textContent = tokenVisible && token ? token : maskedToken(token);
  toggle.disabled = !token;
  toggle.setAttribute("aria-label", tokenVisible ? "隐藏 Token" : "显示 Token");
  toggle.title = tokenVisible ? "隐藏 Token" : "显示 Token";
  toggle.querySelector(".eye-open").hidden = tokenVisible;
  toggle.querySelector(".eye-closed").hidden = !tokenVisible;
}

function showCopyToast() {
  const toast = document.querySelector("#copyToast");
  window.clearTimeout(toastTimer);
  toast.hidden = false;
  requestAnimationFrame(() => toast.classList.add("show"));
  toastTimer = window.setTimeout(() => {
    toast.classList.remove("show");
    window.setTimeout(() => { toast.hidden = true; }, 180);
  }, 2200);
}

async function copyTokenText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch { /* Fall back for HTTP deployments or denied clipboard access. */ }
  }
  const previousFocus = document.activeElement;
  const field = document.createElement("textarea");
  field.value = text;
  field.readOnly = true;
  field.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
  document.body.append(field);
  try {
    field.focus();
    field.select();
    field.setSelectionRange(0, field.value.length);
    return document.execCommand("copy") === true;
  } catch {
    return false;
  } finally {
    field.remove();
    previousFocus?.focus();
  }
}

async function initLogin() {
  const form = document.querySelector("#authForm");
  if (!form) return initAccount();
  let register = false;
  const title = document.querySelector("#title");
  const submit = document.querySelector("#submit");
  const switchMode = document.querySelector("#switchMode");
  const error = document.querySelector("#error");
  switchMode.addEventListener("click", () => {
    register = !register;
    title.textContent = register ? "注册" : "登录";
    submit.textContent = register ? "注册并获取 Token" : "登录";
    switchMode.textContent = register ? "已有账号？登录" : "还没有账号？注册";
    error.textContent = "";
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    submit.disabled = true;
    try {
      const payload = await request(register ? "/api/auth/register" : "/api/auth/login", { method: "POST", body: JSON.stringify({ email: document.querySelector("#email").value, password: document.querySelector("#password").value }) });
      saveToken(payload.token);
      window.location.href = payload.user?.role === "admin" ? "/index.html#admin" : "/index.html";
    } catch (e) { error.textContent = e.message; } finally { submit.disabled = false; }
  });
}

async function initAccount() {
  const embedded = window.parent !== window && new URLSearchParams(window.location.search).get("embedded") === "1";
  document.querySelector("#returnToDemo")?.addEventListener("click", (event) => {
    if (!embedded) return;
    event.preventDefault();
    window.parent.postMessage({ type: "developer-center:close" }, window.location.origin);
  });
  try {
    const me = await request("/api/auth/me");
    document.querySelector("#userLine").textContent = `当前账号：${me.user.email} · ${me.user.role === "admin" ? "开发者 Admin" : "成员"}`;
    const adminLink = document.querySelector("[data-admin-link]");
    if (adminLink) adminLink.hidden = me.user.role !== "admin";
    const token = sessionStorage.getItem(tokenKey);
    renderToken(token);
  } catch { (embedded ? window.parent : window).location.href = "/login.html"; return; }
  document.querySelector("#toggleToken").addEventListener("click", () => {
    tokenVisible = !tokenVisible;
    renderToken(sessionStorage.getItem(tokenKey));
  });
  document.querySelector("#copy").addEventListener("click", async () => {
    const button = document.querySelector("#copy");
    const message = document.querySelector("#message");
    const token = sessionStorage.getItem(tokenKey);
    if (!token) {
      message.textContent = "当前没有可复制的 Token，请重新登录或重置 Token。";
      return;
    }
    button.disabled = true;
    try {
      if (await copyTokenText(token)) {
        message.textContent = "";
        showCopyToast();
      } else {
        const range = document.createRange();
        range.selectNodeContents(document.querySelector("#token"));
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
        message.textContent = "浏览器未允许自动复制，已选中 Token，请按 Ctrl+C / ⌘C，或长按复制。";
      }
    } finally {
      button.disabled = false;
    }
  });
  document.querySelector("#rotate").addEventListener("click", async () => {
    if (!window.confirm("重置后旧 Token 会立即失效，确定继续吗？")) return;
    const payload = await request("/api/auth/token/rotate", { method: "POST" });
    saveToken(payload.token);
    tokenVisible = false;
    renderToken(payload.token);
    document.querySelector("#message").textContent = "新 Token 已生成，旧 Token 已失效。";
  });
  document.querySelector("#logout").addEventListener("click", async () => { await request("/api/auth/logout", { method: "POST" }); sessionStorage.removeItem(tokenKey); (embedded ? window.parent : window).location.href = "/login.html"; });
  await loadUsage();
}

let usagePage = 1;
let usagePages = 1;
let usageLoading = false;

function renderUsagePagination() {
  const pagination = document.querySelector("#usagePagination");
  if (!pagination) return;
  const nodes = [];
  function button(label, page, disabled = false, current = false) {
    const node = document.createElement("button");
    node.type = "button";
    node.textContent = label;
    node.disabled = usageLoading || disabled;
    if (current) node.setAttribute("aria-current", "page");
    node.setAttribute("aria-label", /^\d+$/.test(label) ? `第 ${page} 页` : label);
    node.addEventListener("click", () => loadUsage(page));
    nodes.push(node);
  }
  button("上一页", usagePage - 1, usagePage === 1);
  const visible = new Set([1, usagePages]);
  for (let p = Math.max(1, usagePage - 2); p <= Math.min(usagePages, usagePage + 2); p++) visible.add(p);
  let previous = 0;
  for (const p of [...visible].sort((a, b) => a - b)) {
    if (previous && p - previous > 1) {
      const dots = document.createElement("span");
      dots.textContent = "…";
      nodes.push(dots);
    }
    button(String(p), p, p === usagePage, p === usagePage);
    previous = p;
  }
  button("下一页", usagePage + 1, usagePage === usagePages);
  pagination.replaceChildren(...nodes);
}

async function loadUsage(page = 1) {
  const status = document.querySelector("#usageStatus");
  const rows = document.querySelector("#usageRows");
  if (!status || !rows) return;
  if (usageLoading) return;
  usageLoading = true;
  renderUsagePagination();
  try {
    const payload = await request(`/api/usage?page=${page}&page_size=10`);
    const events = payload.events || [];
    usagePage = payload.page;
    usagePages = payload.pages;
    status.textContent = `共 ${payload.total} 条 · 每页 10 条`;
    rows.innerHTML = events.map((event) => {
      const messages = Array.isArray(event.messages) && event.messages.length
        ? event.messages
        : [{ role: "user", content: event.query || "" }];
      const lastUserMessage = [...messages].reverse().find((item) => item.role === "user");
      const query = event.query || lastUserMessage?.content || messages[messages.length - 1]?.content || "";
      const timestamp = new Date(event.created_at);
      const dateLabel = timestamp.toLocaleDateString([], { month: "2-digit", day: "2-digit" });
      const timeLabel = timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      const requestId = event.request_id || "";
      return `<tr><td class="time">${escapeHtml(dateLabel)} · ${escapeHtml(timeLabel)}</td><td class="query"><details><summary>${escapeHtml(query || "空消息")}</summary></details></td>${riskCell(event.per_risk, ["harmful", "content_safety"])}${riskCell(event.per_risk, ["prompt_leakage", "rag_leak", "sys_leak", "theft"])}${riskCell(event.per_risk, ["ipi", "indirect_prompt_injection"])}<td class="result ${event.action === "block" ? "risk-block" : "risk-pass"}"><span>${event.action === "block" ? "已拦截" : event.action === "pass" ? "已放行" : escapeHtml(event.action || "—")}</span></td><td>${escapeHtml(String(event.usage?.input_tokens ?? "—"))}</td><td><span class="request-id" title="${escapeHtml(requestId)}">${escapeHtml(shortRequestId(requestId))}</span></td></tr>`;
    }).join("");
    if (!events.length) rows.innerHTML = '<tr><td colspan="8">暂无调用记录</td></tr>';
  } catch (error) { status.textContent = error.message || "日志加载失败。"; }
  finally { usageLoading = false; renderUsagePagination(); }
}

function riskCell(perRisk, keys) {
  const values = keys.map((key) => perRisk?.[key]).filter(Boolean);
  if (!values.length) return `<td class="risk-cell"><span class="risk-state">未检测</span></td>`;
  const flagged = values.some((value) => value.flagged);
  const scores = values.map((value) => Number(value.score)).filter(Number.isFinite);
  const score = scores.length ? Math.max(...scores) : null;
  const scoreLabel = score == null ? "" : `<small>${escapeHtml(formatRiskScore(score))}</small>`;
  const threshold = values.find((value) => Number.isFinite(Number(value.threshold)))?.threshold;
  const title = score == null ? "" : `风险分数 ${formatRiskScore(score)}${threshold == null ? "" : `，阈值 ${formatRiskScore(Number(threshold))}`}`;
  return `<td class="risk-cell"><span class="risk-state ${flagged ? "flagged" : "passed"}" title="${escapeHtml(title)}">${flagged ? "风险" : "通过"}${scoreLabel}</span></td>`;
}

function formatRiskScore(score) {
  return score >= 0 && score <= 1 ? `${(score * 100).toFixed(1)}%` : String(Math.round(score * 100) / 100);
}

function shortRequestId(value) {
  if (!value) return "—";
  return value.length > 15 ? `${value.slice(0, 7)}…${value.slice(-5)}` : value;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
}

initLogin();
