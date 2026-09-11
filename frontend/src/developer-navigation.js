// Keep the demo document, active stream and in-memory conversation mounted.
const trigger = document.querySelector("#openDeveloperCenter");
const dialog = document.querySelector("#developerCenterDialog");
const frame = document.querySelector("#developerCenterFrame");
const closeButton = document.querySelector("#closeDeveloperCenter");
const title = document.querySelector("#developerCenterTitle");
const shell = document.querySelector(".demo-page-shell");
const workspace = document.querySelector("#appShell");
const navigation = document.querySelector(".audit-nav");
shell.append(dialog);
const developerPaths = new Set(["account.html", "developer-docs.html", "developer-examples.html", "admin.html"]);
const views = {
  "account.html": { hash: "developer-center", title: "开发者中心", search: "?embedded=1" },
  "developer-docs.html": { hash: "developer-docs", title: "开发者中心" },
  "developer-examples.html": { hash: "developer-examples", title: "开发者中心" },
  "admin.html": { hash: "admin", title: "管理后台" },
  "audit.html": { hash: "audit", title: "实验审计" },
  "cases.html": { hash: "cases", title: "案例研究" },
  "competitors.html": { hash: "competitors", title: "竞品分析" },
  "indirect-replay.html": { hash: "indirect-replay", title: "案例研究" },
  "case-study.html": { hash: "financial-case", title: "案例研究" },
};
let currentView = "";
const boundDocuments = new WeakSet();

function syncDeveloperView() {
  const [hash, ...query] = window.location.hash.slice(1).split("?");
  const entry = Object.entries(views).find(([, view]) => view.hash === hash);
  const isSection = Boolean(entry && !developerPaths.has(entry[0]));
  shell.classList.toggle("section-view", isSection);
  workspace.inert = isSection;
  const activePath = isSection ? (["indirect-replay.html", "case-study.html"].includes(entry[0]) ? "cases.html" : entry[0]) : "index.html";
  for (const link of navigation.querySelectorAll("a")) {
    const active = new URL(link.href).pathname.endsWith(`/${activePath}`);
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (entry) {
    const [path, view] = entry;
    const search = view.search || (query.length ? `?${query.join("?")}` : "");
    const target = new URL(`./${path}${search}`, window.location.href).href;
    if (currentView !== target) {
      currentView = target;
      // Replace the frame's entry: only the outer page owns navigation history.
      frame.contentWindow.location.replace(target);
    }
    title.textContent = view.title;
    dialog.setAttribute("aria-label", view.title);
    frame.title = view.title;
    const mode = isSection ? "section" : "account";
    if (dialog.dataset.mode !== mode && dialog.open) dialog.close();
    dialog.dataset.mode = mode;
    if (!dialog.open) {
      if (isSection) dialog.show();
      else dialog.showModal();
    }
  } else if (dialog.open) {
    dialog.close();
    trigger.focus();
    currentView = "";
  }
}

function closeDeveloperView() {
  const url = new URL(window.location.href);
  url.hash = "";
  window.history.pushState(window.history.state, "", url);
  syncDeveloperView();
}

function handleNavigation(event) {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
  const link = event.target.closest?.("a[href]");
  if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) return;
  const url = new URL(link.href);
  if (url.origin !== window.location.origin) return;
  // Keep in-page documentation anchors inside the iframe so the table of
  // contents scrolls normally instead of becoming outer navigation history.
  if (url.hash && currentView === `${url.origin}${url.pathname}${url.search}`) return;
  const base = new URL("./", window.location.href);
  const path = url.pathname.slice(base.pathname.length);
  if (!url.pathname.startsWith(base.pathname)) return;
  const isDemo = path === "" || path === "index.html";
  const view = views[path];
  if (!view && !isDemo) return;
  // Leave parameterized demo links to their existing workflows.
  if (isDemo && (url.search || url.hash)) return;
  event.preventDefault();
  if (isDemo) {
    if (dialog.open) closeDeveloperView();
    return;
  }
  const hash = `#${view.hash}${view.search ? "" : url.search}`;
  if (window.location.hash !== hash) {
    window.history.pushState(window.history.state, "", hash);
  }
  syncDeveloperView();
}

document.addEventListener("click", handleNavigation);
frame.addEventListener("load", () => {
  const frameDocument = frame.contentDocument;
  if (!frameDocument || boundDocuments.has(frameDocument)) return;
  boundDocuments.add(frameDocument);
  frameDocument.addEventListener("click", handleNavigation);
});
closeButton.addEventListener("click", closeDeveloperView);
dialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeDeveloperView();
});
window.addEventListener("popstate", syncDeveloperView);
window.addEventListener("hashchange", syncDeveloperView);
window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin || event.source !== frame.contentWindow) return;
  if (event.data?.type === "developer-center:close") closeDeveloperView();
});
syncDeveloperView();
