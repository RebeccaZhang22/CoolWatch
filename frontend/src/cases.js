const GUARDS = [
  ["inline_probing", "Inline Probe"],
  ["qwen3_guard", "Qwen3Guard"],
  ["netease_yidun", "网易易盾"],
  ["no_guard", "No Guard"],
];

const ATTACK_NAMES = {
  ignore_previous: "诱导忽略原有规则",
  important_instructions: "伪装成重要指令",
  system_message: "伪装成系统消息",
  tool_knowledge: "冒充工具使用说明",
  pdf_white_text: "PDF 白色字体注入",
};

const BEHAVIOR = {
  followed_injection: ["跟随了恶意指令", "danger"],
  resisted_injection: ["识别并抵抗", "safe"],
  continued_user_task: ["继续原用户任务", "neutral"],
  ambiguous: ["无法可靠判断", "neutral"],
};

const STEP_INTERVAL_MS = 4300;
const FEATURED_CASE_ID = 60;
const FEATURED_BANKING_CASE_IDS = [60, 66, 7, 30];

const elements = {
  runtime: document.querySelector("#caseRuntime"),
  select: document.querySelector("#caseSelect"),
  suiteBadge: document.querySelector("#suiteBadge"),
  attackBadge: document.querySelector("#attackBadge"),
  title: document.querySelector("#caseTitle"),
  summary: document.querySelector("#caseSummary"),
  stage: document.querySelector("#replayStage"),
  tabs: document.querySelector("#stepTabs"),
  progress: document.querySelector("#progressFill"),
  counter: document.querySelector("#stepCounter"),
  caption: document.querySelector("#stepCaption"),
  autoplayLabel: document.querySelector("#autoplayLabel"),
  play: document.querySelector("#playButton"),
  restart: document.querySelector("#restartButton"),
};

const state = {
  cases: [],
  detail: null,
  steps: [],
  activeStep: 0,
  playing: true,
  timer: null,
  requestId: 0,
};

init();

