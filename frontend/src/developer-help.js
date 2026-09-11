async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch { /* Use the selection fallback below. */ }
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.readOnly = true;
  field.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
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
  }
}

const adminLink = document.querySelector("[data-admin-link]");
if (adminLink) {
  fetch("/api/auth/me", { credentials: "include" })
    .then((response) => response.ok ? response.json() : null)
    .then((payload) => { adminLink.hidden = payload?.user?.role !== "admin"; })
    .catch(() => { adminLink.hidden = true; });
}

document.querySelectorAll("[data-copy-code]").forEach((button) => {
  button.addEventListener("click", async () => {
    const source = document.getElementById(button.dataset.copyCode);
    const feedback = document.querySelector("#copyFeedback");
    button.disabled = true;
    const copied = source ? await copyText(source.textContent) : false;
    button.disabled = false;
    button.textContent = copied ? "已复制" : "复制失败";
    feedback.textContent = copied ? "示例代码已复制到剪贴板。" : "浏览器未允许自动复制，请手动选择代码。";
    window.setTimeout(() => { button.textContent = "复制代码"; }, 1800);
  });
});

const tocLinks = [...document.querySelectorAll(".help-toc a[href^='#']")];

function selectTocLink(selected) {
  for (const link of tocLinks) {
    link.classList.toggle("active", link === selected);
    if (link === selected) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}

for (const link of tocLinks) {
  link.addEventListener("click", (event) => {
    const id = decodeURIComponent(link.hash.slice(1));
    const section = document.getElementById(id);
    if (!section) return;
    event.preventDefault();
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(window.history.state, "", link.hash);
    selectTocLink(link);
  });
}

if (window.location.hash) {
  const activeLink = tocLinks.find((link) => link.hash === window.location.hash);
  if (activeLink) selectTocLink(activeLink);
}
