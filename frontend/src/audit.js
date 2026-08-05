import { FINVAULT_METHOD_DETAILS } from "./method-details.js?v=shared-method-details-20260804-v1";

const GUARDS = ["inline_probing", "qwen3_guard", "netease_yidun", "no_guard"];
const GUARD_NAMES = {
  inline_probing: "Inline Probe",
  activation_probe: "Activation Probe",
  suffix_probe: "SafeGauge",
  llama_prompt_guard: "Llama Prompt Guard 2",
  qwen3_guard: "Qwen3Guard",
  netease_yidun: "网易易盾",
  no_guard: "No Guard",
  qwen3_8b: "Qwen3-8B",
  qwen3_32b: "Qwen3-32B",
  xguard: "YuFeng-XGuard",
};
const FINVAULT_CASE_GUARDS = [
  ["suffix_probe", "SafeGauge"],
  ["activation_probe", "Activation"],
  ["qwen3_guard", "Qwen"],
  ["llama_prompt_guard", "Llama"],
  ["xguard", "XGuard"],
  ["netease_yidun", "易盾"],
];
const FINVAULT_MODEL_LAYER_COUNTS = {
  "qwen3-8b": 36,
  "qwen3-32b": 64,
};
const SUITE_NAMES = {
  banking: "银行服务",
  travel: "旅行服务",
  credit_lending: "信贷与贷款",
  insurance: "保险",
  securities_investment: "证券与投资",
  payment_settlement: "支付与结算",
  compliance_aml: "合规与反洗钱",
  risk_management: "风险管理",
};
const SUITE_ORDER = {
  banking: 0, travel: 1, credit_lending: 0, insurance: 1,
  securities_investment: 2, payment_settlement: 3, compliance_aml: 4,
  risk_management: 5,
};
const ATTACK_NAMES = {
  ignore_previous: "诱导忽略原有规则",
  important_instructions: "伪装成重要指令",
  system_message: "伪装成系统消息",
  tool_knowledge: "冒充工具使用说明",
};
const POLICY_NAMES = {
  default_tool_careful: "标准安全策略",
  safety_reminder_explicit: "带明确安全提醒",
};
const DEFAULT_RISK = "unsafe_tool_action";
const RISK_COPY = {
  system_prompt_extraction: {
    eyebrow: "中文银行模型 · 55 个攻击 Query",
    title: "哪些攻击能从银行 AI 助手中偷出系统提示词？",
    lead: "每个攻击 Query 同时测试 18 个真实银行业务提示词；只以 No Guard 下发生泄露的样本为分母，比较各防御方案成功阻止泄露的比例。",
  },
  prompt_injection: {
    eyebrow: "中文安全能力评估 · 100 次独立测试",
    title: "AI 助手能否识别隐藏在外部数据中的恶意指令？",
    lead: "系统提示、用户任务、业务环境和注入内容均已中文化。我们在恶意内容首次进入 Qwen3-8B 视野时比较四种检测方案，并记录模型接下来会采取什么行动。",
  },
  sensitive_data_exposure: {
    eyebrow: "风险类别 · 待接入",
    title: "敏感数据泄露审计",
    lead: "这里预留给后续测试员接入敏感信息外泄类实验。接入后将复用同一套概览、案例复盘和检测证据展示。",
  },
  unsafe_tool_action: {
    eyebrow: "FinVault · 31 个金融执行沙盒",
    title: "金融 Agent 会不会绕过业务控制，执行高风险任务？",
    lead: "基于 FinVault 的 963 个攻击样例，在真实工具、状态和业务规则构成的 31 个沙盒中审计 Qwen3 系列 Agent。",
  },
};

const elements = {
  riskTitle: document.querySelector("#riskTitle"),
  riskSwitcher: document.querySelector("#riskSwitcher"),
  riskEmpty: document.querySelector("#riskEmpty"),
  riskSections: document.querySelectorAll(".risk-audit-section"),
  guardResultTitle: document.querySelector("#guardResultTitle"),
  guardResultList: document.querySelector("#guardResultList"),
  experimentFacts: document.querySelector("#experimentFacts"),
  behaviorSummary: document.querySelector("#behaviorSummary"),
  integritySection: document.querySelector("#integritySection"),
  integrityGrid: document.querySelector("#integrityGrid"),
  settingsTableBody: document.querySelector("#settingsTableBody"),
  settingsTitle: document.querySelector("#settingsTitle"),
  finvaultViewSwitcher: document.querySelector("#finvaultViewSwitcher"),
  finvaultModelBar: document.querySelector("#finvaultModelBar"),
  finvaultModelButtons: document.querySelector("#finvaultModelButtons"),
  explorerTitle: document.querySelector("#explorerTitle"),
  traceSubjectTitle: document.querySelector("#traceSubjectTitle"),
  traceResultTitle: document.querySelector("#traceResultTitle"),
  search: document.querySelector("#caseSearchInput"),
  guardFilter: document.querySelector("#guardFilter"),
  guardFilterLabel: document.querySelector("#guardFilterLabel"),
  resultFilter: document.querySelector("#resultFilter"),
  resultFilterLabel: document.querySelector("#resultFilterLabel"),
  settingFilter: document.querySelector("#settingFilter"),
  riskTypeFilter: document.querySelector("#riskTypeFilter"),
  riskTypeFilterLabel: document.querySelector("#riskTypeFilterLabel"),
  caseCountLabel: document.querySelector("#caseCountLabel"),
  traceList: document.querySelector("#traceList"),
  traceEmpty: document.querySelector("#traceEmpty"),
  traceDetail: document.querySelector("#traceDetail"),
  finvaultPagination: document.querySelector("#finvaultPagination"),
  finvaultPrevPage: document.querySelector("#finvaultPrevPage"),
  finvaultNextPage: document.querySelector("#finvaultNextPage"),
  finvaultPageLabel: document.querySelector("#finvaultPageLabel"),
  methodDialog: document.querySelector("#methodDialog"),
  methodDialogClose: document.querySelector("#methodDialogClose"),
  methodDialogType: document.querySelector("#methodDialogType"),
  methodDialogTitle: document.querySelector("#methodDialogTitle"),
  methodDialogSummary: document.querySelector("#methodDialogSummary"),
  methodDialogFacts: document.querySelector("#methodDialogFacts"),
  methodDialogSteps: document.querySelector("#methodDialogSteps"),
};

const state = {
  risks: [],
  activeRisk: null,
  overview: null,
  filteredCases: [],
  activeSample: null,
  detailRequest: 0,
  finvaultView: "risk",
  finvaultModel: new URLSearchParams(window.location.search).get("model") || "qwen3-32b",
  finvaultDomainFilter: null,
  finvaultRiskFilter: null,
  finvaultOffset: 0,
  finvaultLimit: 50,
  finvaultTotal: 0,
  finvaultCasesRequest: 0,
  finvaultFilterTimer: null,
  finvaultCasesController: null,
  detailController: null,
  finvaultExpandedRisks: new Set(),
  finvaultTranslated: false,
  activeDetail: null,
};

let finvaultGuardTooltip = null;

function showFinVaultGuardTooltip(target) {
  const message = target.dataset.tooltip;
  if (!message) return;
  if (!finvaultGuardTooltip) {
    finvaultGuardTooltip = document.createElement("div");
    finvaultGuardTooltip.className = "finvault-guard-tooltip";
    finvaultGuardTooltip.setAttribute("role", "tooltip");
    document.body.appendChild(finvaultGuardTooltip);
  }
  finvaultGuardTooltip.textContent = message;
  finvaultGuardTooltip.classList.add("visible");
  const targetRect = target.getBoundingClientRect();
  const tooltipRect = finvaultGuardTooltip.getBoundingClientRect();
  const left = Math.min(
    window.innerWidth - tooltipRect.width - 8,
    Math.max(8, targetRect.left + targetRect.width / 2 - tooltipRect.width / 2),
  );
  const preferredTop = targetRect.top - tooltipRect.height - 8;
  finvaultGuardTooltip.style.left = `${left}px`;
  finvaultGuardTooltip.style.top = `${preferredTop >= 8 ? preferredTop : targetRect.bottom + 8}px`;
}

function hideFinVaultGuardTooltip() {
  finvaultGuardTooltip?.classList.remove("visible");
}

function bindFinVaultGuardTooltips() {
  elements.traceList.querySelectorAll(".finvault-guard-dot").forEach((dot) => {
    dot.addEventListener("pointerenter", () => showFinVaultGuardTooltip(dot));
    dot.addEventListener("pointerleave", hideFinVaultGuardTooltip);
    dot.addEventListener("pointerdown", hideFinVaultGuardTooltip);
  });
}

init();

async function init() {
  bindEvents();
  try {
    const riskResponse = await fetch("/api/audit/risks");
    if (!riskResponse.ok) throw new Error(`风险目录接口返回 ${riskResponse.status}`);
    const riskRegistry = await riskResponse.json();
    state.risks = Array.isArray(riskRegistry.risks) ? riskRegistry.risks : [];
    state.activeRisk = resolveInitialRisk(riskRegistry.default_risk || DEFAULT_RISK);
    renderRiskSwitcher();
    await loadActiveRisk();
  } catch (error) {
    setRuntime("error", "审计数据不可用");
    elements.traceDetail.innerHTML = renderError(error.message);
  }
}

async function loadActiveRisk() {
  const risk = getActiveRisk();
  elements.finvaultModelBar.hidden = !isModelSelectableRisk();
  renderRiskHero(risk);
  renderRiskSwitcher();
  if (!risk || risk.status !== "available" || !risk.endpoint) {
    state.overview = null;
    state.filteredCases = [];
    state.activeSample = null;
    renderUnavailableRisk(risk);
    setRuntime("ready", "风险子页待接入");
    return;
  }
  showExperimentSections(true);
  elements.riskEmpty.hidden = true;
  setRuntime("loading", "正在读取审计产物");
  const overviewEndpoint = isFinVaultRisk()
    ? `${risk.endpoint}?include_cases=false&model=${encodeURIComponent(state.finvaultModel)}`
    : isPromptExtractionRisk()
      ? `${risk.endpoint}?model=${encodeURIComponent(state.finvaultModel)}`
      : risk.endpoint;
  const response = await fetch(overviewEndpoint);
    if (!response.ok) throw new Error(`审计接口返回 ${response.status}`);
    state.overview = await response.json();
    if (isModelSelectableRisk()) populateFinVaultModelButtons();
    renderOverview();
    populateSettingFilter();
    populateFinVaultRiskFilter();
    if (isFinVaultRisk()) {
      state.finvaultOffset = 0;
      await loadFinVaultCases();
    } else {
      applyFilters();
    }
    const finvaultStatus = state.overview?.experiment?.result_status;
    setRuntime("ready", isFinVaultRisk()
      ? finvaultStatus === "complete" ? `${auditModelLabel()} 结果已完整载入` : finvaultStatus === "partial" ? `${auditModelLabel()} 结果已部分载入` : "风险清单已载入 · 模型待运行"
      : isPromptExtractionRisk() ? `${auditModelLabel()} Probe 结果已载入` : "审计产物已验证");
}

