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
    title.textContent = register ? "注册 ProspectMonitor" : "登录 ProspectMonitor";
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
      window.location.href = "/account.html";
    } catch (e) { error.textContent = e.message; } finally { submit.disabled = false; }
  });
}

async function initAccount() {
  try {
    const me = await request("/api/auth/me");
    document.querySelector("#userLine").textContent = `当前账号：${me.user.email} · ${me.user.role === "admin" ? "开发者 Admin" : "成员"}`;
    const token = sessionStorage.getItem(tokenKey);
    document.querySelector("#token").textContent = token || "Token 已生成，请重新登录或重置 Token";
  } catch { window.location.href = "/login.html"; return; }
  document.querySelector("#copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText(document.querySelector("#token").textContent);
    document.querySelector("#message").textContent = "Token 已复制。";
  });
  document.querySelector("#rotate").addEventListener("click", async () => {
    if (!window.confirm("重置后旧 Token 会立即失效，确定继续吗？")) return;
    const payload = await request("/api/auth/token/rotate", { method: "POST" });
    saveToken(payload.token);
    document.querySelector("#token").textContent = payload.token;
    document.querySelector("#message").textContent = "新 Token 已生成，旧 Token 已失效。";
  });
  document.querySelector("#logout").addEventListener("click", async () => { await request("/api/auth/logout", { method: "POST" }); sessionStorage.removeItem(tokenKey); window.location.href = "/login.html"; });
}

initLogin();
