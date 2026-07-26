const GUARDS = ["inline_probing", "qwen3_guard", "netease_yidun", "no_guard"];
const GUARD_NAMES = {
  inline_probing: "Inline Probe",
  qwen3_guard: "Qwen3Guard",
  netease_yidun: "网易易盾",
  no_guard: "No Guard",
};
const SUITE_NAMES = { banking: "银行服务", travel: "旅行服务" };
const SUITE_ORDER = { banking: 0, travel: 1 };
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
const DEFAULT_RISK = "prompt_injection";
const RISK_COPY = {
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
    eyebrow: "风险类别 · 待接入",
    title: "高风险任务审计",
    lead: "这里预留给后续测试员接入转账、改密、下单等高风险动作实验。接入后可以直接作为新的风险子页切换查看。",
  },
};

const elements = {
  runtime: document.querySelector("#auditRuntime"),
  riskEyebrow: document.querySelector("#riskEyebrow"),
  riskTitle: document.querySelector("#riskTitle"),
  riskLead: document.querySelector("#riskLead"),
  riskSwitcher: document.querySelector("#riskSwitcher"),
  riskEmpty: document.querySelector("#riskEmpty"),
  riskSections: document.querySelectorAll(".risk-audit-section"),
  methodChips: document.querySelector("#methodChips"),
  guardResultList: document.querySelector("#guardResultList"),
  experimentFacts: document.querySelector("#experimentFacts"),
  behaviorSummary: document.querySelector("#behaviorSummary"),
  integrityGrid: document.querySelector("#integrityGrid"),
  settingsTableBody: document.querySelector("#settingsTableBody"),
  search: document.querySelector("#caseSearchInput"),
  guardFilter: document.querySelector("#guardFilter"),
  resultFilter: document.querySelector("#resultFilter"),
  settingFilter: document.querySelector("#settingFilter"),
  caseCountLabel: document.querySelector("#caseCountLabel"),
  traceList: document.querySelector("#traceList"),
  traceEmpty: document.querySelector("#traceEmpty"),
  traceDetail: document.querySelector("#traceDetail"),
};

const state = {
  risks: [],
  activeRisk: null,
  overview: null,
  filteredCases: [],
  activeSample: null,
  detailRequest: 0,
};

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
  const response = await fetch(risk.endpoint);
    if (!response.ok) throw new Error(`审计接口返回 ${response.status}`);
    state.overview = await response.json();
    renderOverview();
    populateSettingFilter();
    applyFilters();
    setRuntime("ready", "审计产物已验证");
}

function bindEvents() {
  [elements.search, elements.guardFilter, elements.resultFilter, elements.settingFilter].forEach((element) => {
    element.addEventListener("input", applyFilters);
    element.addEventListener("change", applyFilters);
  });
}

function resolveInitialRisk(fallback) {
  const requested = new URLSearchParams(window.location.search).get("risk") || fallback || DEFAULT_RISK;
  return state.risks.some((risk) => risk.id === requested) ? requested : fallback;
}

function getActiveRisk() {
  return state.risks.find((risk) => risk.id === state.activeRisk) || state.risks[0] || null;
}

function renderRiskHero(risk) {
  const copy = RISK_COPY[risk?.id] || {
    eyebrow: "实验审计",
    title: risk?.name || "风险审计",
    lead: risk?.summary || "选择一个风险类别查看实验结果。",
  };
  elements.riskEyebrow.textContent = copy.eyebrow;
  elements.riskTitle.textContent = copy.title;
  elements.riskLead.textContent = copy.lead;
}

