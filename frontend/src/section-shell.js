// Direct section links enter the same persistent shell as the main navigation.
(() => {
  const routes = {
    "audit.html": "audit",
    "cases.html": "cases",
    "competitors.html": "competitors",
    "indirect-replay.html": "indirect-replay",
    "case-study.html": "financial-case",
  };
  if (window.top === window) {
    const route = routes[window.location.pathname.split("/").pop()];
    const target = new URL("./index.html", window.location.href);
    target.hash = `${route}${window.location.search}`;
    window.location.replace(target);
  } else {
    // Suppress the child navigation before first paint; the shell owns it.
    const style = document.createElement("style");
    style.textContent = ".audit-topbar { display: none !important; }";
    document.head.append(style);
  }
})();