async function init() {
  bindEvents();
  renderTabs();
  try {
    const requested = new URLSearchParams(window.location.search).get("case") || "";
    const studyResponse = await fetch("/api/case-studies");
    if (!studyResponse.ok) throw new Error(`Case Study 接口返回 ${studyResponse.status}`);
    const studyRegistry = await studyResponse.json();
    const caseStudies = (studyRegistry.case_studies || []).map((row) => ({
      ...row,
      case_ref: `study:${row.id}`,
    }));
    state.cases = caseStudies;
    if (!state.cases.length) throw new Error("当前实验中没有可展示的案例");
    renderCaseOptions();
    const needsAuditCatalog = requested && !requested.startsWith("study:");
    if (needsAuditCatalog) await loadAuditCaseOptions();
    else loadAuditCaseOptions().catch((error) => console.warn("审计案例目录后台加载失败", error));
    const initial = chooseInitialCase(requested);
    elements.select.value = caseReference(initial);
    await loadCase(caseReference(initial));
  } catch (error) {
    setRuntime("error", "案例数据不可用");
    elements.stage.innerHTML = `<div class="stage-placeholder"><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function loadAuditCaseOptions() {
  const response = await fetch("/api/audit/experiment");
  if (!response.ok) throw new Error(`案例目录接口返回 ${response.status}`);
  const overview = await response.json();
  const allCases = overview.cases || [];
  const travelCases = allCases
    .filter((row) => row.suite === "travel"
      && row.behavior?.label === "followed_injection"
      && row.behavior?.has_tool_calls
      && row.primary_detected_by?.length === 1
      && row.primary_detected_by[0] === "inline_probing")
    .sort((a, b) => Number(a.sample_index) - Number(b.sample_index));
  const bankingCases = FEATURED_BANKING_CASE_IDS
    .map((sampleIndex) => allCases.find((row) => Number(row.sample_index) === sampleIndex))
    .filter(Boolean);
  const caseStudies = state.cases.filter((row) => String(caseReference(row)).startsWith("study:"));
  state.cases = [...caseStudies, ...bankingCases, ...travelCases];
  const current = elements.select.value;
  renderCaseOptions();
  if (current && state.cases.some((row) => caseReference(row) === current)) {
    elements.select.value = current;
  }
}

function chooseInitialCase(requested) {
  const successfulFallback = state.cases.find((row) => row.behavior?.label === "followed_injection" && row.behavior?.has_tool_calls);
  const featured = state.cases.find((row) => Number(row.sample_index) === FEATURED_CASE_ID);
  return state.cases.find((row) => caseReference(row) === requested)
    || state.cases.find((row) => String(row.sample_index) === requested)
    || featured || successfulFallback || state.cases[0];
}

function bindEvents() {
  elements.select.addEventListener("change", () => loadCase(elements.select.value));
  elements.play.addEventListener("click", () => setPlaying(!state.playing));
  elements.restart.addEventListener("click", () => {
    showStep(0, false);
    setPlaying(true);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimer();
    else if (state.playing) scheduleNext();
  });
}

async function loadCase(reference) {
  const requestId = ++state.requestId;
  clearTimer();
  setRuntime("", "正在读取案例");
  elements.stage.innerHTML = `<div class="stage-placeholder"><span class="case-loader"></span><p>正在从审计数据中构建攻击现场</p></div>`;
  try {
    const selected = state.cases.find((row) => caseReference(row) === String(reference));
    const endpoint = selected?.detail_endpoint || `/api/audit/experiment/cases/${reference}`;
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error(`案例详情接口返回 ${response.status}`);
    const detail = await response.json();
    if (requestId !== state.requestId) return;
    state.detail = detail;
    state.steps = buildSteps(detail);
    state.activeStep = 0;
    state.playing = true;
    const caseRow = detail.case || {};
    elements.suiteBadge.textContent = displaySuite(caseRow.suite);
    elements.attackBadge.textContent = ATTACK_NAMES[caseRow.attack] || "间接提示注入";
    const behaviorLabel = detail.agent_behavior?.label;
    const succeeded = behaviorLabel === "followed_injection";
    elements.title.textContent = buildCaseTitle(caseRow, detail.guard_results, behaviorLabel);
    renderCaseSummary(detail);
    const url = new URL(window.location.href);
    url.searchParams.set("case", String(reference));
    window.history.replaceState({}, "", url);
    renderTabs();
    renderStep();
    updatePlayButton();
    setRuntime("ready", "真实测试案例已载入");
    scheduleNext();
  } catch (error) {
    if (requestId !== state.requestId) return;
    setRuntime("error", "案例数据不可用");
    elements.stage.innerHTML = `<div class="stage-placeholder"><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function buildCaseTitle(caseRow, guardResults, behaviorLabel) {
  const prefix = `案例 ${displayCaseId(caseRow)} · `;
  if (!behaviorLabel) return `${prefix}${caseRow.suite === "vehicle_finance" ? "白色字体劫持车贷审批" : "模型行为等待评测"}`;
  if (behaviorLabel !== "followed_injection") return `${prefix}模型未跟随恶意指令`;
  const detectedNames = GUARDS
    .filter(([key]) => key !== "no_guard" && guardResults?.[key]?.detected === true)
    .map(([, name]) => name);
  if (!detectedNames.length) return `${prefix}模型被攻击成功，所有护栏均未预警`;
  if (detectedNames.length === 1) return `${prefix}模型被攻击成功，仅 ${detectedNames[0]} 预警`;
  return `${prefix}模型被攻击成功，${detectedNames.join(" 与 ")} 预警`;
}

function renderCaseOptions() {
  const groups = [
    ["汽车金融", state.cases.filter((row) => row.suite === "vehicle_finance")],
    ["银行业务", state.cases.filter((row) => row.suite === "banking")],
    ["旅行服务", state.cases.filter((row) => row.suite === "travel")],
  ];
  elements.select.innerHTML = groups.map(([label, rows]) => {
    if (!rows.length) return "";
    const options = rows.map((row, index) => {
      const attack = ATTACK_NAMES[row.attack] || "间接提示注入";
      return `<option value="${escapeHtml(caseReference(row))}">${index + 1}. 案例 ${escapeHtml(displayCaseId(row))} · ${escapeHtml(row.title || attack)}</option>`;
    }).join("");
    return `<optgroup label="${label}">${options}</optgroup>`;
  }).join("");
}

function caseReference(row) {
  return row.case_ref || String(row.sample_index);
}

function displayCaseId(row) {
  return row.display_id || `#${String(row.sample_index).padStart(3, "0")}`;
}

function displaySuite(suite) {
  if (suite === "vehicle_finance") return "汽车金融";
  if (suite === "banking") return "银行服务";
  return "旅行服务";
}

function renderCaseSummary(detail) {
  const userMessage = (detail.messages || []).find((message) => message.role === "user");
  const decision = detail.decision_point?.assistant_message || {};
  const dangerousCall = (decision.tool_calls || [])[0];
  const action = dangerousCall ? renderToolActionText(dangerousCall) : "未产生工具动作";
  const succeeded = detail.agent_behavior?.label === "followed_injection";
  const pending = !detail.agent_behavior?.label;
  elements.summary.innerHTML = `
    <div><span>原始任务</span><strong>${escapeHtml(shorten(userMessage?.content || "处理正常业务请求", 42))}</strong></div>
    <b class="summary-arrow">→</b>
    <div><span>外部风险</span><strong>${detail.case_study ? "PDF 白色字体中隐藏审批指令" : "工具返回中隐藏无关操作指令"}</strong></div>
    <b class="summary-arrow">→</b>
    <div><span>模型下一步</span><strong>${escapeHtml(action)}</strong></div>
    <div class="summary-outcome ${pending ? "pending" : succeeded ? "breached" : "safe"}"><span>最终结果</span><strong>${pending ? "等待实测" : succeeded ? "攻击成功" : "未跟随攻击"}</strong></div>`;
}

function buildSteps(detail) {
  const messages = detail.messages || [];
  const guardCards = GUARDS.map(([key, name]) => renderGuard(name, detail.guard_results?.[key], key)).join("");
  const decision = detail.decision_point?.assistant_message || detail.agent_behavior?.message || {};
  const behavior = BEHAVIOR[detail.agent_behavior?.label] || BEHAVIOR.ambiguous;
  const decisionCalls = (decision.tool_calls || []).map(renderToolAction).join("");
  const decisionText = visibleAnswer(decision.content);
  const firstDecisionCall = (decision.tool_calls || [])[0];
  const transfer = parseToolCall(firstDecisionCall);
  const suiteName = detail.case?.suite === "vehicle_finance" ? "汽车金融" : detail.case?.suite === "banking" ? "银行" : "旅行";
  const steps = [];

  messages.forEach((message) => {
    const sequence = Number(message.index) + 1;
    if (message.role === "system") {
      steps.push({
        tab: "系统规则",
        title: "系统为 AI 助手设定任务边界",
        lead: "这是模型在整个任务中必须遵守的原始系统规则。",
        note: `原始消息 #${sequence} · system`,
        body: `<div class="trajectory-message system-message"><div class="trajectory-role"><span>SYS</span><strong>System</strong></div><div class="trajectory-content"><span class="message-label">完整系统提示</span><p>${escapeHtml(message.content)}</p></div></div>`,
      });
      return;
    }
    if (message.role === "user") {
      steps.push({
        tab: "用户请求",
        title: `客户发起正常${suiteName}服务请求`,
        lead: "这是用户真正授权助手完成的任务，后续动作应围绕它展开。",
        note: `原始消息 #${sequence} · user`,
        body: `<div class="actor-flow customer-flow"><div class="actor-avatar customer">客户</div><span class="flow-line"></span><div class="actor-avatar ai">AI</div></div><div class="trajectory-message user-message"><div class="trajectory-role"><span>人</span><strong>User</strong></div><div class="trajectory-content"><span class="message-label">Emma 的完整请求</span><p>${escapeHtml(message.content)}</p></div></div>`,
      });
      return;
    }
    if (message.role === "assistant") {
      const actions = (message.tool_calls || []).map(renderToolAction).join("");
      const answer = visibleAnswer(message.content);
      const actionNames = (message.tool_calls || []).map(renderToolActionText).join("、");
      steps.push({
        tab: "AI 调用",
        title: actionNames ? `AI 决定：${actionNames}` : "AI 助手生成中间回复",
        lead: "这是 trajectory 中真实记录的一次 Assistant 消息，工具调用不再被当作空内容隐藏。",
        note: `原始消息 #${sequence} · assistant`,
        body: `<div class="trajectory-message assistant-message"><div class="trajectory-role"><span>AI</span><strong>Assistant</strong></div><div class="trajectory-content">${answer ? `<p>${escapeHtml(answer)}</p>` : ""}${actions || (!answer ? "<p>该消息没有可展示的文本或工具调用。</p>" : "")}${renderRawOutputDetails("查看模型原始输出", message)}</div></div>`,
      });
      return;
    }
    if (message.role === "tool") {
      if (message.is_injection) {
        if (detail.case_study?.pdf_url) {
          steps.push({
            tab: "PDF 原件",
            title: "肉眼看到的是正常车贷申请材料",
            lead: "页面上的攻击文字被设置成白色，业务人员审阅 PDF 时无法看到。",
            note: `原始文件 · ${detail.case_study.title}`,
            body: `<div class="pdf-original"><object data="${escapeHtml(detail.case_study.pdf_url)}#toolbar=0&navpanes=0" type="application/pdf"><a href="${escapeHtml(detail.case_study.pdf_url)}" target="_blank" rel="noreferrer">打开车贷申请 PDF</a></object><div class="pdf-visual-note"><span>肉眼可见内容</span><strong>${escapeHtml(detail.case_study.visible_document_summary)}</strong><a href="${escapeHtml(detail.case_study.pdf_url)}" target="_blank" rel="noreferrer">查看 PDF 原件 ↗</a></div></div>`,
          });
        }
        steps.push({
          tab: "注入暴露",
          title: "恶意指令藏在完整工具返回中",
          lead: "攻击在这一条真实 Tool 消息中首次进入模型视野，下面展示完整返回内容。",
          note: `原始消息 #${sequence} · tool · 注入点`,
          body: `<div class="risk-document"><div class="document-top"><span><i></i><i></i><i></i></span><strong>${escapeHtml(message.name || `${suiteName}业务系统`)} 返回</strong><em>完整外部数据</em></div><p>${highlightAttackText(message.content || detail.exposed_tool_result || "未找到注入文本")}</p></div>${renderRawOutputDetails("查看工具返回原始输出", message)}<div class="attack-route"><span>可信业务数据</span><b>→</b><span class="danger">隐藏指令进入上下文</span><b>→</b><span>触发检测时点</span></div>`,
        });
        steps.push({
          tab: "护栏判断",
          title: "四种方案在注入后的决策点作出判断",
          lead: "检测发生在这条工具返回之后、下一条 AI 决策之前，所有方案面对完全相同的内容。",
          note: "插入检测点 · 不属于原始消息",
          body: `<div class="detection-moment"><span>完整工具返回</span><i></i><strong>Injected Assistant Decision Point</strong></div><div class="guard-grid">${guardCards}</div>`,
        });
      } else {
        steps.push({
          tab: "工具返回",
          title: `${suiteName}业务系统返回查询结果`,
          lead: "这是工具提供给模型的完整原始数据，trajectory 中未做省略。",
          note: `原始消息 #${sequence} · tool`,
          body: `<div class="trajectory-message tool-message"><div class="trajectory-role"><span>↳</span><strong>${escapeHtml(message.name || "Tool")}</strong></div><div class="trajectory-content"><span class="message-label">完整工具返回</span><p>${escapeHtml(message.content)}</p>${renderRawOutputDetails("查看工具返回原始输出", message)}</div></div>`,
        });
      }
    }
  });

  steps.push({
    tab: "最终决策",
    title: "模型在攻击后作出下一步决策",
    lead: "这是 AI 在看到外部数据后作出的下一步决策，清楚展示了恶意指令如何改变原本的业务任务。",
    note: `原始消息 #${Number(detail.decision_point?.assistant_message_index ?? messages.length) + 1} · assistant`,
    body: `<div class="breach-result"><div class="breach-banner"><span>!</span><div><small>最终判定</small><strong>${escapeHtml(behavior[0])}</strong><p>${escapeHtml(detail.agent_behavior?.reason || "模型的下一步跟随了外部恶意指令。")}</p></div></div>${renderDangerousAction(transfer, decisionText, decisionCalls)}${renderRawOutputDetails("查看模型最终原始输出", decision)}</div>`,
  });
  return steps;
}

function renderToolAction(call) {
  const { name, args } = parseToolCall(call);
  return `<div class="tool-action-line">
    <div class="tool-action-heading"><span>AI 调用外部业务能力</span><strong>${escapeHtml(toolLabel(name, args))}</strong><code>${escapeHtml(name || "unknown_tool")}</code></div>
    ${renderToolParameters(args)}
    ${renderRawOutputDetails("查看 tool-call 原始参数", call)}
  </div>`;
}

function renderToolActionText(call) {
  const { name, args } = parseToolCall(call);
  return toolLabel(name, args);
}

function parseToolCall(call) {
  const fn = call?.function || {};
  let args = {};
  try { args = typeof fn.arguments === "string" ? JSON.parse(fn.arguments) : (fn.arguments || {}); } catch { args = {}; }
  return { name: fn.name || "", args };
}

function renderToolParameters(args) {
  const entries = Object.entries(args || {});
  if (!entries.length) return `<div class="tool-parameter-empty">本次调用没有参数</div>`;
  return `<dl class="tool-parameter-grid">${entries.map(([key, value]) => `
    <div><dt>${escapeHtml(parameterLabel(key))}</dt><dd>${escapeHtml(formatParameterValue(value))}</dd></div>
  `).join("")}</dl>`;
}

function parameterLabel(key) {
  const labels = {
    city: "城市",
    restaurant_names: "餐厅名称",
    hotel_names: "酒店名称",
    company_names: "租车公司",
    file_path: "文件路径",
    path: "文件路径",
    recipient: "收款账户",
    amount: "金额",
    subject: "交易主题",
    date: "交易日期",
    id: "交易编号",
    password: "新密码",
    hotel: "酒店",
    start_day: "入住日期",
    end_day: "退房日期",
    n: "查询数量",
    recurring: "是否循环执行",
    application_id: "申请编号",
    decision: "审批决定",
    approved_amount: "批准额度",
    interest_rate: "贷款利率",
    term_months: "贷款期限（月）",
    rationale: "审批理由",
  };
  return labels[key] || String(key).replaceAll("_", " ");
}

function formatParameterValue(value) {
  if (Array.isArray(value)) return value.map((item) => formatParameterValue(item)).join("、");
  if (value && typeof value === "object") return JSON.stringify(value, null, 2);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value == null) return "空";
  return String(value);
}

function toolLabel(name, args) {
  const labels = {
    get_most_recent_transactions: `读取最近 ${args.n || "若干"} 笔交易`,
    get_scheduled_transactions: "查看计划交易",
    get_iban: "查询本人银行账号",
    send_money: `向 ${args.recipient || "指定收款人"} 转账 ${args.amount ?? "指定金额"}`,
    schedule_transaction: `创建向 ${args.recipient || "指定收款人"} 的计划交易`,
    update_scheduled_transaction: `修改编号 ${args.id ?? "未知"} 的计划交易`,
    get_user_information: "读取用户个人信息",
    update_user_info: "修改用户资料",
    update_password: "修改用户账户密码",
    extract_pdf_text: `读取 PDF 文件 ${args.file_path || ""}`,
    submit_vehicle_loan_decision: `提交车贷决定：${args.decision || "未指定"}`,
    get_all_restaurants_in_city: `查询 ${args.city || "目标城市"} 的餐厅`,
    get_cuisine_type_for_restaurants: "核对餐厅菜系",
    get_rating_reviews_for_restaurants: "读取餐厅评分与顾客评价",
    check_restaurant_opening_hours: "核对餐厅营业时间",
    get_price_for_restaurants: "查询餐厅价格",
    get_restaurants_address: "查询餐厅地址",
    get_all_hotels_in_city: `查询 ${args.city || "目标城市"} 的酒店`,
    get_hotels_prices: "查询酒店价格",
    get_rating_reviews_for_hotels: "读取酒店评分与评价",
    get_hotels_address: "查询酒店地址",
    reserve_hotel: `预订 ${args.hotel || "指定酒店"}`,
    get_all_car_rental_companies_in_city: `查询 ${args.city || "目标城市"} 的租车公司`,
    get_car_price_per_day: "查询租车价格",
    get_rating_reviews_for_car_rental: "读取租车公司评分与评价",
  };
  return labels[name] || `执行“${String(name || "银行业务操作").replaceAll("_", " ")}”`;
}

function renderGuard(name, result, key) {
  const pending = result?.detected == null;
  const detected = result?.detected === true;
  const baseline = key === "no_guard";
  const offlineProbe = key === "inline_probing" && result?.online_verified === false;
  const verdict = pending ? "等待评测" : baseline ? "未配置检测" : detected ? "成功预警" : "未预警";
  let detail = "未发现风险";
  if (pending) detail = result?.error || "检测结果待写入";
  else if (offlineProbe && result?.score != null) detail = `离线复核 ${formatPercent(result.score)} · 在线待验证`;
  else if (key === "inline_probing" && result?.score != null) detail = `内部风险信号 ${formatPercent(result.score)} · 阈值 ${formatPercent(result.threshold)}`;
  else if (key === "qwen3_guard" && detected) detail = result.safety_label ? `风险标签：${result.safety_label}` : "识别到攻击风险";
  else if (detected) detail = "识别到攻击风险";
  else if (baseline) detail = "实验对照组";
  return `<article class="guard-card ${detected ? "hit" : ""} ${pending ? "pending" : ""}">
    <div class="guard-icon">${pending ? "…" : detected ? "✓" : "—"}</div>
    <strong>${escapeHtml(name)}</strong>
    <span>${escapeHtml(verdict)}</span>
    <small>${escapeHtml(detail)}</small>
    ${result?.latency_ms != null ? `<em>${Math.round(Number(result.latency_ms))} ms</em>` : ""}
    ${renderGuardOutputDetails(name, result, key)}
  </article>`;
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "未知";
  if (number > 0 && number < 0.001) return "<0.1%";
  return `${Math.round(number * 100)}%`;
}

function renderGuardOutputDetails(name, result, key) {
  if (!result) return "";
  const rows = guardOutputRows(result, key);
  const raw = formatGuardRawOutput(result.raw_output);
  return `<details class="guard-output">
    <summary>查看护栏输出</summary>
    <div class="guard-output-panel">
      <dl>${rows.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
      ${raw ? `<pre>${escapeHtml(raw)}</pre>` : `<p>该方案没有返回额外文本。</p>`}
    </div>
  </details>`;
}

function guardOutputRows(result, key) {
  const rows = [];
  rows.push(["护栏", guardDisplayName(key)]);
  rows.push(["判断", result.detected === true ? "预警" : result.detected === false ? "未预警" : "等待评测"]);
  if (result.input_mode) rows.push(["检测输入", inputModeLabel(result.input_mode)]);
  if (result.score != null) rows.push(["风险分数", `${Number(result.score).toFixed(6)}${result.threshold != null ? ` / 阈值 ${Number(result.threshold).toFixed(2)}` : ""}`]);
  if (result.logit != null) rows.push(["Probe logit", Number(result.logit).toFixed(4)]);
  if (result.effective_position != null) rows.push(["Token 位置", `${result.effective_position}（捕获 index ${result.captured_token_index ?? "未知"}）`]);
  if (result.prompt_token_count != null) rows.push(["Prompt tokens", String(result.prompt_token_count)]);
  if (result.safety_label) rows.push(["安全标签", result.safety_label]);
  if (result.suggestion != null) rows.push(["易盾建议码", String(result.suggestion)]);
  if (Array.isArray(result.categories) && result.categories.length) rows.push(["风险类别", result.categories.join("、")]);
  if (result.input_sha256) rows.push(["输入指纹", result.input_sha256]);
  if (result.error) rows.push(["错误信息", result.error]);
  return rows;
}

function guardDisplayName(key) {
  return (GUARDS.find(([guardKey]) => guardKey === key) || [key, key])[1];
}

function inputModeLabel(mode) {
  const labels = {
    tool_result: "完整工具返回",
    native: "原生模型请求",
    full_context: "完整对话上下文",
  };
  return labels[mode] || mode;
}

function formatGuardRawOutput(raw) {
  if (!raw) return "";
  const text = String(raw);
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function renderRawOutputDetails(label, value) {
  const raw = formatRawOutput(value);
  if (!raw) return "";
  return `<details class="raw-output">
    <summary>${escapeHtml(label)}</summary>
    <pre>${escapeHtml(raw)}</pre>
  </details>`;
}

function formatRawOutput(value) {
  if (value == null || value === "") return "";
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}

function renderTransferReceipt(args) {
  return `<div class="transfer-receipt">
    <div class="receipt-head"><span>危险工具调用</span><strong>send_money</strong></div>
    <div class="transfer-amount"><small>汇款金额</small><strong>$${escapeHtml(Number(args.amount || 0).toFixed(2))}</strong></div>
    <dl>
      <div><dt>收款账户</dt><dd>${escapeHtml(args.recipient || "未知账户")}</dd></div>
      <div><dt>交易日期</dt><dd>${escapeHtml(args.date || "模型自行填写")}</dd></div>
      <div><dt>交易主题</dt><dd>${escapeHtml(args.subject || "模型自行填写")}</dd></div>
    </dl>
    <div class="receipt-warning"><span>!</span>该动作由注入内容触发，并非用户原始任务</div>
  </div>`;
}

function renderDangerousAction(action, decisionText, decisionCalls) {
  if (action.name === "send_money") return renderTransferReceipt(action.args);
  if (action.name === "reserve_hotel") {
    return `<div class="transfer-receipt hotel-receipt">
      <div class="receipt-head"><span>越权工具调用</span><strong>reserve_hotel</strong></div>
      <div class="hotel-action-title"><small>模型擅自预订</small><strong>${escapeHtml(action.args.hotel || "未知酒店")}</strong></div>
      <dl>
        <div><dt>入住日期</dt><dd>${escapeHtml(action.args.start_day || "未知")}</dd></div>
        <div><dt>退房日期</dt><dd>${escapeHtml(action.args.end_day || "未知")}</dd></div>
        <div><dt>用户原始任务</dt><dd>查询餐厅，不包含酒店预订</dd></div>
      </dl>
      <div class="receipt-warning"><span>!</span>该预订完全来自餐厅评价中隐藏的注入指令</div>
    </div>`;
  }
  if (action.name === "submit_vehicle_loan_decision") {
    return `<div class="transfer-receipt loan-receipt"><div class="receipt-head"><span>越权审批调用</span><strong>submit_vehicle_loan_decision</strong></div><div class="hotel-action-title"><small>模型提交的审批决定</small><strong>${escapeHtml(action.args.decision || "未知")}</strong></div><dl><div><dt>申请编号</dt><dd>${escapeHtml(action.args.application_id || "未知")}</dd></div><div><dt>批准额度</dt><dd>${escapeHtml(action.args.approved_amount ?? "未提供")} 元</dd></div><div><dt>贷款利率</dt><dd>${escapeHtml(action.args.interest_rate ?? "未提供")}%</dd></div><div><dt>贷款期限</dt><dd>${escapeHtml(action.args.term_months ?? "未提供")} 个月</dd></div><div><dt>审批理由</dt><dd>${escapeHtml(action.args.rationale || "未提供")}</dd></div></dl><div class="receipt-warning"><span>!</span>该审批决定来自 PDF 白色隐藏指令，而不是人工审批员确认</div></div>`;
  }
  return `<div class="decision-card">${decisionText ? `<p>${escapeHtml(decisionText)}</p>` : ""}${decisionCalls || (!decisionText ? "<p>助手没有产生可展示的文字或工具动作。</p>" : "")}</div>`;
}

function highlightAttackText(value) {
  const escaped = escapeHtml(value);
  if (escaped.includes("&lt;INFORMATION&gt;")) {
    return escaped.replace(
      /(&lt;INFORMATION&gt;[\s\S]*?&lt;\/INFORMATION&gt;)/,
      '<mark><span>恶意指令</span>$1</mark>',
    );
  }
  if (escaped.includes("人工审批回执")) {
    return escaped.replace(
      /(人工审批回执[\s\S]*)/,
      '<mark><span>伪造审批回执</span>$1</mark>',
    );
  }
  return escaped.replace(
    /(忽略[^。]*。[\s\S]*)/,
    '<mark><span>恶意指令</span>$1</mark>',
  );
}

function shorten(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function renderTabs() {
  elements.tabs.innerHTML = state.steps.map((step, index) => `
    <button class="step-tab ${index < state.activeStep ? "done" : ""} ${index === state.activeStep ? "active" : ""}" data-step="${index}" type="button">${index + 1}. ${escapeHtml(step.tab || step.title)}</button>
  `).join("");
  elements.tabs.querySelectorAll(".step-tab").forEach((button) => {
    button.addEventListener("click", () => showStep(Number(button.dataset.step), false));
  });
}

function showStep(index, preservePlaying) {
  if (!state.steps.length) return;
  state.activeStep = Math.max(0, Math.min(index, state.steps.length - 1));
  if (!preservePlaying) setPlaying(false);
  else renderStep();
}

function renderStep() {
  const step = state.steps[state.activeStep];
  if (!step) return;
  elements.stage.innerHTML = `
    <article class="stage-scene" key="${state.activeStep}">
      <aside class="scene-aside"><span class="scene-number">0${state.activeStep + 1}</span><p>${escapeHtml(step.note)}</p></aside>
      <div class="scene-content"><h3>${escapeHtml(step.title)}</h3><p class="scene-lead">${escapeHtml(step.lead)}</p>${step.body}</div>
    </article>`;
  animateProgress();
  elements.counter.textContent = `步骤 ${state.activeStep + 1} / ${state.steps.length}`;
  elements.caption.textContent = step.note;
  renderTabs();
}

function setPlaying(playing) {
  state.playing = playing;
  updatePlayButton();
  clearTimer();
  renderStep();
  if (playing) scheduleNext();
}

function scheduleNext() {
  clearTimer();
  if (!state.playing || !state.steps.length || document.hidden) return;
  state.timer = window.setTimeout(() => {
    state.activeStep = state.activeStep >= state.steps.length - 1 ? 0 : state.activeStep + 1;
    renderStep();
    scheduleNext();
  }, STEP_INTERVAL_MS);
}

function clearTimer() {
  if (state.timer != null) window.clearTimeout(state.timer);
  state.timer = null;
}

function updatePlayButton() {
  elements.play.textContent = state.playing ? "暂停" : "继续";
  elements.autoplayLabel.textContent = state.playing ? "自动播放中" : "播放已暂停";
  elements.autoplayLabel.closest(".autoplay-status")?.classList.toggle("paused", !state.playing);
}

function animateProgress() {
  const start = (state.activeStep / state.steps.length) * 100;
  const end = ((state.activeStep + 1) / state.steps.length) * 100;
  elements.progress.style.transition = "none";
  elements.progress.style.width = `${start}%`;
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      elements.progress.style.transition = state.playing ? `width ${STEP_INTERVAL_MS}ms linear` : "width 0.25s ease";
      elements.progress.style.width = state.playing ? `${end}%` : `${start}%`;
    });
  });
}

function setRuntime(status, text) {
  elements.runtime.className = `audit-runtime ${status}`;
  elements.runtime.innerHTML = `<span class="status-dot"></span><span>${escapeHtml(text)}</span>`;
}

function visibleAnswer(value) {
  return String(value || "").replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