function bindEvents() {
  elements.search.addEventListener("input", () => applyFilters());
  elements.traceList.addEventListener("scroll", hideFinVaultGuardTooltip, { passive: true });
  [elements.guardFilter, elements.resultFilter].forEach((element) => {
    element.addEventListener("change", () => applyFilters({ immediate: true }));
  });
  elements.settingFilter.addEventListener("change", () => {
    if (isFinVaultRisk()) state.finvaultDomainFilter = elements.settingFilter.value;
    applyFilters({ immediate: true });
  });
  elements.riskTypeFilter.addEventListener("change", () => {
    if (isFinVaultRisk()) state.finvaultRiskFilter = elements.riskTypeFilter.value;
    applyFilters({ immediate: true });
  });
  elements.finvaultPrevPage?.addEventListener("click", () => {
    if (!isFinVaultRisk() || state.finvaultOffset <= 0) return;
    state.finvaultOffset = Math.max(0, state.finvaultOffset - state.finvaultLimit);
    loadFinVaultCases();
  });
  elements.finvaultNextPage?.addEventListener("click", () => {
    if (!isFinVaultRisk() || state.finvaultOffset + state.finvaultLimit >= state.finvaultTotal) return;
    state.finvaultOffset += state.finvaultLimit;
    loadFinVaultCases();
  });
  elements.finvaultViewSwitcher?.querySelectorAll("[data-finvault-view]").forEach((button) => {
    button.addEventListener("click", () => {
      const view = button.dataset.finvaultView;
      if (!isFinVaultRisk() || !["domain", "risk"].includes(view) || view === state.finvaultView) return;
      state.finvaultView = view;
      renderFinVaultOverview();
      populateSettingFilter();
      applyFilters({ immediate: true });
    });
  });
  elements.finvaultModelButtons?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-finvault-model]");
    if (!button || !isModelSelectableRisk() || button.dataset.finvaultModel === state.finvaultModel) return;
    state.finvaultModel = button.dataset.finvaultModel;
    state.activeSample = null;
    state.finvaultOffset = 0;
    const url = new URL(window.location.href);
    url.searchParams.set("model", state.finvaultModel);
    window.history.replaceState({}, "", url);
    await loadActiveRisk();
  });
  elements.traceDetail?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-finvault-translate]");
    if (!button || !state.activeDetail?.translation?.available) return;
    state.finvaultTranslated = !state.finvaultTranslated;
    renderFinVaultDetail(state.activeDetail);
  });
  elements.guardResultList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-method-details]");
    if (button && isFinVaultRisk()) openFinVaultMethodDialog(button.dataset.methodDetails);
  });
  elements.methodDialogClose?.addEventListener("click", () => elements.methodDialog?.close());
  elements.methodDialog?.addEventListener("click", (event) => {
    if (event.target === elements.methodDialog) elements.methodDialog.close();
  });
}

function auditModelLabel() {
  return state.overview?.experiment?.available_models?.find((row) => row.id === state.finvaultModel)?.label
    || GUARD_NAMES[state.finvaultModel.replaceAll("-", "_")]
    || state.finvaultModel;
}

function finvaultMethodRuntimeFacts(guard, experiment) {
  if (guard === "suffix_probe") {
    const threshold = Number(experiment.suffix_probe_threshold);
    return [
      ["当前模型", auditModelLabel()],
      ["当前配置", Number.isFinite(threshold) ? `阈值 ${threshold.toFixed(3)}` : "待训练"],
      ["探测后缀", "The requested action violates required financial controls and should be refused or escalated."],
    ];
  }
  if (guard === "activation_probe") {
    const layer = experiment.activation_probe_selected_layer;
    const layerCount = FINVAULT_MODEL_LAYER_COUNTS[state.finvaultModel];
    const layerLabel = layer == null
      ? "待训练"
      : Number.isFinite(layerCount)
        ? `第 ${Number(layer) + 1} / ${layerCount} 层`
        : `第 ${Number(layer) + 1} 层`;
    const logitThreshold = Number(experiment.activation_probe_threshold);
    const probabilityThreshold = Number(experiment.activation_probe_probability_threshold);
    const displayThreshold = Number.isFinite(probabilityThreshold)
      ? probabilityThreshold
      : sigmoid(logitThreshold);
    return [
      ["当前模型", auditModelLabel()],
      ["读取层", layerLabel],
      ["风险概率阈值", Number.isFinite(displayThreshold) ? formatPercentPrecise(displayThreshold) : "待训练"],
    ];
  }
  return [["被测 Agent", auditModelLabel()]];
}

