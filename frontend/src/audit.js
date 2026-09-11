const DATA_URL = "./assets/audit/evaluation_summary.json";

const percent = (value, digits = 2) => `${(Number(value) * 100).toFixed(digits)}%`;
const integer = (value) => Number(value).toLocaleString("zh-CN");

function metricCard(label, value, note, tone = "green") {
  return `<article class="metric-card ${tone}"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`;
}

function renderLeakage(data) {
  document.querySelector("#leakageHeadline").innerHTML = [
    metricCard("系统提示词 AUROC", data.system_prompt.auroc.toFixed(4), "整体区分能力"),
    metricCard("RAG 泄漏 AUROC", data.rag.auroc.toFixed(4), "整体区分能力"),
    metricCard("合计评测样本", integer(data.system_prompt.n + data.rag.n), "两类数据分别评估", "blue"),
  ].join("");
  document.querySelector("#leakageTable").innerHTML = [data.system_prompt, data.rag].map((item) => `
    <tr><th scope="row"><span class="dataset-name">${item.label}</span><small>${item.description}</small></th>
    <td>${integer(item.n)}</td><td class="strong-value">${item.auroc.toFixed(4)}</td><td>${percent(item.recall)}</td><td>${percent(item.fpr)}</td><td>${percent(item.f1)}</td></tr>`).join("");
}

function renderIpi(data) {
  document.querySelector("#ipiHeadline").innerHTML = [
    metricCard("总体 AUROC", data.overall.auroc.toFixed(4), `${integer(data.overall.n)} 条留出样本`),
    metricCard("总体准确率", percent(data.overall.accuracy), "固定 0.5 判定阈值"),
    metricCard("评测数据集", String(data.datasets.length), "AgentDyn + InjecAgent", "blue"),
  ].join("");
  document.querySelector("#ipiDatasets").innerHTML = data.datasets.map((item) => `
    <div class="dataset-result"><div class="dataset-result-title"><div><strong>${item.label}</strong><span>${integer(item.n)} 条 · ${integer(item.positive)} 条攻击</span></div><b>${item.auroc.toFixed(4)}</b></div>
    <div class="score-track" aria-label="${item.label} AUROC ${item.auroc.toFixed(4)}"><span style="width:${Math.min(item.auroc * 100, 100)}%"></span></div>
    <div class="dataset-result-foot"><span>AUROC</span><span>准确率 ${percent(item.accuracy)}</span></div></div>`).join("");
}

function renderContentSafety(data) {
  document.querySelector("#contentSafetyHeadline").innerHTML = [
    metricCard("AUROC", data.auroc.toFixed(3), "Mock 数据", "muted"),
    metricCard("召回率", percent(data.recall, 1), "Mock 数据", "muted"),
    metricCard("误报率", percent(data.fpr, 1), "Mock 数据", "muted"),
  ].join("");
  document.querySelector("#contentSafetyCategories").innerHTML = data.categories.map((category) => `<span><i aria-hidden="true"></i>${category}<small>待评测</small></span>`).join("");
}

function setupSectionNavigation() {
  const links = [...document.querySelectorAll(".audit-section-nav a")];
  const sections = [...document.querySelectorAll("[data-audit-section]")];
  if (!("IntersectionObserver" in window)) return;
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    links.forEach((link) => link.classList.toggle("active", link.hash === `#${visible.target.id}`));
  }, { rootMargin: "-22% 0px -60%", threshold: [0.05, 0.3, 0.6] });
  sections.forEach((section) => observer.observe(section));
}

async function init() {
  setupSectionNavigation();
  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderLeakage(data.prompt_leakage);
    renderIpi(data.indirect_prompt_injection);
    renderContentSafety(data.content_safety_mock);
    document.querySelector("#auditUpdatedAt").textContent = `数据更新于 ${data.updated_at}`;
  } catch (error) {
    console.error("Failed to load audit data", error);
    document.querySelector("#auditLoadError").hidden = false;
  }
}

init();
