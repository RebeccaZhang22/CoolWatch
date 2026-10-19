// UI hints are best effort. The server independently records requests and risk outcomes.
let context = () => sessionStorage.getItem("coolwatch.demo.session") || "";
let queue = [];
let timer;
let sending = false;
const enabled = !window.AGENT_GUARD_USE_MOCK
  && new URLSearchParams(location.search).get("demo") !== "1"
  && !location.pathname.startsWith("/manager")
  && !location.pathname.endsWith("login.html");

export function setTelemetryContext(provider) {
  context = provider;
  try { sessionStorage.setItem("coolwatch.demo.session", String(context() || "")); } catch { /* Storage may be disabled. */ }
}

export function telemetryHeaders() {
  try { return { "X-Demo-Session": String(context() || "").slice(0, 128) }; }
  catch { return {}; }
}

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function track(name, target = "", label = "", value = null) {
  if (!enabled) return;
  try {
    const session = String(context() || "").slice(0, 128);
    if (session) sessionStorage.setItem("coolwatch.demo.session", session);
    queue.push({ id: uuid(), name, path: location.pathname, session_id: session,
      target: target.slice(0, 160), label: label.slice(0, 160), value });
    queue = queue.slice(-120);
    clearTimeout(timer);
    timer = setTimeout(flush, 700);
  } catch { /* Analytics must never interrupt a demo. */ }
}

async function flush() {
  if (!queue.length || sending) return;
  const batch = queue.splice(0, 30);
  sending = true;
  try {
    const response = await fetch("/api/telemetry/events", { method: "POST", credentials: "same-origin", keepalive: true,
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ events: batch }) });
    if (response.status >= 500 || response.status === 429) queue = [...batch, ...queue].slice(-120);
    if (response.status === 401) queue = [];
  } catch { queue = [...batch, ...queue].slice(-120); }
  finally {
    sending = false;
    if (queue.length) timer = setTimeout(flush, 3000);
  }
}

function identify(node) {
  const data = ["track", "defenseId", "attackId", "scenarioId", "replayCase", "documentId", "fileId"]
    .find(key => node.dataset[key]);
  const target = node.id || (data ? `${data}:${node.dataset[data]}` : node.name || node.classList[0] || node.tagName.toLowerCase());
  const label = node.getAttribute("aria-label") || node.getAttribute("title")
    || (node.matches("input, select, textarea") ? node.name || target : node.textContent.trim().replace(/\s+/g, " "));
  return [target, label];
}

if (enabled) {
  document.addEventListener("click", event => {
    const node = event.target.closest?.("button, a[href], summary, [role=button]");
    if (!node || node.disabled) return;
    track("click", ...identify(node));
  }, true);
  document.addEventListener("change", event => {
    const node = event.target;
    // Never collect passwords, tokens, textarea contents, or freeform input drafts.
    if (!node.matches("select, input[type=checkbox], input[type=radio], input[type=range], input[type=number]")) return;
    const value = node.matches("[type=checkbox], [type=radio]") ? String(node.checked) : String(node.value).slice(0, 160);
    track("change", ...identify(node), value);
  }, true);
  setTimeout(() => track("page_view", "page", document.title), 0);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flush(); });
  window.addEventListener("pagehide", flush);
}
