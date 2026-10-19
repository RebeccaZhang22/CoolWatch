const form = document.querySelector("#loginForm");
form.addEventListener("submit", async event => {
  event.preventDefault();
  const button = document.querySelector("#loginButton");
  const error = document.querySelector("#loginError");
  button.disabled = true; error.textContent = "";
  try {
    const response = await fetch("/api/manager/login", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: document.querySelector("#email").value, password: document.querySelector("#password").value }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "登录失败，请检查账号和密码。");
    location.replace("/manager/");
  } catch (failure) { error.textContent = failure.message || "连接失败，请稍后重试。"; }
  finally { button.disabled = false; }
});