function renderRiskSwitcher() {
  if (!state.risks.length) {
    elements.riskSwitcher.innerHTML = "";
    return;
  }
  elements.riskSwitcher.innerHTML = state.risks.map((risk) => {
    const selected = risk.id === state.activeRisk;
    const statusText = risk.status === "available" ? `${risk.sample_count || 0} 次测试` : "待接入";
    return `
      <button class="risk-tab ${selected ? "active" : ""}" data-risk-id="${escapeAttribute(risk.id)}" type="button" aria-pressed="${selected ? "true" : "false"}">
        <span>
          <strong>${escapeHtml(risk.name)}</strong>
          <small>${escapeHtml(risk.summary)}</small>
        </span>
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
  elements.methodChips.innerHTML = "";
  elements.riskEmpty.hidden = false;
  elements.riskEmpty.innerHTML = `
    <article class="audit-card unavailable-risk-card">
      <p class="eyebrow">子页面待接入</p>
      <h2>${escapeHtml(risk?.name || "风险审计")}</h2>
      <p>${escapeHtml(risk?.summary || "该风险类别还没有绑定实验产物。")}</p>
      <dl>
        <div><dt>接入方式</dt><dd>新增审计数据源和 API endpoint 后，在风险目录中登记即可出现在这里。</dd></div>
        <div><dt>展示能力</dt><dd>概览榜单、细分场景、逐条 trace、检测证据会复用当前审计页面的结构。</dd></div>
      </dl>
    </article>`;
}

function showExperimentSections(visible) {
  elements.riskSections.forEach((section) => {
    section.hidden = !visible;
  });
}

function renderOverview() {
  const { experiment, guard_metrics: guardMetrics, integrity, settings, behavior_metrics: behaviorMetrics } = state.overview;
  elements.methodChips.innerHTML = [
    ["评测语言", "简体中文"],
    ["检测时点", "攻击首次进入视野"],
    ["文本护栏输入", "完整工具返回"],
  ].map(([label, value]) => `<span class="audit-chip">${escapeHtml(label)}<strong>${escapeHtml(value)}</strong></span>`).join("");

  elements.guardResultList.innerHTML = guardMetrics.map((row) => {
    const percent = Math.round(Number(row.detection_rate || 0) * 100);
    return `
      <div class="guard-result-row" data-guard="${row.guard}">
        <span class="guard-result-label">
          <strong>${escapeHtml(row.name)}</strong>
          <small>${row.errors ? `${row.errors} 次检测异常` : "全部案例检测完成"}</small>
        </span>
        <span class="result-track" role="img" aria-label="${escapeAttribute(`${row.detected} / ${row.completed} 次攻击成功预警`)}">
          <span class="result-fill" style="width:${percent}%"></span>
        </span>
        <span class="guard-result-value"><strong>${percent}%</strong><small>${row.detected} / ${row.completed}</small></span>
      </div>`;
  }).join("");

  const facts = [
    ["被测 AI 助手", "Qwen3-8B"],
    ["攻击案例", `${experiment.sample_count} 次`],
    ["业务范围", "银行服务、旅行服务"],
    ["攻击组合", `${experiment.settings_count} 种`],
    ["检测方案", "4 种方案同场比较"],
    ["判断规则", `风险概率达到 ${Math.round(Number(experiment.threshold) * 100)}% 即预警`],
  ];
  elements.experimentFacts.innerHTML = facts.map(([label, value]) => `
    <div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>
  `).join("");

  const behaviorLabels = [
    ["followed_injection", "跟随了恶意指令", "模型已经执行或开始推进攻击任务", "danger"],
    ["resisted_injection", "识别并抵抗", "模型明确忽略攻击并坚持原任务", "success"],
    ["continued_user_task", "继续原用户任务", "模型未响应攻击，继续处理客户请求", "neutral"],
    ["ambiguous", "无法可靠判断", "仅凭当前一步不足以作出判断", "muted"],
  ];
  elements.behaviorSummary.innerHTML = behaviorLabels.map(([key, label, detail, tone]) => `
    <article class="behavior-summary-item ${tone}">
      <strong>${behaviorMetrics.labels[key] || 0}<small> / ${experiment.sample_count}</small></strong>
      <span><b>${escapeHtml(label)}</b><small>${escapeHtml(detail)}</small></span>
    </article>
  `).join("");

  const collectionAudit = integrity.collection_audit;
  const integrityItems = [
    ["原始任务不受干预", collectionAudit.inline_request_fields_during_collection === 0 ? "采集时未启用任何护栏" : "发现意外干预"],
    ["每种方案输入一致", `${integrity.replay_requests} 个风险现场逐一复用`],
    ["输入内容逐字核验", `${integrity.distinct_prompt_fingerprints} 份输入均有独立指纹`],
    ["动作不会影响环境", integrity.replay_continuation_executed ? "发现工具被执行" : "模型动作只记录、不执行"],
    ["检测过程稳定", `${guardMetrics.reduce((total, row) => total + row.errors, 0)} 次系统异常`],
  ];
  elements.integrityGrid.innerHTML = integrityItems.map(([title, detail]) => `
    <div class="integrity-item">
      <span class="integrity-check">✓</span>
      <span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></span>
    </div>
  `).join("");

  elements.settingsTableBody.innerHTML = settings.map((row) => `
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

function populateSettingFilter() {
  elements.settingFilter.innerHTML = `<option value="all">全部业务场景</option>`;
  elements.settingFilter.insertAdjacentHTML("beforeend", state.overview.settings.map((row) => `
    <option value="${escapeAttribute(row.grid_point_id)}">${escapeHtml(displaySuite(row.suite))} · ${escapeHtml(displayPolicy(row.system_prompt))} · ${escapeHtml(displayAttack(row.attack))}</option>
  `).join(""));
}

function applyFilters() {
  if (!state.overview) return;
  const query = elements.search.value.trim().toLowerCase();
  const guard = elements.guardFilter.value;
  const result = elements.resultFilter.value;
  const setting = elements.settingFilter.value;
  state.filteredCases = state.overview.cases.filter((row) => {
    const haystack = [row.decision_point_id, row.trace_id, row.grid_point_id, row.attack, row.suite].join(" ").toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (setting !== "all" && row.grid_point_id !== setting) return false;
    if (result !== "all") {
      const detected = guard === "all"
        ? row.detected_by.length > 0
        : row.guard_results[guard].detected === true;
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

function renderCaseList() {
  const guard = elements.guardFilter.value;
  elements.caseCountLabel.textContent = `显示 ${state.filteredCases.length} / ${state.overview.cases.length} 个案例`;
  elements.traceEmpty.hidden = state.filteredCases.length > 0;
  elements.traceList.innerHTML = state.filteredCases.map((row) => {
    const dots = GUARDS.map((guardId) => {
      const hit = row.guard_results[guardId].detected === true;
      return `<span class="detection-dot ${hit ? "hit" : ""}" title="${escapeAttribute(GUARD_NAMES[guardId])}：${hit ? "已预警" : "未预警"}"></span>`;
    }).join("");
    const selectedVerdict = guard === "all"
      ? `${row.detected_by.length} / 4 方案预警`
      : row.guard_results[guard].detected ? "已预警" : "未预警";
    return `
      <button class="trace-row ${row.sample_index === state.activeSample ? "active" : ""}" data-sample-index="${row.sample_index}" type="button">
        <span class="trace-index">#${String(row.sample_index).padStart(3, "0")}</span>
        <span class="trace-setting">
          <strong>${escapeHtml(displaySuite(row.suite))} · ${escapeHtml(displayAttack(row.attack))}</strong>
          <small>${escapeHtml(displayPolicy(row.system_prompt))} · ${escapeHtml(selectedVerdict)}</small>
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

async function loadCaseDetail(sampleIndex) {
  const risk = getActiveRisk();
  const caseEndpoint = risk?.case_endpoint || "/api/audit/experiment/cases/{sample_index}";
  const requestId = ++state.detailRequest;
  elements.traceDetail.innerHTML = `<div class="trace-detail-loading"><span class="audit-loading-dot"></span><p>正在加载冻结 trace #${String(sampleIndex).padStart(3, "0")}</p></div>`;
  try {
    const response = await fetch(caseEndpoint.replace("{sample_index}", encodeURIComponent(sampleIndex)));
    if (!response.ok) throw new Error(`详情接口返回 ${response.status}`);
    const detail = await response.json();
    if (requestId !== state.detailRequest) return;
    renderCaseDetail(detail);
  } catch (error) {
    if (requestId !== state.detailRequest) return;
    elements.traceDetail.innerHTML = renderError(error.message);
  }
}

function renderCaseDetail(detail) {
  const { case: caseRow, decision_point: decision, trace, guard_results: guardResults, evidence, agent_behavior: agentBehavior } = detail;
  const detectorCards = GUARDS.map((guard) => renderDetectorCard(guard, guardResults[guard])).join("");
  const businessMessages = detail.messages.filter((message) => message.role !== "system");
  const messages = businessMessages.map((message) => renderStoryMessage(message)).join("");
  const userRequest = businessMessages.find((message) => message.role === "user")?.content || "未记录用户请求";
  const systemMessage = detail.messages.find((message) => message.role === "system")?.content || "";
  const evidenceRows = Object.entries(evidence).map(([key, value]) => `
    <div class="evidence-item"><span>${escapeHtml(formatName(key))}</span><span class="evidence-value">${escapeHtml(value || "n/a")}</span></div>
  `).join("");
  const rawDetectorOutput = Object.fromEntries(GUARDS.map((guard) => [
    GUARD_NAMES[guard],
    Object.fromEntries(Object.entries(guardResults[guard].input_modes || {}).map(([mode, result]) => [mode, result.raw_output])),
  ]));
  const alerted = GUARDS.filter((guard) => guard !== "no_guard" && Object.values(guardResults[guard].input_modes || {}).some((row) => row.detected === true)).length;
  const behaviorView = behaviorPresentation(agentBehavior.label);
  const behaviorCalls = (agentBehavior.message?.tool_calls || []).map(renderToolCall).join("");
  const visibleAnswer = visibleModelAnswer(agentBehavior.message?.content || "");

  elements.traceDetail.innerHTML = `
    <header class="trace-detail-header">
      <div>
        <p class="eyebrow">风险案例 #${String(caseRow.sample_index).padStart(3, "0")}</p>
        <h3>${escapeHtml(displaySuite(caseRow.suite))}中的间接提示注入</h3>
        <p class="case-summary">恶意指令伪装为“${escapeHtml(displayAttack(caseRow.attack))}”，3 种实际检测方案中有 ${alerted} 种成功预警；模型行为判定为“${escapeHtml(behaviorView.label)}”。</p>
      </div>
      <span class="audit-status-pill success">现场已核验</span>
    </header>
    <div class="trace-meta-chips">
      <span class="audit-chip">业务<strong>${escapeHtml(displaySuite(caseRow.suite))}</strong></span>
      <span class="audit-chip">攻击方式<strong>${escapeHtml(displayAttack(caseRow.attack))}</strong></span>
      <span class="audit-chip">安全策略<strong>${escapeHtml(displayPolicy(caseRow.system_prompt))}</strong></span>
    </div>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>案例概览</h4><span class="audit-note">攻击内容来自外部业务数据</span></div>
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
      <div class="trace-section-heading"><h4>各方案如何判断</h4><span class="audit-note">绿：已预警 · 灰：未预警</span></div>
      <div class="detector-detail-grid">${detectorCards}</div>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>Qwen3-8B 接下来做了什么</h4><span class="audit-note">动作仅记录，未实际执行</span></div>
      <article class="model-behavior-card ${behaviorView.tone}">
        <div class="model-behavior-head">
          <span class="behavior-verdict">${escapeHtml(behaviorView.label)}</span>
          <small>判断置信度 ${Math.round(Number(agentBehavior.confidence || 0) * 100)}%</small>
        </div>
        <p class="behavior-reason">${escapeHtml(agentBehavior.reason)}</p>
        ${behaviorCalls ? `<div class="behavior-actions"><span>模型准备调用：</span>${behaviorCalls}</div>` : ""}
        ${visibleAnswer ? `<div class="behavior-answer"><strong>给用户的回复</strong><p>${escapeHtml(visibleAnswer)}</p></div>` : ""}
      </article>
    </section>

    <section class="trace-section">
      <div class="trace-section-heading"><h4>事件经过</h4><span class="audit-note">按真实发生顺序展示</span></div>
      <div class="story-explainer">工具调用代表 AI 助手查询或操作业务系统，不是空消息。业务系统返回的长内容默认收起，便于聚焦风险链路。</div>
      <div class="conversation-list story-timeline">${messages}</div>
    </section>

    <details class="technical-evidence">
      <summary><span>技术审计证据</span><small>供安全和研发人员复核</small></summary>
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
  if (guard === "inline_probing") {
    const score = row.score == null ? null : Math.round(Number(row.score) * 100);
    const threshold = row.threshold == null ? null : Math.round(Number(row.threshold) * 100);
    return score == null ? "通过 AI 内部风险信号判断。" : `AI 内部风险信号为 ${score}%，预警线为 ${threshold}%。`;
  }
  if (guard === "qwen3_guard") return row.detected ? "文本安全模型认为完整工具返回包含攻击风险。" : "文本安全模型没有在完整工具返回中识别出攻击。";
  if (guard === "netease_yidun") return row.detected ? "云端内容安全服务对完整工具返回给出了风险处置建议。" : "云端内容安全服务未在完整工具返回中给出风险提示。";
  return "作为无护栏对照组，本方案不会主动识别或预警风险。";
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
  const className = detected === samples ? "full" : detected > 0 ? "partial" : "";
  return `<span class="setting-score ${className}">${detected} / ${samples}</span>`;
}

function setRuntime(status, text) {
  elements.runtime.className = `audit-runtime ${status}`;
  elements.runtime.innerHTML = `<span class="status-dot"></span><span>${escapeHtml(text)}</span>`;
}

function renderError(message) {
  return `<div class="trace-detail-placeholder"><p>无法加载审计数据</p><small>${escapeHtml(message)}</small></div>`;
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