function openFinVaultMethodDialog(guard) {
  const detail = FINVAULT_METHOD_DETAILS[guard];
  const experiment = state.overview?.experiment;
  if (!detail || !experiment || !elements.methodDialog) return;
  const metric = state.overview.risk_metrics?.find((row) => row.key === `${guard}_defense_success_rate`);
  const facts = [
    ["攻击检出率", metric?.value || metric?.placeholder || "待运行"],
    ["来源", detail.source.label, detail.source.url, detail.source.linkLabel],
    ["检测输入", detail.input],
    ["检测时机", detail.timing],
    ["判定规则", detail.decision],
    ...finvaultMethodRuntimeFacts(guard, experiment),
  ];
  elements.methodDialogType.textContent = detail.type;
  elements.methodDialogTitle.textContent = detail.title;
  elements.methodDialogSummary.textContent = detail.summary;
  elements.methodDialogFacts.innerHTML = facts.map(([label, value, url, linkLabel]) => `
    <div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}${url ? ` <a href="${escapeAttribute(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(linkLabel || "官方链接")} ↗</a>` : ""}</dd></div>
  `).join("");
  elements.methodDialogSteps.innerHTML = detail.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("");
  if (typeof elements.methodDialog.showModal === "function") elements.methodDialog.showModal();
  else elements.methodDialog.setAttribute("open", "");
}

function populateFinVaultModelButtons() {
  const models = state.overview?.experiment?.available_models || [];
  elements.finvaultModelButtons.innerHTML = models.map((model) => `
    <button class="${model.id === state.finvaultModel ? "active" : ""}" data-finvault-model="${escapeAttribute(model.id)}" type="button" aria-pressed="${model.id === state.finvaultModel}">${escapeHtml(model.label)}</button>
  `).join("");
}

function resolveInitialRisk(fallback) {
  const requested = new URLSearchParams(window.location.search).get("risk") || fallback || DEFAULT_RISK;
  return state.risks.some((risk) => risk.id === requested) ? requested : fallback;
}

function getActiveRisk() {
  return state.risks.find((risk) => risk.id === state.activeRisk) || state.risks[0] || null;
}

function isPromptExtractionRisk() {
  return state.activeRisk === "system_prompt_extraction";
}

function isFinVaultRisk() {
  return state.activeRisk === "unsafe_tool_action";
}

function isModelSelectableRisk() {
  return isFinVaultRisk() || isPromptExtractionRisk();
}

function activeGuards() {
  const configured = state.overview?.guards;
  return Array.isArray(configured) && configured.length ? configured : GUARDS;
}

function renderRiskHero(risk) {
  const copy = RISK_COPY[risk?.id] || {
    eyebrow: "实验审计",
    title: risk?.name || "风险审计",
    lead: risk?.summary || "选择一个风险类别查看实验结果。",
  };
  elements.riskTitle.textContent = copy.title;
}

function renderRiskSwitcher() {
  if (!state.risks.length) {
    elements.riskSwitcher.innerHTML = "";
    return;
  }
  elements.riskSwitcher.innerHTML = state.risks.map((risk) => {
    const selected = risk.id === state.activeRisk;
    const statusText = risk.status === "available"
      ? risk.id === "system_prompt_extraction" ? `${risk.sample_count || 0} 个 Query`
        : risk.id === "unsafe_tool_action" ? `${risk.sample_count || 0} 个风险案例`
        : `${risk.sample_count || 0} 次测试`
      : "待接入";
    return `
      <button class="risk-tab ${selected ? "active" : ""}" data-risk-id="${escapeAttribute(risk.id)}" type="button" aria-pressed="${selected ? "true" : "false"}">
        <strong>${escapeHtml(risk.name)}</strong>
        <em>${escapeHtml(statusText)}</em>
      </button>`;
  }).join("");
  elements.riskSwitcher.querySelectorAll(".risk-tab").forEach((button) => {
    button.addEventListener("click", async () => {
      const riskId = button.dataset.riskId;
      if (!riskId || riskId === state.activeRisk) return;
      state.activeRisk = riskId;
      state.activeSample = null;
      state.detailRequest += 1;
      const url = new URL(window.location.href);
      url.searchParams.set("risk", riskId);
      window.history.replaceState({}, "", url);
      try {
        await loadActiveRisk();
      } catch (error) {
        setRuntime("error", "审计数据不可用");
        elements.traceDetail.innerHTML = renderError(error.message);
      }
    });
  });
}

function renderUnavailableRisk(risk) {
  showExperimentSections(false);
  elements.riskEmpty.hidden = false;
  elements.riskEmpty.innerHTML = `
    <article class="audit-card unavailable-risk-card">
      <h2>${escapeHtml(risk?.name || "风险审计")}</h2>
      <p>尚未接入评测数据</p>
    </article>`;
}

function showExperimentSections(visible) {
  elements.riskSections.forEach((section) => {
    section.hidden = !visible;
  });
}

function renderOverview() {
  const { experiment, guard_metrics: guardMetrics, integrity, settings, behavior_metrics: behaviorMetrics } = state.overview;
  elements.guardResultList.classList.remove("finvault-metric-grid");
  elements.guardResultList.classList.toggle("finvault-defense-bars", isFinVaultRisk());
  if (isFinVaultRisk()) {
    renderFinVaultOverview();
    return;
  }
  const promptExtraction = isPromptExtractionRisk();
  const probeBenchmark = state.overview.probe_benchmark || {};
  populateGuardFilter();
  configureResultFilter();
  configureSettingsTable();
  configureSectionCopy();

  const displayedGuardMetrics = promptExtraction
    ? guardMetrics.filter((row) => row.guard !== "no_guard")
    : guardMetrics;
  elements.guardResultList.innerHTML = displayedGuardMetrics.map((row) => {
    const isSelectedProbe = promptExtraction && row.guard === "activation_probe";
    const completed = isSelectedProbe
      ? Number(probeBenchmark.test_attack_query_count || 0)
      : promptExtraction
      ? Number(row.protection_denominator ?? experiment.base_attack_success_count ?? 0)
      : Number(row.completed || 0);
    const rate = isSelectedProbe
      ? Number(probeBenchmark.attack_recall || 0)
      : promptExtraction
      ? Number(row.protection_success_rate || 0)
      : Number(row.detection_rate || 0);
    const count = isSelectedProbe
      ? Number(probeBenchmark.true_positive || 0)
      : promptExtraction
      ? Number(row.protection_success_count ?? Math.max(0, completed - Number(row.attack_success_count || 0)))
      : Number(row.detected || 0);
    const percent = Math.round(rate * 100);
    const metricNote = isSelectedProbe
      ? `${auditModelLabel()} · 独立测试集 Attack Query`
      : promptExtraction ? "基于 No Guard 泄露样本" : "";
    return `
      <div class="guard-result-row ${promptExtraction ? "protection" : ""}" data-guard="${row.guard}">
        <span class="guard-result-label"><strong>${escapeHtml(row.name)}</strong>${metricNote ? `<small>${escapeHtml(metricNote)}</small>` : ""}</span>
        <span class="result-track" role="img" aria-label="${escapeAttribute(`${count} / ${completed}`)}">
          <span class="result-fill" style="width:${percent}%"></span>
        </span>
        <span class="guard-result-value"><strong>${percent}%</strong><span>${count} / ${completed}</span></span>
      </div>`;
  }).join("");

  const facts = promptExtraction ? [
    ["被测模型", auditModelLabel()],
    ["模型结构", `${probeBenchmark.num_layers || "—"} 层 · Hidden ${probeBenchmark.hidden_size || "—"}`],
    ["Probe 读取", `${String(probeBenchmark.feature_type || "—").toUpperCase()} · 第 ${Number(probeBenchmark.start_layer || 0) + 1}–${Number(probeBenchmark.end_layer || 0) + 1} 层`],
    ["独立测试 Query", `${probeBenchmark.test_query_count || 0} 个（攻击 ${probeBenchmark.test_attack_query_count || 0} / 正常 ${probeBenchmark.test_normal_query_count || 0}）`],
    ["独立测试样本", `${probeBenchmark.test_sample_count || 0} 个 Query × System Prompt`],
    ["Query AUROC / F1", `${formatPercentPrecise(probeBenchmark.test_query_metrics?.auroc)} / ${formatPercentPrecise(probeBenchmark.test_query_metrics?.f1)}`],
    ["风险概率阈值", formatPercentPrecise(probeBenchmark.probability_threshold)],
    ["全量案例回放", `${experiment.attack_query_count} 个中文攻击 Query · 行为基线 Qwen3-8B`],
  ] : [
    ["被测 AI 助手", "Qwen3-8B"],
    ["攻击案例", `${experiment.sample_count} 次`],
    ["业务范围", "银行服务、旅行服务"],
    ["攻击组合", `${experiment.settings_count} 种`],
    ["检测方案", "4 种方案同场比较"],
    ["判断规则", `风险概率达到 ${Math.round(Number(experiment.threshold) * 100)}% 即预警`],
    ["数据格式", "统一 JSONL · 可复用审计数据"],
  ];
  elements.experimentFacts.innerHTML = facts.map(([label, value]) => `
    <div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>
  `).join("");

  const behaviorItems = promptExtraction ? [
    [probeBenchmark.true_positive || 0, "攻击检出", "success", `${probeBenchmark.test_attack_query_count || 0} 个独立测试攻击 Query`],
    [probeBenchmark.true_negative || 0, "正常放行", "success", `${probeBenchmark.test_normal_query_count || 0} 个独立测试正常 Query`],
    [probeBenchmark.false_positive || 0, "误报", Number(probeBenchmark.false_positive || 0) ? "danger" : "neutral", "正常 Query 被错误拦截"],
    [probeBenchmark.false_negative || 0, "漏报", Number(probeBenchmark.false_negative || 0) ? "danger" : "neutral", "攻击 Query 未被检出"],
  ] : [
    [behaviorMetrics.labels.followed_injection || 0, "跟随恶意指令", "danger", ""],
    [behaviorMetrics.labels.resisted_injection || 0, "识别并抵抗", "success", ""],
    [behaviorMetrics.labels.continued_user_task || 0, "继续原任务", "neutral", ""],
    [behaviorMetrics.labels.ambiguous || 0, "无法判断", "muted", ""],
  ];
  elements.behaviorSummary.innerHTML = behaviorItems.map(([value, label, tone, note]) => `
    <article class="behavior-summary-item ${tone}">
      <strong>${value}</strong>
      <span><b>${escapeHtml(label)}</b>${note ? `<small>${escapeHtml(note)}</small>` : ""}</span>
    </article>
  `).join("");

  const collectionAudit = integrity.collection_audit;
  const integrityItems = promptExtraction ? [
    ["模型间数据一致", `${integrity.probe_split_query_counts?.train || 0} / ${integrity.probe_split_query_counts?.val || 0} / ${integrity.probe_split_query_counts?.test || 0} 个 Train / Val / Test Query`],
    ["独立测试隔离", integrity.probe_model_selection_uses_test ? "测试集参与了模型选择" : "测试集未参与层或阈值选择"],
    ["提示词条件一致", `${integrity.distinct_prompt_fingerprints} 个 System Prompt 指纹`],
    ["测试样本完整", `${integrity.probe_split_sample_counts?.test || 0} 个条件样本全部完成`],
    ["运行无异常", `${guardMetrics.reduce((total, row) => total + row.errors, 0)} 次系统异常`],
  ] : [
    ["原始任务不受干预", collectionAudit.inline_request_fields_during_collection === 0 ? "采集时未启用任何护栏" : "发现意外干预"],
    ["每种方案输入一致", `${integrity.replay_requests} 个风险现场逐一复用`],
    ["输入内容逐字核验", `${integrity.distinct_prompt_fingerprints} 份输入均有独立指纹`],
    ["动作不会影响环境", integrity.replay_continuation_executed ? "发现工具被执行" : "模型动作只记录、不执行"],
    ["检测过程稳定", `${guardMetrics.reduce((total, row) => total + row.errors, 0)} 次系统异常`],
  ];
  elements.integrityGrid.innerHTML = integrityItems.map(([title]) => `
    <div class="integrity-item"><span class="integrity-check">✓</span><strong>${escapeHtml(title)}</strong></div>
  `).join("");

  elements.settingsTableBody.innerHTML = promptExtraction
    ? settings.map((row) => `
      <tr>
        <td>${escapeHtml(row.attack_category)}</td>
        <td class="attack-query-cell"><span title="${escapeAttribute(row.attack_query)}">${escapeHtml(row.attack_query)}</span></td>
        <td>${escapeHtml(row.attack_prompt_name)}</td>
        <td><span class="probe-split-badge ${escapeAttribute(row.probe_split)}">${escapeHtml(formatProbeSplit(row.probe_split))}</span></td>
        <td>${row.samples}</td>
        <td>${settingScore(row.baseline_attack_success_count, row.samples)}</td>
        <td>${settingScore(row.defense_success.activation_probe, row.baseline_attack_success_count)}</td>
        <td>${settingScore(row.defense_success.llama_prompt_guard, row.baseline_attack_success_count)}</td>
        <td>${settingScore(row.defense_success.qwen3_guard, row.baseline_attack_success_count)}</td>
        <td>${settingScore(row.defense_success.netease_yidun, row.baseline_attack_success_count)}</td>
      </tr>
    `).join("")
    : settings.map((row) => `
      <tr>
        <td>${escapeHtml(displaySuite(row.suite))}</td>
        <td>${escapeHtml(displayPolicy(row.system_prompt))}</td>
        <td>${escapeHtml(displayAttack(row.attack))}</td>
        <td>${row.samples}</td>
        <td>${settingScore(row.detected.inline_probing, row.samples)}</td>
        <td>${settingScore(row.detected.qwen3_guard, row.samples)}</td>
        <td>${settingScore(row.detected.netease_yidun, row.samples)}</td>
      </tr>
    `).join("");
}

function renderFinVaultOverview() {
  const { experiment, risk_metrics: riskMetrics, integrity, settings } = state.overview;
  const classificationRows = state.finvaultView === "risk" ? state.overview.risk_settings : settings;
  elements.finvaultViewSwitcher.hidden = false;
  elements.finvaultViewSwitcher.querySelectorAll("[data-finvault-view]").forEach((button) => {
    const active = button.dataset.finvaultView === state.finvaultView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  populateGuardFilter();
  configureResultFilter();
  configureSettingsTable();
  configureSectionCopy();

  const defenseMetrics = riskMetrics
    .filter((metric) => metric.key.endsWith("defense_success_rate"))
    .sort((left, right) => {
      const leftRate = Number.parseFloat(left.value);
      const rightRate = Number.parseFloat(right.value);
      return (Number.isFinite(rightRate) ? rightRate : -1) - (Number.isFinite(leftRate) ? leftRate : -1);
    });
  elements.guardResultList.innerHTML = defenseMetrics.map((metric) => {
    const guard = metric.key.replace(/_defense_success_rate$/, "");
    const methodName = metric.label.replace(/\s*(?:防御成功率|攻击检出率)$/, "");
    const displayName = methodName;
    const parsed = metric.value == null ? Number.NaN : Number.parseFloat(metric.value);
    const percent = Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : 0;
    const valueLabel = Number.isFinite(parsed) ? `${percent.toFixed(1)}%` : (metric.placeholder || "xx%");
    return `
      <button class="guard-result-row protection method-result-button" type="button" data-guard="${escapeAttribute(guard)}" data-method-details="${escapeAttribute(guard)}" aria-haspopup="dialog" aria-label="查看 ${escapeAttribute(displayName)} 的方法说明">
        <span class="guard-result-label"><strong>${escapeHtml(displayName)}</strong><em>查看方法</em></span>
        <span class="result-track" role="progressbar" aria-label="${escapeAttribute(`${metric.label} ${valueLabel}`)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent.toFixed(1)}">
          <span class="result-fill" style="width:${percent.toFixed(1)}%"></span>
        </span>
        <span class="guard-result-value"><strong>${escapeHtml(valueLabel)}</strong></span>
      </button>`;
  }).join("");

  const facts = [
    ["评测基准", "FinVault"],
    ["被测模型", auditModelLabel()],
    ["金融沙盒", `${experiment.scenario_count} 个`],
    ["原始攻击", `${experiment.sample_count + experiment.synthesized_sample_count} 个`],
    ["判定方式", "工具执行 + 状态变化 + 漏洞触发器"],
  ];
  elements.experimentFacts.innerHTML = facts.map(([label, value]) => `
    <div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>
  `).join("");

  const attackSuccessMetric = riskMetrics.find((metric) => metric.key === "attack_success_rate");
  const compromisedMetric = riskMetrics.find((metric) => metric.key === "compromised_vulnerabilities");
  const compromisedMatch = String(compromisedMetric?.value || "").match(/^(\d+)\s*\/\s*(\d+)$/);
  const attackCaseCount = experiment.sample_count + experiment.synthesized_sample_count;
  const coverage = [
    [attackSuccessMetric?.value || attackSuccessMetric?.placeholder || "xx%", "整体 ASR", "danger", "No Guard 下攻击成功率"],
    [compromisedMatch?.[1] || "xx", "攻破 Case", "danger", compromisedMatch ? `共 ${compromisedMatch[2]} 个攻击案例` : "按沙盒状态判定"],
    [attackCaseCount, "攻击 Case", "neutral", "参与整体 ASR 统计"],
    [experiment.scenario_count, "金融执行沙盒", "muted", "每个场景独立验证状态"],
  ];
  elements.behaviorSummary.innerHTML = coverage.map(([value, label, tone, note]) => `
    <article class="behavior-summary-item ${tone}">
      <strong>${value}</strong>
      <span><b>${escapeHtml(label)}</b><small>${escapeHtml(note)}</small></span>
    </article>
  `).join("");

  const integrityItems = [
    ["执行结果可验证", integrity.execution_grounded],
    ["31 个隔离沙盒", integrity.sandbox_count === 31],
    ["覆盖 6 类金融业务", settings.length === 6],
    [integrity.result_status === "complete" ? "模型结果已完整载入" : "模型结果待回填", integrity.result_status === "complete"],
  ];
  elements.integrityGrid.innerHTML = integrityItems.map(([title, ok], index) => {
    const pending = index === 3 && integrity.result_status !== "complete";
    return `
    <div class="integrity-item ${pending ? "pending" : ""}">
      <span class="integrity-check">${pending ? "…" : ok ? "✓" : "!"}</span>
      <strong>${escapeHtml(title)}</strong>
    </div>`;
  }).join("");

  elements.settingsTableBody.innerHTML = state.finvaultView === "risk"
    ? classificationRows.flatMap((row) => {
      const children = row.subcategories || [];
      const expandable = children.length > 0;
      const expanded = state.finvaultExpandedRisks.has(row.risk_type);
      const parent = `
    <tr class="finvault-risk-parent ${expandable ? "expandable" : ""}">
      <td>${expandable ? `<button class="risk-expand-button" type="button" data-risk-expand="${escapeAttribute(row.risk_type)}" aria-expanded="${expanded}"><span>${expanded ? "−" : "+"}</span><strong>${escapeHtml(row.risk_name)}</strong></button>` : `<strong>${escapeHtml(row.risk_name)}</strong>`}<small class="risk-subtype-summary">${escapeHtml(row.description)}</small><small class="risk-subtype-summary">覆盖：${escapeHtml(row.subtypes.join("、"))}</small></td>
      <td>${row.samples}</td>
      <td>${rateScore(row.attack_success_rate, "danger")}</td>
      <td>${defenseRateBar(row.suffix_probe_defense_success_rate)}</td>
      <td>${defenseRateBar(row.activation_probe_defense_success_rate)}</td>
      <td>${defenseRateBar(row.qwen3_guard_detection_rate)}</td>
      <td>${defenseRateBar(row.llama_prompt_guard_defense_success_rate)}</td>
      <td>${defenseRateBar(row.xguard_defense_success_rate)}</td>
      <td>${defenseRateBar(row.netease_yidun_defense_success_rate)}</td>
    </tr>`;
      const childRows = children.map((child) => `
    <tr class="finvault-risk-subcategory" data-risk-child="${escapeAttribute(row.risk_type)}" ${expanded ? "" : "hidden"}>
      <td><div class="risk-subcategory-name"><i></i><span><strong>${escapeHtml(child.name)}</strong><small>${escapeHtml(child.description)}</small><small>${child.attack_query_count} 个攻击 Query × ${child.system_prompt_count} 个 System Prompt · 完整匹配 ${child.exact_matches} 条</small></span></div></td>
      <td>${child.samples}</td>
      <td>${rateScore(child.attack_success_rate, "danger")}</td>
      <td>${notEvaluatedScore()}</td>
      <td>${notEvaluatedScore()}</td>
      <td>${notEvaluatedScore()}</td>
      <td>${notEvaluatedScore()}</td>
      <td>${notEvaluatedScore()}</td>
      <td>${notEvaluatedScore()}</td>
    </tr>`);
      return [parent, ...childRows];
    }).join("")
    : classificationRows.map((row) => `
    <tr>
      <td><strong>${escapeHtml(row.domain_name)}</strong></td>
      <td>${row.scenario_count}</td>
      <td>${row.samples}</td>
      <td>${row.attack_success_rate == null ? pendingScore() : settingValue(`${(row.attack_success_rate * 100).toFixed(1)}%`, "danger")}</td>
      <td>${row.violation_count == null ? pendingScore() : settingValue(row.violation_count, row.violation_count ? "danger" : "full")}</td>
    </tr>
  `).join("");
  bindFinVaultRiskExpansions();
}

function bindFinVaultRiskExpansions() {
  elements.settingsTableBody.querySelectorAll("[data-risk-expand]").forEach((button) => {
    button.addEventListener("click", () => {
      const riskType = button.dataset.riskExpand;
      if (state.finvaultExpandedRisks.has(riskType)) {
        state.finvaultExpandedRisks.delete(riskType);
      } else {
        state.finvaultExpandedRisks.add(riskType);
      }
      renderFinVaultOverview();
    });
  });
}

function rateScore(value, tone = "") {
  return value == null ? pendingScore() : settingValue(`${(Number(value) * 100).toFixed(1)}%`, tone);
}

function defenseRateBar(value) {
  if (value == null || value === "") return pendingScore();
  const numeric = typeof value === "string"
    ? Number.parseFloat(value) / (value.includes("%") ? 100 : 1)
    : Number(value);
  if (!Number.isFinite(numeric)) return pendingScore();
  const percent = Math.max(0, Math.min(100, numeric * 100));
  const label = `${percent.toFixed(1)}%`;
  return `<div class="defense-rate-bar" role="progressbar" aria-label="攻击检出率 ${label}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent.toFixed(1)}">
    <span class="defense-rate-track"><i style="width: ${percent.toFixed(1)}%"></i></span>
    <strong>${label}</strong>
  </div>`;
}

function populateGuardFilter() {
  const previous = elements.guardFilter.value;
  if (isFinVaultRisk()) {
    elements.guardFilter.innerHTML = `<option value="attack">全部攻击</option>
      <option value="original">原始攻击</option>
      <option value="synthesis">8 类合成攻击</option>`;
    elements.guardFilter.value = ["attack", "original", "synthesis"].includes(previous) ? previous : "attack";
    return;
  }
  elements.guardFilter.innerHTML = `<option value="all">全部方案</option>${activeGuards().map((guard) => `
    <option value="${escapeAttribute(guard)}">${escapeHtml(GUARD_NAMES[guard] || formatName(guard))}</option>
  `).join("")}`;
  elements.guardFilter.value = previous === "all" || activeGuards().includes(previous) ? previous : "all";
}

function configureResultFilter() {
  const previous = elements.resultFilter.value;
  elements.resultFilter.innerHTML = isFinVaultRisk()
    ? `<option value="all">全部运行状态</option><option value="pending">待运行</option><option value="unsafe">风险失败</option><option value="safe">安全通过</option>`
    : isPromptExtractionRisk()
    ? `<option value="all">全部结果</option><option value="detected">存在泄露</option><option value="missed">没有泄露</option>`
    : `<option value="all">全部结果</option><option value="detected">已检出</option><option value="missed">未检出</option>`;
  const allowed = isFinVaultRisk() ? ["all", "pending", "unsafe", "safe"] : ["all", "detected", "missed"];
  elements.resultFilter.value = allowed.includes(previous) ? previous : "all";
}

function configureSettingsTable() {
  const labels = isFinVaultRisk()
    ? state.finvaultView === "risk"
      ? ["风险类型", "攻击案例", "攻击成功率", "SafeGauge (Ours)", "Activation Probe (Ours)", "Qwen3Guard", "Llama Prompt Guard 2", "YuFeng-XGuard", "网易易盾"]
      : ["金融领域", "沙盒场景", "攻击案例", "攻击成功率", "触发漏洞"]
    : isPromptExtractionRisk()
    ? ["攻击类别", "攻击 Query", "样本", "Probe 数据划分", "System Prompt 数", "No Guard 泄露", "Activation Probe (Ours) 防御成功", "Llama Prompt Guard 2 防御成功", "Qwen3Guard 防御成功", "网易易盾防御成功"]
    : ["业务场景", "助手安全策略", "攻击伪装方式", "测试次数", "Inline Probe", "Qwen3Guard", "网易易盾"];
  document.querySelector("#settingsTableHead tr").innerHTML = labels
    .map((label) => `<th>${escapeHtml(label)}</th>`)
    .join("");
}

function configureSectionCopy() {
  const promptExtraction = isPromptExtractionRisk();
  const finvault = isFinVaultRisk();
  elements.integritySection.hidden = finvault;
  elements.guardResultTitle.textContent = finvault ? "攻击检出率" : promptExtraction ? "Probe 测试集与防御结果" : "检测结果";
  elements.settingsTitle.textContent = finvault
    ? state.finvaultView === "risk" ? "按安全后果分类" : "六大金融领域风险概览"
    : promptExtraction ? "按 Attack Query 聚合" : "分类结果";
  elements.finvaultViewSwitcher.hidden = !finvault;
  elements.explorerTitle.textContent = finvault ? "风险类型 × 金融领域任务清单" : promptExtraction ? "Attack Query 记录" : "案例记录";
  elements.traceSubjectTitle.textContent = finvault ? "金融场景与风险" : promptExtraction ? "攻击 Query" : "风险场景";
  if (finvault) {
    elements.traceResultTitle.innerHTML = `<span class="finvault-guard-column-labels">${FINVAULT_CASE_GUARDS.map(([, name]) => `<b>${escapeHtml(name)}</b>`).join("")}</span>`;
    elements.traceResultTitle.setAttribute("aria-label", "方法检出结果");
  } else {
    elements.traceResultTitle.textContent = promptExtraction ? "Probe / 偷取结果" : "检测结果";
    elements.traceResultTitle.removeAttribute("aria-label");
  }
  elements.search.placeholder = finvault ? "搜索金融场景、风险类型或案例编号" : promptExtraction ? "搜索攻击 Query 或攻击类型" : "搜索案例或攻击类型";
  elements.guardFilterLabel.hidden = finvault;
  elements.resultFilterLabel.hidden = finvault;
  elements.riskTypeFilterLabel.hidden = !finvault;
  const traceListPanel = elements.traceList.closest(".trace-list-panel");
  traceListPanel?.classList.toggle("finvault", finvault);
  traceListPanel?.closest(".trace-explorer")?.classList.toggle("finvault", finvault);
}

function populateSettingFilter() {
  const rows = state.overview.settings;
  elements.settingFilter.innerHTML = `<option value="all">${isFinVaultRisk()
    ? "全部金融领域"
    : isPromptExtractionRisk() ? "全部攻击 Query" : "全部业务场景"}</option>`;
  elements.settingFilter.insertAdjacentHTML("beforeend", rows.map((row) => `
    <option value="${escapeAttribute(row.grid_point_id)}">${isFinVaultRisk()
      ? escapeHtml(row.domain_name)
      : isPromptExtractionRisk()
      ? `${escapeHtml(row.attack_category)} · ${escapeHtml(row.attack_prompt_name)}`
      : `${escapeHtml(displaySuite(row.suite))} · ${escapeHtml(displayPolicy(row.system_prompt))} · ${escapeHtml(displayAttack(row.attack))}`}</option>
  `).join(""));
  if (isFinVaultRisk()) {
    const allowed = ["all", ...rows.map((row) => row.grid_point_id)];
    const selected = allowed.includes(state.finvaultDomainFilter)
      ? state.finvaultDomainFilter
      : "all";
    elements.settingFilter.value = selected;
    state.finvaultDomainFilter = selected;
  }
}

function populateFinVaultRiskFilter() {
  const finvault = isFinVaultRisk();
  elements.riskTypeFilterLabel.hidden = !finvault;
  if (!finvault) return;
  const rows = state.overview.risk_settings || [];
  elements.riskTypeFilter.innerHTML = `<option value="all">全部风险类型</option>${rows.map((row) => `
    <option value="${escapeAttribute(row.risk_type)}">${escapeHtml(row.risk_name)}</option>
  `).join("")}`;
  const allowed = ["all", ...rows.map((row) => row.risk_type)];
  const selected = allowed.includes(state.finvaultRiskFilter)
    ? state.finvaultRiskFilter
    : "all";
  elements.riskTypeFilter.value = selected;
  state.finvaultRiskFilter = selected;
}

function applyFilters({ immediate = false } = {}) {
  if (!state.overview) return;
  if (isFinVaultRisk()) {
    state.finvaultOffset = 0;
    scheduleFinVaultCases(immediate);
    return;
  }
  const query = elements.search.value.trim().toLowerCase();
  const guard = elements.guardFilter.value;
  const result = elements.resultFilter.value;
  const setting = elements.settingFilter.value;
  const riskType = elements.riskTypeFilter.value;
  state.filteredCases = state.overview.cases.filter((row) => {
    const haystack = [row.decision_point_id, row.trace_id, row.grid_point_id, row.attack, row.attack_type, row.attack_prompt, row.vulnerability, row.scenario_name, row.scenario_name_en, row.suite, row.risk_names, row.risk_subtypes, row.business_risk_name].join(" ").toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (setting !== "all") {
      if (row.grid_point_id !== setting) return false;
    }
    if (isFinVaultRisk() && riskType !== "all" && !row.risk_types.includes(riskType)) return false;
    if (isFinVaultRisk() && guard !== "all" && row.dataset_type !== guard) return false;
    if (result !== "all") {
      if (isFinVaultRisk()) return row.evaluation_status === result;
      const detected = isPromptExtractionRisk()
        ? guard === "all"
          ? Number(row.guard_results.no_guard.attack_success_count || 0) > 0
          : Number(row.guard_results[guard]?.attack_success_count || 0) > 0
        : guard === "all"
          ? row.detected_by.length > 0
          : row.guard_results[guard]?.detected === true;
      if ((result === "detected") !== detected) return false;
    }
    return true;
  }).sort((left, right) => {
    const suiteDifference = (SUITE_ORDER[left.suite] ?? 99) - (SUITE_ORDER[right.suite] ?? 99);
    return suiteDifference || Number(left.sample_index) - Number(right.sample_index);
  });
  if (!state.filteredCases.some((row) => row.sample_index === state.activeSample)) {
    state.activeSample = state.filteredCases[0]?.sample_index ?? null;
  }
  renderCaseList();
  if (state.activeSample !== null) loadCaseDetail(state.activeSample);
}

function scheduleFinVaultCases(immediate = false) {
  window.clearTimeout(state.finvaultFilterTimer);
  if (immediate) {
    loadFinVaultCases();
    return;
  }
  state.finvaultFilterTimer = window.setTimeout(loadFinVaultCases, 180);
}

async function loadFinVaultCases() {
  if (!state.overview || !isFinVaultRisk()) return;
  window.clearTimeout(state.finvaultFilterTimer);
  state.finvaultCasesController?.abort();
  const controller = new AbortController();
  state.finvaultCasesController = controller;
  const requestId = ++state.finvaultCasesRequest;
  const params = new URLSearchParams({
    model: state.finvaultModel,
    risk_type: elements.riskTypeFilter.value,
    domain: elements.settingFilter.value,
    dataset_type: "attack",
    evaluation_status: "all",
    search: elements.search.value.trim(),
    offset: String(state.finvaultOffset),
    limit: String(state.finvaultLimit),
  });
  elements.traceList.innerHTML = `<div class="trace-detail-loading"><span class="audit-loading-dot"></span><p>正在加载当前筛选案例</p></div>`;
  elements.traceEmpty.hidden = true;
  try {
    const response = await fetch(`/api/audit/finvault/cases?${params}`, { signal: controller.signal });
    if (!response.ok) throw new Error(`案例列表接口返回 ${response.status}`);
    const payload = await response.json();
    if (requestId !== state.finvaultCasesRequest) return;
    state.filteredCases = payload.cases || [];
    state.finvaultTotal = Number(payload.total || 0);
    state.finvaultOffset = Number(payload.offset || 0);
    const previousSample = state.activeSample;
    if (!state.filteredCases.some((row) => row.sample_index === previousSample)) {
      state.activeSample = state.filteredCases[0]?.sample_index ?? null;
    }
    renderFinVaultCaseList();
    if (state.activeSample !== null) {
      const detailSample = Number(state.activeDetail?.case?.sample_index);
      if (state.activeSample !== previousSample || detailSample !== state.activeSample) {
        loadCaseDetail(state.activeSample);
      }
    } else {
      state.activeDetail = null;
      elements.traceDetail.innerHTML = `<div class="trace-detail-placeholder"><p>当前筛选条件下没有案例</p></div>`;
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    if (requestId !== state.finvaultCasesRequest) return;
    state.filteredCases = [];
    state.finvaultTotal = 0;
    renderFinVaultCaseList();
    elements.traceDetail.innerHTML = renderError(error.message);
  }
}

function renderCaseList() {
  if (isFinVaultRisk()) {
    renderFinVaultCaseList();
    return;
  }
  elements.finvaultPagination.hidden = true;
  const guard = elements.guardFilter.value;
  const promptExtraction = isPromptExtractionRisk();
  elements.caseCountLabel.textContent = `显示 ${state.filteredCases.length} / ${state.overview.cases.length} ${promptExtraction ? "个攻击 Query" : "个案例"}`;
  elements.traceEmpty.hidden = state.filteredCases.length > 0;
  elements.traceList.innerHTML = state.filteredCases.map((row) => {
    const dots = activeGuards().map((guardId) => {
      const result = row.guard_results[guardId];
      const hit = promptExtraction ? Number(result.attack_success_count || 0) > 0 : result.detected === true;
      const title = promptExtraction
        ? `${GUARD_NAMES[guardId]}：偷取 ${result.attack_success_count} / ${result.total}`
        : `${GUARD_NAMES[guardId]}：${hit ? "已预警" : "未预警"}`;
      return `<span class="detection-dot ${hit ? "hit" : ""}" title="${escapeAttribute(title)}"></span>`;
    }).join("");
    const selectedGuard = guard === "all" ? "no_guard" : guard;
    const selectedResult = row.guard_results[selectedGuard];
    const secondary = promptExtraction
      ? `${formatProbeSplit(row.probe_evaluation?.split)} · ${row.attack_prompt} · ${GUARD_NAMES[selectedGuard]} 偷取 ${selectedResult.attack_success_count}/${selectedResult.total}`
      : "";
    return `
      <button class="trace-row ${promptExtraction ? "prompt-extraction-row" : ""} ${row.sample_index === state.activeSample ? "active" : ""}" data-sample-index="${row.sample_index}" type="button">
        <span class="trace-index">#${String(row.sample_index).padStart(3, "0")}</span>
        <span class="trace-setting">
          <strong>${escapeHtml(promptExtraction ? row.attack : `${displaySuite(row.suite)} · ${displayAttack(row.attack)}`)}</strong>
          ${secondary ? `<small>${escapeHtml(secondary)}</small>` : ""}
        </span>
        <span class="detection-dots">${dots}</span>
      </button>`;
  }).join("");
  elements.traceList.querySelectorAll(".trace-row").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeSample = Number(button.dataset.sampleIndex);
      renderCaseList();
      loadCaseDetail(state.activeSample);
    });
  });
}

function renderFinVaultCaseList() {
  const domainLabel = elements.settingFilter.selectedOptions[0]?.textContent || "全部金融领域";
  const riskLabel = elements.riskTypeFilter.selectedOptions[0]?.textContent || "全部风险类型";
  const first = state.finvaultTotal ? state.finvaultOffset + 1 : 0;
  const last = Math.min(state.finvaultOffset + state.filteredCases.length, state.finvaultTotal);
  elements.caseCountLabel.textContent = `${riskLabel} × ${domainLabel} · 共 ${state.finvaultTotal} 条，当前 ${first}–${last}`;
  const pageCount = Math.max(1, Math.ceil(state.finvaultTotal / state.finvaultLimit));
  const currentPage = Math.floor(state.finvaultOffset / state.finvaultLimit) + 1;
  elements.finvaultPagination.hidden = state.finvaultTotal <= state.finvaultLimit;
  elements.finvaultPageLabel.textContent = `第 ${currentPage} / ${pageCount} 页`;
  elements.finvaultPrevPage.disabled = state.finvaultOffset <= 0;
  elements.finvaultNextPage.disabled = state.finvaultOffset + state.finvaultLimit >= state.finvaultTotal;
  elements.traceEmpty.hidden = state.filteredCases.length > 0;
  elements.traceList.innerHTML = state.filteredCases.map((row) => {
    const guardDots = FINVAULT_CASE_GUARDS.map(([guardKey]) => {
      const result = row.guard_detections?.[guardKey];
      const tone = result?.status !== "complete" || result?.detected == null
        ? "pending"
        : result.detected ? "detected" : "missed";
      const conclusion = tone === "detected" ? "已检出" : tone === "missed" ? "未检出" : "未运行";
      const methodName = GUARD_NAMES[guardKey] || guardKey;
      return `<span class="finvault-guard-dot ${tone}" data-tooltip="${escapeAttribute(`${methodName}：${conclusion}`)}" aria-label="${escapeAttribute(`${methodName}：${conclusion}`)}"><i></i></span>`;
    }).join("");
    return `
    <button class="trace-row finvault-trace-row ${row.sample_index === state.activeSample ? "active" : ""}" data-sample-index="${row.sample_index}" type="button">
      <span class="trace-index">#${String(row.sample_index + 1).padStart(3, "0")}</span>
      <span class="trace-setting">
        <strong>${escapeHtml(row.scenario_name)}</strong>
        <small>${escapeHtml(`${row.attack_technique} · ${displaySuite(row.suite)} · ${row.risk_names.join(" / ")}`)}</small>
      </span>
      <span class="finvault-guard-dots" role="group" aria-label="各方法攻击检出结果">${guardDots}</span>
    </button>
  `;
  }).join("");
  bindFinVaultGuardTooltips();
  elements.traceList.querySelectorAll(".trace-row").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeSample = Number(button.dataset.sampleIndex);
      renderCaseList();
      loadCaseDetail(state.activeSample);
    });
  });
}

async function loadCaseDetail(sampleIndex) {
  const risk = getActiveRisk();
  const caseEndpoint = risk?.case_endpoint || "/api/audit/experiment/cases/{sample_index}";
  const requestId = ++state.detailRequest;
  state.detailController?.abort();
  const controller = new AbortController();
  state.detailController = controller;
  const loadingLabel = isFinVaultRisk() ? "正在加载 FinVault 风险案例" : "正在加载冻结 trace";
  elements.traceDetail.innerHTML = `<div class="trace-detail-loading"><span class="audit-loading-dot"></span><p>${loadingLabel} #${String(sampleIndex).padStart(3, "0")}</p></div>`;
  try {
    const detailUrl = caseEndpoint.replace("{sample_index}", encodeURIComponent(sampleIndex));
    const response = await fetch(
      isModelSelectableRisk() ? `${detailUrl}?model=${encodeURIComponent(state.finvaultModel)}` : detailUrl,
      { signal: controller.signal },
    );
    if (!response.ok) throw new Error(`详情接口返回 ${response.status}`);
    const detail = await response.json();
    if (requestId !== state.detailRequest) return;
    state.activeDetail = detail;
    renderCaseDetail(detail);
  } catch (error) {
    if (error.name === "AbortError") return;
    if (requestId !== state.detailRequest) return;
    elements.traceDetail.innerHTML = renderError(error.message);
  }
}

function renderCaseDetail(detail) {
  if (detail.kind === "finvault") {
    renderFinVaultDetail(detail);
    return;
  }
  if (detail.kind === "prompt_extraction") {
    renderPromptExtractionDetail(detail);
    return;
  }
  const { case: caseRow, decision_point: decision, trace, guard_results: guardResults, evidence, agent_behavior: agentBehavior } = detail;
  const detectorCards = activeGuards().map((guard) => renderDetectorCard(guard, guardResults[guard])).join("");
  const businessMessages = detail.messages.filter((message) => message.role !== "system");
  const messages = businessMessages.map((message) => renderStoryMessage(message)).join("");
  const userRequest = businessMessages.find((message) => message.role === "user")?.content || "未记录用户请求";
  const systemMessage = detail.messages.find((message) => message.role === "system")?.content || "";
  const evidenceRows = Object.entries(evidence).map(([key, value]) => `
    <div class="evidence-item"><span>${escapeHtml(formatName(key))}</span><span class="evidence-value">${escapeHtml(value || "n/a")}</span></div>
  `).join("");
  const rawDetectorOutput = Object.fromEntries(activeGuards().map((guard) => [
    GUARD_NAMES[guard],
    Object.fromEntries(Object.entries(guardResults[guard].input_modes || {}).map(([mode, result]) => [mode, result.raw_output])),
  ]));
  const behaviorView = behaviorPresentation(agentBehavior.label);
  const behaviorCalls = (agentBehavior.message?.tool_calls || []).map(renderToolCall).join("");
  const visibleAnswer = visibleModelAnswer(agentBehavior.message?.content || "");

  elements.traceDetail.innerHTML = `
    <header class="trace-detail-header">
      <h3>#${String(caseRow.sample_index).padStart(3, "0")} · ${escapeHtml(displaySuite(caseRow.suite))} · ${escapeHtml(displayAttack(caseRow.attack))}</h3>
    </header>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>案例概览</h4></div>
      <div class="case-overview-grid">
        <article class="case-overview-item request">
          <span class="case-overview-icon">1</span>
          <div><strong>客户原本想做什么</strong><p>${escapeHtml(userRequest)}</p></div>
        </article>
        <article class="case-overview-item danger">
          <span class="case-overview-icon">2</span>
          <div><strong>助手意外看到了什么</strong><p>${escapeHtml(detail.exposed_tool_result || detail.injected_text)}</p></div>
        </article>
      </div>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>检测结果</h4></div>
      <div class="detector-detail-grid">${detectorCards}</div>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>模型行为</h4></div>
      <article class="model-behavior-card ${behaviorView.tone}">
        <div class="model-behavior-head">
          <span class="behavior-verdict">${escapeHtml(behaviorView.label)}</span>
          <span>置信度 ${Math.round(Number(agentBehavior.confidence || 0) * 100)}%</span>
        </div>
        <p class="behavior-reason">${escapeHtml(agentBehavior.reason)}</p>
        ${behaviorCalls ? `<div class="behavior-actions"><span>模型准备调用：</span>${behaviorCalls}</div>` : ""}
        ${visibleAnswer ? `<div class="behavior-answer"><strong>给用户的回复</strong><p>${escapeHtml(visibleAnswer)}</p></div>` : ""}
      </article>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>事件经过</h4></div>
      <div class="conversation-list story-timeline">${messages}</div>
    </section>

    <details class="technical-evidence">
      <summary><span>技术审计证据</span></summary>
      <div class="technical-evidence-body">
        <h4>输入一致性指纹</h4>
        <div class="evidence-grid">${evidenceRows}</div>
        <h4>模型与执行信息</h4>
        <pre>${escapeHtml(prettyJson({
          request_model: decision.request_model,
          prompt_tokens: decision.prompt_token_count,
          assistant_message_index: decision.assistant_message_index,
          available_tools: decision.tool_names,
          system_message: systemMessage,
          original_outcome: trace.outcome,
          agent_behavior: agentBehavior,
        }))}</pre>
        <h4>检测器原始输出</h4>
        <pre>${escapeHtml(prettyJson(rawDetectorOutput))}</pre>
      </div>
    </details>`;
}

function finvaultDefenseState(risky, blocked, status) {
  if (status !== "complete" || risky === null || risky === undefined) {
    return { label: "未运行", tone: "pending" };
  }
  if (risky && blocked) return { label: "拦截", tone: "blocked" };
  if (risky) return { label: "存在风险", tone: "risk" };
  return { label: "通过", tone: "passed" };
}

function renderFinVaultDefenseSummary({ activationProbe, suffixProbe, queryGuard, llamaGuard, xguard, yidunGuard, evaluation }) {
  const activation = finvaultDefenseState(activationProbe?.risky, activationProbe?.blocked, activationProbe?.status);
  const safeGauge = finvaultDefenseState(suffixProbe?.risky, suffixProbe?.blocked, suffixProbe?.status);
  const qwen = finvaultDefenseState(queryGuard?.risky, queryGuard?.blocked, queryGuard?.status);
  const llama = finvaultDefenseState(llamaGuard?.risky, llamaGuard?.blocked, llamaGuard?.status);
  const xguardState = finvaultDefenseState(xguard?.risky, xguard?.blocked, xguard?.status);
  const yidun = finvaultDefenseState(yidunGuard?.risky, yidunGuard?.blocked, yidunGuard?.status);
  const cards = [
    ["SafeGauge", "逐轮检测", safeGauge, null],
    ["Activation Probe", activationProbe?.turns?.length ? `${activationProbe.turns.length} 轮均检测` : "逐轮检测", activation, null],
    ["Qwen3Guard-Gen-8B", queryGuard?.turns?.length ? `${queryGuard.turns.length} 轮均检测` : "逐轮检测", qwen, null],
    ["Llama Prompt Guard 2", "仅首轮结果", llama, llamaGuard?.probability == null ? null : `恶意概率 ${(Number(llamaGuard.probability) * 100).toFixed(1)}%`],
    ["YuFeng-XGuard", xguard?.turns?.length ? `${xguard.turns.length} 轮均检测` : "逐轮检测", xguardState, xguard?.risk_probability == null ? null : `最高风险 ${(Number(xguard.risk_probability) * 100).toFixed(1)}%`],
    ["网易易盾", "仅首轮结果", yidun, null],
  ];
  return `<div class="finvault-defense-summary">${cards.map(([name, scope, state, inlineDetail]) => `
    <article class="finvault-defense-card ${state.tone}">
      <header><strong>${escapeHtml(name)}</strong><span>${escapeHtml(scope)}</span></header>
      <div><i></i><b>${escapeHtml(state.label)}</b>${inlineDetail ? `<small>${escapeHtml(inlineDetail)}</small>` : ""}</div>
    </article>`).join("")}</div>`;
}

function finvaultToolSummary(turn) {
  const action = turn.parsed_action || parseToolArguments(turn.action);
  const tool = action?.tool || "未知工具";
  const args = action?.args && typeof action.args === "object" ? action.args : {};
  const argSummary = Object.entries(args).slice(0, 3).map(([key, value]) => {
    const rendered = Array.isArray(value) ? value.join(", ") : typeof value === "object" ? prettyJson(value) : String(value);
    return `${key}=${rendered}`;
  }).join(" · ");
  const toolResult = turn.environment_info?.tool_result;
  const resultStatus = toolResult?.status || (toolResult?.success === true ? "success" : null);
  return { tool, argSummary, resultStatus, reward: turn.reward, vulnerabilities: turn.vulnerabilities || [] };
}

function renderFinVaultRoundFlow({ queryTurns, isNormal, activationProbe, suffixProbe, queryGuard, llamaGuard, xguard, yidunGuard, evaluation }) {
  const detectorTurns = suffixProbe?.turns || [];
  const activationTurns = activationProbe?.turns || [];
  const qwenGuardTurns = queryGuard?.turns || [];
  const xguardTurns = xguard?.turns || [];
  const executionTurns = evaluation.turns || [];
  const maxExecutionRound = executionTurns.reduce((maximum, turn) => Math.max(maximum, Number(turn.multi_turn || 1)), 0);
  const roundCount = Math.max(1, queryTurns.length, detectorTurns.length, activationTurns.length, qwenGuardTurns.length, xguardTurns.length, maxExecutionRound);
  const phaseLabels = {
    normal: "正常轮次",
    pre_attack: "攻击前轮次",
    attack_onset: "攻击出现轮",
    post_attack: "攻击后轮次",
  };
  const firstRoundGuards = [
    ["Llama Guard", llamaGuard],
    ["网易易盾", yidunGuard],
  ];
  const activationTimeline = Array.from({ length: roundCount }, (_, index) => {
    const round = index + 1;
    const detection = activationTurns.find((turn) => Number(turn.turn_index) === round);
    const state = finvaultDefenseState(detection?.prediction, detection?.prediction ? activationProbe?.blocked : false, detection ? "complete" : "pending");
    return `<div class="activation-round-node ${state.tone}">
      <span>第 ${round} 轮</span><i></i><strong>${escapeHtml(state.label)}</strong>
    </div>`;
  }).join('<span class="activation-round-arrow" aria-hidden="true">→</span>');
  let safeGaugeDetectedThroughRound = false;
  let safeGaugeFalsePositiveThroughRound = false;
  let safeGaugeAttackObservedThroughRound = false;
  let safeGaugeObservedThroughRound = false;
  return `<div class="activation-round-timeline">
      <div class="activation-round-title"><strong>Activation Probe</strong><span>每轮 Assistant 回复前检测</span></div>
      <div class="activation-round-track">${activationTimeline}</div>
    </div>
    <div class="finvault-round-flow">${Array.from({ length: roundCount }, (_, index) => {
    const round = index + 1;
    const detection = detectorTurns.find((turn) => Number(turn.turn_index) === round);
    const activationDetection = activationTurns.find((turn) => Number(turn.turn_index) === round);
    const qwenGuardDetection = qwenGuardTurns.find((turn) => Number(turn.turn_index) === round);
    const xguardDetection = xguardTurns.find((turn) => Number(turn.turn_index) === round);
    const tools = executionTurns.filter((turn) => Number(turn.multi_turn || 1) === round).map(finvaultToolSummary);
    const query = queryTurns[index] || activationDetection?.query || detection?.user_query || "未保存本轮用户输入";
    const phase = phaseLabels[activationDetection?.phase || detection?.phase] || (round === 1 ? "首轮输入" : "后续轮次");
    const safeGaugeTurnTriggered = detection != null && Number(detection.prediction) === 1;
    const safeGaugeTurnIsAttack = detection != null && Number(detection.label) === 1;
    if (detection) {
      safeGaugeObservedThroughRound = true;
      safeGaugeAttackObservedThroughRound ||= safeGaugeTurnIsAttack;
      safeGaugeDetectedThroughRound ||= safeGaugeTurnTriggered && safeGaugeTurnIsAttack && !isNormal;
      safeGaugeFalsePositiveThroughRound ||= safeGaugeTurnTriggered && (!safeGaugeTurnIsAttack || isNormal);
    }
    const safeGaugeState = !detection
      ? { label: "本轮未运行", tone: "pending" }
      : (isNormal || !safeGaugeTurnIsAttack)
        ? {
          label: safeGaugeTurnTriggered ? "本轮误报" : "本轮未触发",
          tone: safeGaugeTurnTriggered ? "risk" : "passed",
        }
        : {
          label: safeGaugeTurnTriggered ? "本轮命中" : "本轮未命中",
          tone: safeGaugeDetectedThroughRound ? "risk" : "passed",
        };
    const safeGaugeCumulative = !safeGaugeObservedThroughRound
      ? "累计至本轮：待运行"
      : isNormal
        ? (safeGaugeFalsePositiveThroughRound ? "累计至本轮：有误报" : "累计至本轮：无误报")
        : safeGaugeDetectedThroughRound
          ? "累计至本轮：已检出攻击"
          : safeGaugeAttackObservedThroughRound
            ? (safeGaugeFalsePositiveThroughRound ? "累计至本轮：未检出攻击 · 曾误报" : "累计至本轮：未检出攻击")
            : (safeGaugeFalsePositiveThroughRound ? "累计至本轮：攻击未出现 · 已误报" : "累计至本轮：攻击尚未出现");
    const safeGaugeCumulativeAlert = safeGaugeDetectedThroughRound || safeGaugeFalsePositiveThroughRound;
    const activationState = finvaultDefenseState(activationDetection?.prediction, activationDetection?.prediction ? activationProbe?.blocked : false, activationDetection ? "complete" : "pending");
    const qwenGuardState = finvaultDefenseState(qwenGuardDetection?.risky, qwenGuardDetection?.blocked, qwenGuardDetection ? "complete" : "pending");
    const xguardState = finvaultDefenseState(xguardDetection?.prediction, xguardDetection?.prediction, xguardDetection ? "complete" : "pending");
    const score = detection?.score == null ? Number.NaN : Number(detection.score);
    const activationProbability = activationDetection?.probability == null ? Number.NaN : Number(activationDetection.probability);
    const xguardProbability = xguardDetection?.risk_probability == null ? Number.NaN : Number(xguardDetection.risk_probability);
    const queryPreview = query.replace(/\s+/g, " ").trim();
    return `
      <article class="finvault-round ${(activationDetection?.phase || detection?.phase) === "attack_onset" ? "attack-onset" : ""}">
        <header><span>${round}</span><div><strong>第 ${round} 轮</strong><small>${escapeHtml(phase)}</small></div></header>
        <div class="finvault-round-lane input-lane">
          <span class="lane-label">用户输入</span>
          <details><summary>${escapeHtml(queryPreview.length > 116 ? `${queryPreview.slice(0, 116)}…` : queryPreview)}</summary><blockquote>${escapeHtml(query)}</blockquote></details>
        </div>
        <div class="finvault-round-lane guard-lane">
          <span class="lane-label">执行前检测</span>
          <div class="finvault-round-guards">
            <span class="round-guard safegauge-round-guard ${safeGaugeState.tone}">
              <b>SafeGauge</b><i></i><span>${safeGaugeState.label}${Number.isFinite(score) ? ` · ${(score * 100).toFixed(1)}%` : ""}</span>
              <em class="${safeGaugeCumulativeAlert ? "detected" : "clear"}">${safeGaugeCumulative}</em>
            </span>
            <span class="round-guard activation-round-result ${activationState.tone}"><b>Activation Probe · 本轮检测</b><i></i>${activationState.label}${Number.isFinite(activationProbability) ? ` · ${(activationProbability * 100).toFixed(1)}%` : ""}</span>
            <span class="round-guard qwen-guard-round-result ${qwenGuardState.tone}"><b>Qwen3Guard · 本轮检测</b><i></i>${qwenGuardState.label}${qwenGuardDetection?.safety_label ? ` · ${escapeHtml(qwenGuardDetection.safety_label)}` : ""}</span>
            <span class="round-guard xguard-round-result ${xguardState.tone}"><b>XGuard · 本轮检测</b><i></i>${xguardState.label}${Number.isFinite(xguardProbability) ? ` · ${(xguardProbability * 100).toFixed(1)}%` : ""}</span>
            ${firstRoundGuards.map(([name, guard]) => {
              if (round !== 1) return `<span class="round-guard pending"><b>${escapeHtml(name)}</b><i></i>本轮未运行</span>`;
              const state = finvaultDefenseState(guard?.risky, guard?.blocked, guard?.status);
              return `<span class="round-guard ${state.tone}"><b>${escapeHtml(name)}</b><i></i>${state.label}</span>`;
            }).join("")}
          </div>
        </div>
        <div class="finvault-round-lane tool-lane">
          <span class="lane-label">Agent 工具调用</span>
          ${tools.length ? `<div class="finvault-round-tools">${tools.map((tool) => `
            <div class="round-tool ${tool.vulnerabilities.length ? "danger" : ""}">
              <strong>${escapeHtml(tool.tool)}</strong>
              <small>${escapeHtml(tool.argSummary || "无参数")}</small>
              <span>${escapeHtml(tool.resultStatus === "success" ? "执行成功" : tool.resultStatus || "已执行")}${tool.reward == null ? "" : ` · reward ${escapeHtml(tool.reward)}`}</span>
            </div>`).join("")}</div>` : `<p class="round-empty">${round > maxExecutionRound ? "当前执行报告未覆盖这一轮" : "本轮没有工具调用"}</p>`}
        </div>
      </article>`;
  }).join("")}</div>`;
}

function renderFinVaultDetail(detail) {
  const { case: caseRow, source, translation, system_prompt: systemPrompt, evaluation, activation_probe: activationProbe, suffix_probe: suffixProbe, query_guard: queryGuard, llama_prompt_guard: llamaGuard, xguard, netease_yidun: yidunGuard, evidence } = detail;
  const translated = Boolean(state.finvaultTranslated && translation?.available);
  const displaySource = translated ? {
    ...source,
    description: translation.description || source.description,
    attack_prompt: translation.attack_prompt || source.attack_prompt,
    follow_up_prompts: translation.follow_up_prompts?.length ? translation.follow_up_prompts : source.follow_up_prompts,
  } : source;
  const isNormal = caseRow.dataset_type === "normal";
  const queryTurns = [displaySource.attack_prompt, ...(displaySource.follow_up_prompts || [])].filter(Boolean);
  const displaySystemPrompt = translated
    ? systemPrompt?.translation || systemPrompt?.content
    : systemPrompt?.content;
  const evidenceRows = Object.entries(evidence).map(([key, value]) => `
    <div class="evidence-item"><span>${escapeHtml(formatName(key))}</span><span class="evidence-value">${escapeHtml(value || "n/a")}</span></div>
  `).join("");
  const successCondition = Object.keys(source.success_condition || {}).length
    ? prettyJson(source.success_condition)
    : source.vulnerable_behavior;
  const context = Object.keys(source.context || {}).length ? prettyJson(source.context) : "未提供额外上下文";
  const executionTrace = evaluation.status === "complete" ? prettyJson(evaluation.turns || []) : "xx（待运行后回填）";
  const traceSteps = (evaluation.turns || []).map(renderFinVaultTraceStep).join("");
  const status = finvaultStatusView(caseRow.evaluation_status, isNormal);
  const defenseSummary = renderFinVaultDefenseSummary({ activationProbe, suffixProbe, queryGuard, llamaGuard, xguard, yidunGuard, evaluation });
  const roundFlow = renderFinVaultRoundFlow({ queryTurns, isNormal, activationProbe, suffixProbe, queryGuard, llamaGuard, xguard, yidunGuard, evaluation });
  elements.traceDetail.innerHTML = `
    <header class="trace-detail-header finvault-detail-header">
      <div>
        <p class="eyebrow">FinVault 案例 #${String(caseRow.sample_index + 1).padStart(4, "0")} · ${escapeHtml(caseRow.dataset_name)} · 沙盒 ${escapeHtml(caseRow.scenario_id)}</p>
        <h3>${escapeHtml(caseRow.scenario_name)}</h3>
        <p class="case-summary">${escapeHtml(displaySource.description || caseRow.attack)}</p>
      </div>
      <div class="finvault-detail-actions">
        ${translation?.available && systemPrompt?.available ? `<button class="query-translation-button ${translated ? "active" : ""}" data-finvault-translate type="button">${translated ? "原文" : "翻译"}</button>` : ""}
        <span class="finvault-case-status ${status.tone}"><i></i>${evaluation.status === "complete" ? escapeHtml(status.label) : `${escapeHtml(evaluation.model || auditModelLabel())} 待运行`}</span>
      </div>
    </header>

    <div class="trace-meta-chips">
      <span class="audit-chip">${escapeHtml(displaySuite(caseRow.suite))}</span>
      ${caseRow.risk_names.map((name) => `<span class="audit-chip">${escapeHtml(name)}</span>`).join("")}
      <span class="audit-chip">${escapeHtml(caseRow.attack_technique)}</span>
      <span class="audit-chip">${escapeHtml(caseRow.risk_subtypes.join(" / "))}</span>
      <span class="audit-chip">漏洞 ${escapeHtml(caseRow.vulnerability)}</span>
      <span class="audit-chip">${isNormal ? "正常业务流程" : source.multi_turn ? "多轮攻击" : "单轮攻击"}</span>
    </div>

    <section class="trace-section finvault-system-prompt-section">
      <div class="trace-section-heading">
        <h4>系统提示词</h4>
        <span class="audit-note">${systemPrompt?.test_mode === "base" ? "实验使用的基础提示词" : escapeHtml(systemPrompt?.test_mode || "")}</span>
      </div>
      ${displaySystemPrompt
        ? `<pre lang="${translated ? "zh-CN" : "en"}">${escapeHtml(displaySystemPrompt)}</pre>`
        : `<div class="trace-empty">未载入该沙盒的系统提示词</div>`}
    </section>

    <section class="trace-section prompt-query-section">
      <div class="trace-section-heading">
        <h4>${isNormal ? "正常用户输入" : "攻击者输入"}${queryTurns.length > 1 ? ` · ${queryTurns.length} 轮` : ""}</h4>
      </div>
      <div class="prompt-turn-list">
        ${queryTurns.length ? queryTurns.map((prompt, index) => `
          <article class="prompt-turn-item">
            ${queryTurns.length > 1 ? `<span>第 ${index + 1} 轮</span>` : ""}
            <blockquote lang="${translated ? "zh-CN" : "en"}">${escapeHtml(prompt)}</blockquote>
          </article>
        `).join("") : "<blockquote>未记录输入</blockquote>"}
      </div>
    </section>

    <section class="trace-section finvault-defense-section">
      <div class="trace-section-heading"><h4>执行前 Query 防御</h4><span class="audit-note">紧凑对比</span></div>
      ${defenseSummary}
      ${(queryGuard?.raw_output || llamaGuard?.raw_output || xguard?.status === "complete" || yidunGuard?.raw_output) ? `
        <details class="guard-raw-output finvault-guard-raw"><summary>查看防御方法原始输出</summary>
          <div class="finvault-guard-raw-grid">
            ${queryGuard?.raw_output ? `<article><strong>Qwen3Guard</strong><pre>${escapeHtml(queryGuard.raw_output)}</pre></article>` : ""}
            ${llamaGuard?.raw_output ? `<article><strong>Llama Prompt Guard 2</strong><pre>${escapeHtml(llamaGuard.raw_output)}</pre></article>` : ""}
            ${xguard?.status === "complete" ? `<article><strong>YuFeng-XGuard</strong><pre>${escapeHtml(prettyJson({ category: xguard.category, risk_probability: xguard.risk_probability, top_categories: xguard.top_categories }))}</pre></article>` : ""}
            ${yidunGuard?.raw_output ? `<article><strong>网易易盾</strong><pre>${escapeHtml(yidunGuard.raw_output)}</pre></article>` : ""}
          </div>
        </details>` : ""}
    </section>

    <section class="trace-section finvault-flow-section">
      <div class="trace-section-heading"><div><h4>逐轮安全执行流</h4><p>用户输入 → 本轮检测 / 累计检出 → Agent 工具调用</p></div><span class="audit-note">${queryTurns.length} 个用户轮次</span></div>
      ${roundFlow}
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>风险审计规则</h4></div>
      <div class="finvault-rule-grid">
        <article class="finvault-rule-card safe"><span>期望安全行为</span><p>${escapeHtml(source.expected_safe_behavior)}</p></article>
        <article class="finvault-rule-card danger"><span>${isNormal ? "任务失败条件" : "攻击成功条件"}</span><pre>${escapeHtml(successCondition)}</pre></article>
      </div>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>${escapeHtml(evaluation.model || auditModelLabel())} 执行结果</h4><span class="audit-note">${evaluation.status === "complete" ? "已从报告载入" : "尚未生成结果文件"}</span></div>
      <div class="finvault-result-grid">
        ${isNormal ? finvaultResultCell("正常任务是否通过", evaluation.normal_pass) : finvaultResultCell("攻击是否成功", evaluation.attack_success)}
        ${finvaultResultCell("最终决策", evaluation.final_decision)}
        ${finvaultResultCell("安全得分", evaluation.total_reward)}
        ${finvaultResultCell("触发漏洞", evaluation.vulnerabilities_triggered)}
        ${finvaultResultCell("流程违规", evaluation.violations)}
        ${finvaultResultCell("工具调用", evaluation.tool_calls)}
      </div>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><div><h4>完整 Agent Trace</h4><p>逐步查看模型输入、工具参数、Sandbox 返回与漏洞触发证据</p></div><span>${evaluation.turns?.length || 0} 步</span></div>
      <div class="finvault-agent-trace">${traceSteps || `<div class="trace-empty">待运行 ${escapeHtml(evaluation.model || auditModelLabel())} 后生成完整轨迹</div>`}</div>
    </section>

    <details class="technical-evidence">
      <summary><span>基准上下文与技术证据</span></summary>
      <div class="technical-evidence-body">
        <div class="evidence-grid">${evidenceRows}</div>
        <h4>沙盒初始上下文</h4>
        <pre>${escapeHtml(context)}</pre>
        <h4>模型动作与沙盒奖励轨迹</h4>
        <pre>${escapeHtml(executionTrace)}</pre>
      </div>
    </details>
  `;
}

function renderFinVaultTraceStep(turn, index) {
  const action = turn.parsed_action || parseToolArguments(turn.action);
  const toolName = action?.tool || "未知动作";
  const vulnerabilities = turn.vulnerabilities || turn.environment_info?.vulnerabilities_triggered || [];
  const environmentOutput = typeof turn.environment_observation === "string"
    ? turn.environment_observation
    : prettyJson(turn.environment_observation || {});
  return `
    <article class="finvault-trace-step ${vulnerabilities.length ? "danger" : ""}">
      <header>
        <span class="finvault-step-index">${index + 1}</span>
        <div><strong>${escapeHtml(toolName)}</strong><small>第 ${turn.multi_turn || 1} 轮 · 交互 ${turn.interaction || index + 1}</small></div>
        <span class="finvault-reward ${Number(turn.reward || 0) < 0 ? "negative" : ""}">奖励 ${escapeHtml(turn.reward ?? "xx")}</span>
      </header>
      <div class="finvault-trace-flow">
        <details>
          <summary>模型输入</summary>
          <pre>${escapeHtml(turn.model_input || prettyJson(turn.observation || {}))}</pre>
        </details>
        <div class="finvault-trace-stage action">
          <span>工具调用</span>
          <pre>${escapeHtml(prettyJson(action || {}))}</pre>
        </div>
        <div class="finvault-trace-stage sandbox">
          <span>Sandbox 返回</span>
          <pre>${escapeHtml(environmentOutput)}</pre>
        </div>
      </div>
      ${vulnerabilities.length ? `<footer><strong>触发漏洞</strong><span>${escapeHtml(vulnerabilities.join("、"))}</span></footer>` : ""}
    </article>`;
}

function finvaultResultCell(label, value) {
  const hasValue = value !== null && value !== undefined;
  const display = hasValue
    ? Array.isArray(value) ? value.join("、") || "无" : typeof value === "object" ? prettyJson(value) : String(value)
    : "xx";
  const compact = label === "触发漏洞" || display.length > 36;
  return `<article class="finvault-result-cell ${hasValue ? "ready" : "pending"} ${compact ? "compact-value" : ""}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(display)}</strong></article>`;
}

function finvaultStatusView(status, isNormal = false) {
  if (status === "unsafe") return { label: isNormal ? "正常任务失败" : "攻击成功", tone: "danger" };
  if (status === "safe") return { label: isNormal ? "正常任务通过" : "安全处置", tone: "safe" };
  return { label: "待运行", tone: "pending" };
}

function renderPromptExtractionDetail(detail) {
  const { case: caseRow, guard_results: guardResults, evidence, prompt_extraction: extraction } = detail;
  const example = extraction.example || {};
  const probeEvaluation = extraction.probe_evaluation || {};
  const metric = example.metrics || {};
  const baselineLeakCount = Number(guardResults.no_guard?.attack_success_count || 0);
  const resultCards = activeGuards().map((guard) => {
    const row = guardResults[guard];
    const leakedCount = Number(row.attack_success_count || 0);
    const total = Number(row.total || extraction.system_prompt_count || 0);
    const defendedCount = Math.max(0, baselineLeakCount - leakedCount);
    const percent = baselineLeakCount ? Math.round((defendedCount / baselineLeakCount) * 100) : 0;
    const isBaseline = guard === "no_guard";
    const isActivationProbe = guard === "activation_probe";
    const splitLabel = probeEvaluation.split === "test" ? "独立测试集" : probeEvaluation.split === "val" ? "验证集" : probeEvaluation.split === "train" ? "训练集" : "全量案例";
    const guardNote = isBaseline
      ? "该泄露数是其他方案防御成功率的分母"
      : isActivationProbe
        ? `${extraction.probe_model_label || auditModelLabel()} · ${splitLabel} · ${row.detected_count}/${total} 个条件样本检出`
      : row.detected
        ? `已拦截该 Query，检出 ${row.detected_count}/${total} 次`
        : baselineLeakCount ? "未检出该攻击 Query" : "No Guard 未泄露，不纳入防御率统计";
    return `
      <article class="prompt-guard-card ${isBaseline || leakedCount ? "leaked" : "safe"}">
        <span>${escapeHtml(isActivationProbe ? `${GUARD_NAMES[guard]} · ${extraction.probe_model_label || auditModelLabel()}` : GUARD_NAMES[guard])}</span>
        <strong>${isBaseline ? `${baselineLeakCount} / ${total}` : baselineLeakCount ? `${defendedCount} / ${baselineLeakCount}` : "—"}</strong>
        <b>${isBaseline ? "基线泄露" : baselineLeakCount ? `${percent}% 防御成功` : "不纳入统计"}</b>
        <small>${escapeHtml(guardNote)}</small>
      </article>`;
  }).join("");
  const evidenceRows = Object.entries(evidence).map(([key, value]) => `
    <div class="evidence-item"><span>${escapeHtml(formatName(key))}</span><span class="evidence-value">${escapeHtml(value || "n/a")}</span></div>
  `).join("");
  const rawDetectorOutput = Object.fromEntries(activeGuards().map((guard) => [
    GUARD_NAMES[guard],
    guardResults[guard].raw_output || null,
  ]));

  elements.traceDetail.innerHTML = `
    <header class="trace-detail-header">
      <div>
        <p class="eyebrow">攻击 Query #${String(caseRow.sample_index).padStart(2, "0")} · ${escapeHtml(extraction.probe_model_label || auditModelLabel())}</p>
        <h3>${escapeHtml(caseRow.attack_category)} · ${escapeHtml(caseRow.attack_prompt_name)}</h3>
      </div>
    </header>

    <section class="trace-section prompt-query-section">
      <div class="trace-section-heading"><h4>送入模型和护栏的 Attack Query</h4></div>
      <blockquote>${escapeHtml(extraction.attack_prompt)}</blockquote>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>在 ${extraction.system_prompt_count} 个 System Prompt 上的聚合结果</h4></div>
      <div class="prompt-guard-grid">${resultCards}</div>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>${example.attack_success ? "一条成功偷取示例" : "一条模型响应示例"}</h4></div>
      <article class="prompt-example-card">
        <div><span>业务助手</span><strong>${escapeHtml(example.system_name || "未知")}</strong></div>
        <div><span>ROUGE-L Recall</span><strong>${Math.round(Number(metric.rouge_l_recall || 0) * 100)}%</strong></div>
        <p>${escapeHtml(visibleModelAnswer(example.response || "未记录模型响应"))}</p>
      </article>
    </section>

    <details class="technical-evidence">
      <summary><span>技术审计证据</span></summary>
      <div class="technical-evidence-body">
        <div class="evidence-grid">${evidenceRows}</div>
        <h4>检测器原始输出</h4>
        <pre>${escapeHtml(prettyJson(rawDetectorOutput))}</pre>
      </div>
    </details>`;
}

function renderDetectorCard(guard, row) {
  const detected = row.detected === true;
  const isBaseline = guard === "no_guard";
  const verdict = isBaseline ? "未配置检测" : detected ? "已预警" : "未预警";
  const explanation = detectorExplanation(guard, row);
  return `
    <article class="detector-detail-card ${detected ? "hit" : ""} ${isBaseline ? "baseline" : ""}">
      <div class="detector-detail-head">
        <strong>${escapeHtml(GUARD_NAMES[guard])}</strong>
        <span class="detector-verdict">${verdict}</span>
      </div>
      <p class="detector-explanation">${escapeHtml(explanation)}</p>
    </article>`;
}

function renderStoryMessage(message) {
  if (message.is_injection) {
    return `
      <article class="story-event danger">
        <span class="story-marker">!</span>
        <div class="story-event-body"><strong>外部数据中出现恶意指令</strong><p>${escapeHtml(message.content)}</p></div>
      </article>`;
  }
  if (message.role === "user") {
    return `
      <article class="story-event user">
        <span class="story-marker">人</span>
        <div class="story-event-body"><strong>客户提出请求</strong><p>${escapeHtml(message.content)}</p></div>
      </article>`;
  }
  if (message.role === "assistant") {
    const calls = (message.tool_calls || []).map(renderToolCall).join("");
    const text = message.content ? `<p>${escapeHtml(message.content)}</p>` : "";
    return `
      <article class="story-event assistant">
        <span class="story-marker">AI</span>
        <div class="story-event-body"><strong>AI 助手采取行动</strong>${text}${calls || "<p>助手准备继续处理任务。</p>"}</div>
      </article>`;
  }
  if (message.role === "tool") {
    return `
      <article class="story-event tool">
        <span class="story-marker">↳</span>
        <div class="story-event-body">
          <strong>业务系统返回结果</strong>
          <details class="business-response"><summary>查看返回内容</summary><p>${escapeHtml(message.content || "业务系统没有返回文本内容")}</p></details>
        </div>
      </article>`;
  }
  return "";
}

function renderToolCall(call) {
  const fn = call?.function || {};
  const args = parseToolArguments(fn.arguments);
  return `<div class="business-action"><span>调用业务能力</span><strong>${escapeHtml(toolActionLabel(fn.name, args))}</strong></div>`;
}

function parseToolArguments(value) {
  if (!value) return {};
  try { return typeof value === "string" ? JSON.parse(value) : value; } catch { return {}; }
}

function toolActionLabel(name, args) {
  const count = (key, noun) => Array.isArray(args[key]) ? `查看 ${args[key].length} 家${noun}` : null;
  const labels = {
    get_all_restaurants_in_city: () => `查询 ${args.city || "目标城市"} 的餐厅`,
    get_cuisine_type_for_restaurants: () => count("restaurant_names", "餐厅的菜系") || "核对餐厅菜系",
    get_rating_reviews_for_restaurants: () => count("restaurant_names", "餐厅的评分和评价") || "查看餐厅评价",
    check_restaurant_opening_hours: () => count("restaurant_names", "餐厅的营业时间") || "核对餐厅营业时间",
    get_price_for_restaurants: () => count("restaurant_names", "餐厅的价格") || "查询餐厅价格",
    get_restaurants_address: () => count("restaurant_names", "餐厅的地址") || "查询餐厅地址",
    get_all_hotels_in_city: () => `查询 ${args.city || "目标城市"} 的酒店`,
    get_hotels_prices: () => count("hotel_names", "酒店的价格") || "查询酒店价格",
    get_rating_reviews_for_hotels: () => count("hotel_names", "酒店的评分和评价") || "查看酒店评价",
    get_hotels_address: () => count("hotel_names", "酒店的地址") || "查询酒店地址",
    reserve_hotel: () => `预订 ${args.hotel || "酒店"}${args.start_day ? `，入住 ${args.start_day}` : ""}${args.end_day ? ` 至 ${args.end_day}` : ""}`,
    get_all_car_rental_companies_in_city: () => `查询 ${args.city || "目标城市"} 的租车公司`,
    get_car_price_per_day: () => "查询租车每日价格",
    get_rating_reviews_for_car_rental: () => "查看租车公司评分和评价",
    get_most_recent_transactions: () => `读取最近 ${args.n || "若干"} 笔交易`,
    get_scheduled_transactions: () => "查看计划交易",
    get_iban: () => "查询本人银行账号",
    send_money: () => `向 ${args.recipient || "指定收款人"} 转账 ${args.amount ?? "指定金额"}`,
    schedule_transaction: () => `创建向 ${args.recipient || "指定收款人"} 的计划交易`,
    update_scheduled_transaction: () => `修改编号 ${args.id ?? "未知"} 的计划交易`,
    get_user_information: () => "读取用户个人信息",
    update_user_info: () => `修改用户资料：${Object.keys(args).join("、") || "指定字段"}`,
    update_password: () => "修改用户账户密码",
    read_file: () => `读取文件 ${args.file_path || args.path || ""}`,
    send_email: () => `向 ${args.recipients || args.recipient || "指定收件人"} 发送邮件`,
  };
  if (labels[name]) return labels[name]();
  return `执行“${formatName(name || "未知业务操作")}”`;
}

function detectorExplanation(guard, row) {
  if (guard === "activation_probe") {
    const score = row.score == null ? null : Math.round(Number(row.score) * 100);
    const thresholdValue = row.probability_threshold == null ? sigmoid(Number(row.threshold)) : Number(row.probability_threshold);
    const threshold = Number.isFinite(thresholdValue) ? Math.round(thresholdValue * 100) : null;
    return score == null ? `通过 ${auditModelLabel()} 内部激活判断攻击意图。` : `${auditModelLabel()} 内部激活风险为 ${score}%，预警线为 ${threshold}%。`;
  }
  if (guard === "inline_probing") {
    const score = row.score == null ? null : Math.round(Number(row.score) * 100);
    const threshold = row.threshold == null ? null : Math.round(Number(row.threshold) * 100);
    return score == null ? "通过 AI 内部风险信号判断。" : `AI 内部风险信号为 ${score}%，预警线为 ${threshold}%。`;
  }
  if (guard === "llama_prompt_guard") {
    const score = row.score == null ? null : Math.round(Number(row.score) * 100);
    const threshold = row.threshold == null ? null : Math.round(Number(row.threshold) * 100);
    return score == null ? "通过 Llama Prompt Guard 2 判断提示攻击意图。" : `提示攻击概率为 ${score}%，预警线为 ${threshold}%。`;
  }
  if (guard === "qwen3_guard") return row.detected ? "文本安全模型认为完整工具返回包含攻击风险。" : "文本安全模型没有在完整工具返回中识别出攻击。";
  if (guard === "netease_yidun") return row.detected ? "云端内容安全服务对完整工具返回给出了风险处置建议。" : "云端内容安全服务未在完整工具返回中给出风险提示。";
  return "作为无护栏对照组，本方案不会主动识别或预警风险。";
}

function sigmoid(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return NaN;
  return 1 / (1 + Math.exp(-number));
}

function formatPercentPrecise(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "待训练";
}

function behaviorPresentation(label) {
  const values = {
    followed_injection: { label: "跟随了恶意指令", tone: "danger" },
    resisted_injection: { label: "识别并抵抗", tone: "success" },
    continued_user_task: { label: "继续原用户任务", tone: "neutral" },
    ambiguous: { label: "无法可靠判断", tone: "muted" },
  };
  return values[label] || values.ambiguous;
}

function visibleModelAnswer(content) {
  return String(content || "").replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
}

function settingScore(detected, samples) {
  if (!samples) return `<span class="setting-score">—</span>`;
  const className = detected === samples ? "full" : detected > 0 ? "partial" : "";
  return `<span class="setting-score ${className}">${detected} / ${samples}</span>`;
}

function pendingScore() {
  return `<span class="setting-score pending" title="待 Qwen3-8B 运行后回填">xx</span>`;
}

function notEvaluatedScore() {
  return `<span class="setting-score pending" title="该子类尚未运行此防御方法">待评测</span>`;
}

function settingValue(value, tone) {
  return `<span class="setting-score ${escapeAttribute(tone)}">${escapeHtml(value)}</span>`;
}

function setRuntime(status, text) {
  if (!elements.runtime) return;
  elements.runtime.className = `audit-runtime ${status}`;
  elements.runtime.innerHTML = `<span class="status-dot"></span><span>${escapeHtml(text)}</span>`;
}

function renderError(message) {
  return `<div class="trace-detail-placeholder"><p>无法加载审计数据</p><p class="error-detail">${escapeHtml(message)}</p></div>`;
}

function formatProbeSplit(value) {
  if (value === "test") return "独立测试集";
  if (value === "val") return "验证集";
  if (value === "train") return "训练集";
  return "未标注";
}

function formatName(value) {
  return String(value ?? "").replaceAll("_", " ");
}

function displaySuite(value) {
  return SUITE_NAMES[value] ?? formatName(value);
}

function displayAttack(value) {
  return ATTACK_NAMES[value] ?? formatName(value);
}

function displayPolicy(value) {
  return POLICY_NAMES[value] ?? formatName(value);
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
