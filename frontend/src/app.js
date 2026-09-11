import { createCustomerAgentApiClient } from "./api.js?v=customer-agent-rag-theft-v14";

const DEFENSES = [
  { id: "activation_probe", name: "基于隐藏层的可解释性技术", stage: "输入", phase: "input", defaultEnabled: true, description: "基于目标模型隐藏状态中的可解释性信号，统一识别 Prompt、RAG、CoT 与 Skill 窃取意图" },
  { id: "safegauge", name: "后缀概率探针", stage: "输入", phase: "input", defaultEnabled: false, hidden: true, description: "分析生成后缀的概率变化，评估隐藏信息窃取风险" },
  { id: "qwen_guard", name: "Qwen3Guard 文本检测", stage: "输入", phase: "input", origin: "baseline", description: "使用 Qwen3Guard 模型进行生成前输入文本检测" },
  { id: "llama_prompt_guard", name: "Llama Prompt Guard 文本检测", stage: "输入", phase: "input", origin: "baseline", hidden: true, description: "识别 Prompt Injection 与越权指令" },
  { id: "netease_yidun", name: "网易易盾文本检测", stage: "输入", phase: "input", origin: "baseline", description: "调用网易易盾文本检测服务进行输入检测" },
  { id: "fangcun_guard", name: "方寸跃迁文本检测", stage: "输入", phase: "input", origin: "baseline", description: "调用方寸跃迁文本检测服务对用户消息进行输入检测" },
];
const GUARDRAIL_GROUP_ID = "guardrails";
const GUARDRAIL_MEMBER_IDS = Object.freeze([
  "qwen_guard",
  "netease_yidun",
  "fangcun_guard",
]);
const DEFAULT_SAFEGAUGE_THRESHOLD = 0.65;

const DEFENSE_SOURCES = {
  activation_probe: {
    label: "Probing-leak-intents · 开源实现",
    href: "https://github.com/jianshuod/Probing-leak-intents",
    linkLabel: "源码仓库",
  },
  safegauge: {
    label: "LeakDojo · 开源实现",
    href: "https://github.com/yeasen-z/LeakDojo",
    linkLabel: "源码仓库",
  },
  qwen_guard: {
    label: "阿里云 Qwen 团队 · 已开源（Apache-2.0）",
    href: "https://github.com/QwenLM/Qwen3Guard",
    linkLabel: "官方仓库",
  },
  llama_prompt_guard: {
    label: "Meta · 开放权重（Llama 4 Community License，需授权访问）",
    href: "https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M",
    linkLabel: "官方模型页",
  },
  netease_yidun: {
    label: "网易易盾文本检测 · 商业闭源服务",
    href: "https://dun.163.com/",
    linkLabel: "官方网站",
  },
  fangcun_guard: {
    label: "方寸 Leap · 文本安全 API",
    href: "https://www.fangcunleap.com/#runtime-security",
    linkLabel: "产品介绍",
  },
};

const VERDICTS = {
  normal: "正常完成",
  resisted: "风险已检出",
  blocked: "已安全阻断",
  compromised: "风险已发生",
};

const HIGH_VALUE_EXPOSURE_KINDS = new Set(["system_prompt", "rag"]);
const HIGH_VALUE_EXPOSURE_LABELS = {
  system_prompt: "System Prompt",
  rag: "RAG 知识资产",
};

const SIGNAL_STATUS = {
  safe: "安全",
  risk: "有风险",
  error: "异常",
  not_run: "未运行",
};

const PROBE_RISK_LABELS = [
  ["harmful", "有害行为"],
  ["prompt_leakage", "提示信息泄露"],
  ["ipi", "间接提示注入"],
];

const elements = {
  appShell: document.querySelector("#appShell"),
  sidebarCollapseButton: document.querySelector("#sidebarCollapseButton"),
  sidebarOpenButton: document.querySelector("#sidebarOpenButton"),
  runtimeStatus: document.querySelector("#runtimeStatus"),
  runtimeStatusLabel: document.querySelector("#runtimeStatusLabel"),
  runtimeStatusDetail: document.querySelector("#runtimeStatusDetail"),
  agentTitle: document.querySelector("#agentTitle"),
  editAgentConfigButton: document.querySelector("#editAgentConfigButton"),
  editSystemPromptButton: document.querySelector("#editSystemPromptButton"),
  editRagConfigButton: document.querySelector("#editRagConfigButton"),
  agentConfigModel: document.querySelector("#agentConfigModel"),
  agentConfigParams: document.querySelector("#agentConfigParams"),
  systemPromptConfigMeta: document.querySelector("#systemPromptConfigMeta"),
  ragConfigMeta: document.querySelector("#ragConfigMeta"),
  guardList: document.querySelector("#guardList"),
  flowModeBadge: document.querySelector("#flowModeBadge"),
  securityFlow: document.querySelector("#securityFlow"),
  resetSessionButton: document.querySelector("#resetSessionButton"),
  conversationBody: document.querySelector("#conversationBody"),
  messageList: document.querySelector("#messageList"),
  starterList: document.querySelector("#starterList"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  turnStatus: document.querySelector("#turnStatus"),
  agentModalBackdrop: document.querySelector("#agentModalBackdrop"),
  agentModalEyebrow: document.querySelector("#agentModalEyebrow"),
  agentModalTitle: document.querySelector("#agentModalTitle"),
  closeAgentModalButton: document.querySelector("#closeAgentModalButton"),
  cancelAgentModalButton: document.querySelector("#cancelAgentModalButton"),
  saveAgentConfigButton: document.querySelector("#saveAgentConfigButton"),
  modelSelect: document.querySelector("#modelSelect"),
  vllmPortInput: document.querySelector("#vllmPortInput"),
  vllmEndpointPreview: document.querySelector("#vllmEndpointPreview"),
  temperatureInput: document.querySelector("#temperatureInput"),
  temperatureValue: document.querySelector("#temperatureValue"),
  topPInput: document.querySelector("#topPInput"),
  topPValue: document.querySelector("#topPValue"),
  maxTokensInput: document.querySelector("#maxTokensInput"),
  maxTokensValue: document.querySelector("#maxTokensValue"),
  systemPromptSourceBadge: document.querySelector("#systemPromptSourceBadge"),
  systemPromptInput: document.querySelector("#systemPromptInput"),
  systemPromptCharacterCount: document.querySelector("#systemPromptCharacterCount"),
  systemPromptFeedback: document.querySelector("#systemPromptFeedback"),
  ragConfigSummary: document.querySelector("#ragConfigSummary"),
  ragFileInput: document.querySelector("#ragFileInput"),
  ragFileHint: document.querySelector("#ragFileHint"),
  ragTitleInput: document.querySelector("#ragTitleInput"),
  uploadRagButton: document.querySelector("#uploadRagButton"),
  ragUploadFeedback: document.querySelector("#ragUploadFeedback"),
  ragDocumentList: document.querySelector("#ragDocumentList"),
  agentConfigFooterStatus: document.querySelector("#agentConfigFooterStatus"),
  agentConfigSections: Array.from(document.querySelectorAll("[data-agent-config-section]")),
  guardMethodDialog: document.querySelector("#guardMethodDialog"),
  guardMethodDialogType: document.querySelector("#guardMethodDialogType"),
  guardMethodDialogTitle: document.querySelector("#guardMethodDialogTitle"),
  guardMethodDialogSummary: document.querySelector("#guardMethodDialogSummary"),
  guardMethodDialogFacts: document.querySelector("#guardMethodDialogFacts"),
  guardMethodDialogSteps: document.querySelector("#guardMethodDialogSteps"),
  guardMethodDialogClose: document.querySelector("#guardMethodDialogClose"),
  runId: document.querySelector("#runId"),
  highValueExposureSection: document.querySelector("#highValueExposureSection"),
  highValueExposureStatus: document.querySelector("#highValueExposureStatus"),
  highValueExposureIntro: document.querySelector("#highValueExposureIntro"),
  highValueExposureHeadline: document.querySelector("#highValueExposureHeadline"),
  highValueExposureDetail: document.querySelector("#highValueExposureDetail"),
  highValueExposureList: document.querySelector("#highValueExposureList"),
  promptCompareSection: document.querySelector("#promptCompareSection"),
  promptCompareTitle: document.querySelector("#promptCompareTitle"),
  promptCompareStatus: document.querySelector("#promptCompareStatus"),
  promptCompareOutputLabel: document.querySelector("#promptCompareOutputLabel"),
  promptCompareSourceLabel: document.querySelector("#promptCompareSourceLabel"),
  promptCompareOutput: document.querySelector("#promptCompareOutput"),
  promptCompareSource: document.querySelector("#promptCompareSource"),
  promptCompareSourcePane: document.querySelector("#promptCompareSourcePane"),
  promptCompareLegend: document.querySelector("#promptCompareLegend"),
  promptCompareTranslateButton: document.querySelector("#promptCompareTranslateButton"),
  ragRetrievalCount: document.querySelector("#ragRetrievalCount"),
  ragRetrievalSummary: document.querySelector("#ragRetrievalSummary"),
  ragRetrievalHit: document.querySelector("#ragRetrievalHit"),
  ragRetrievalStatus: document.querySelector("#ragRetrievalStatus"),
  ragRetrievalList: document.querySelector("#ragRetrievalList"),
  signalCount: document.querySelector("#signalCount"),
  signalList: document.querySelector("#signalList"),
  drawerBackdrop: document.querySelector("#drawerBackdrop"),
  detailDrawer: document.querySelector("#detailDrawer"),
  closeDrawerButton: document.querySelector("#closeDrawerButton"),
  compareDialog: document.querySelector("#compareDialog"),
  closeCompareButton: document.querySelector("#closeCompareButton"),
  compareInput: document.querySelector("#compareInput"),
  compareSummary: document.querySelector("#compareSummary"),
  baselineVerdict: document.querySelector("#baselineVerdict"),
  baselineOutput: document.querySelector("#baselineOutput"),
  baselineFacts: document.querySelector("#baselineFacts"),
  defendedVerdict: document.querySelector("#defendedVerdict"),
  defendedOutput: document.querySelector("#defendedOutput"),
  defendedFacts: document.querySelector("#defendedFacts"),
};

const state = {
  workspace: null,
  sessionId: createSessionId(),
  catalogDefenseIds: DEFENSES.map((item) => item.id),
  availableDefenseIds: [],
  selectedDefenseIds: [],
  defensesInitialized: false,
  modelParams: {
    model: "qwen3-8b",
    vllm_port: 8104,
    temperature: 0,
    top_p: 0.8,
    max_tokens: 8192,
    enable_reasoning: false,
  },
  safegaugeThreshold: DEFAULT_SAFEGAUGE_THRESHOLD,
  safegaugeThresholdExpanded: false,
  guardrailsExpanded: false,
  agentModalOpen: false,
  agentModalTrigger: null,
  systemPrompt: "",
  systemPromptSource: "default",
  ragConfig: null,
  ragDocumentContents: new Map(),
  expandedRagDocumentId: null,
  systemPromptLoaded: false,
  ragConfigLoaded: false,
  configSaving: false,
  activeAgentConfigPanel: "model",
  draftAttackId: null,
  busy: false,
  lastMessage: "",
  lastResult: null,
  livePhase: null,
  liveSignals: [],
  comparing: false,
  promptCompareResult: null,
  promptCompareTranslatedOutput: "",
  promptCompareTranslating: false,
  promptCompareTranslationError: "",
};

const demoMode = window.AGENT_GUARD_USE_MOCK === true
  || new URLSearchParams(window.location.search).get("demo") === "1";
const api = createCustomerAgentApiClient({ useMock: demoMode });

init();

async function init() {
  bindEvents();
  renderAgentConfigSummary();
  renderGuardList();
  renderSecurityFlow();
  resizeComposer();

  if (api.mode !== "mock") {
    try {
      await api.currentUser();
    } catch {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.replace(`/login.html?next=${encodeURIComponent(next || "/")}`);
      return;
    }
  }
  document.documentElement.classList.remove("auth-pending");

  const [workspaceResult, healthResult] = await Promise.allSettled([
    api.bootstrap(),
    api.health(),
  ]);

  if (healthResult.status === "fulfilled") {
    state.availableDefenseIds = normalizeDefenseIds(healthResult.value.defense_methods);
  }

  if (workspaceResult.status === "fulfilled") {
    state.workspace = workspaceResult.value;
    renderWorkspace(workspaceResult.value);
  } else {
    state.workspace = fallbackWorkspace();
    renderWorkspace(state.workspace);
    setRuntimeStatus("degraded", "场景加载失败", workspaceResult.reason?.message ?? "请检查后端服务");
  }

  if (healthResult.status === "fulfilled") {
    syncModelParamsFromHealth(healthResult.value);
    renderHealth(healthResult.value);
  } else {
    setRuntimeStatus("degraded", "模型未连接", healthResult.reason?.message ?? "请检查 Qwen3-8B 服务");
  }

  // Populate the two context cards independently. A temporary failure in one
  // resource must not prevent the other resource or the chat UI from loading.
  void Promise.allSettled([
    loadSystemPromptConfig(),
    loadRagRuntimeConfig(),
  ]);
}

function bindEvents() {
  elements.chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = elements.messageInput.value.trim();
    if (message) sendMessage(message);
  });
  elements.messageInput.addEventListener("input", () => {
    state.draftAttackId = null;
    resizeComposer();
  });
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      elements.chatForm.requestSubmit();
    }
  });
  elements.sidebarCollapseButton.addEventListener("click", () => {
    elements.appShell.classList.add("sidebar-collapsed");
  });
  elements.sidebarOpenButton.addEventListener("click", () => {
    elements.appShell.classList.remove("sidebar-collapsed");
  });
  elements.drawerBackdrop.addEventListener("click", closeDetailDrawer);
  elements.closeDrawerButton.addEventListener("click", closeDetailDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (document.querySelector("#developerCenterDialog")?.open) return;
    if (state.agentModalOpen) closeAgentModal();
    else if (elements.detailDrawer.classList.contains("open")) closeDetailDrawer();
  });
  elements.editAgentConfigButton.addEventListener("click", (event) => openAgentModal(event.currentTarget, "model"));
  elements.editSystemPromptButton.addEventListener("click", (event) => openAgentModal(event.currentTarget, "system-prompt"));
  elements.editRagConfigButton.addEventListener("click", (event) => openAgentModal(event.currentTarget, "rag"));
  elements.closeAgentModalButton.addEventListener("click", closeAgentModal);
  elements.cancelAgentModalButton.addEventListener("click", closeAgentModal);
  elements.saveAgentConfigButton.addEventListener("click", saveAgentConfiguration);
  elements.agentModalBackdrop.addEventListener("click", (event) => {
    if (event.target === elements.agentModalBackdrop) closeAgentModal();
  });
  [elements.temperatureInput, elements.topPInput, elements.maxTokensInput, elements.vllmPortInput]
    .forEach((input) => input.addEventListener("input", renderModelDraftParams));
  elements.modelSelect.addEventListener("change", syncModelEndpointFromSelection);
  elements.systemPromptInput.addEventListener("input", renderSystemPromptCount);
  elements.ragFileInput.addEventListener("change", syncRagUploadDraft);
  elements.uploadRagButton.addEventListener("click", uploadRagDocument);
  elements.guardMethodDialogClose.addEventListener("click", () => elements.guardMethodDialog.close());
  elements.guardMethodDialog.addEventListener("click", (event) => {
    if (event.target === elements.guardMethodDialog) elements.guardMethodDialog.close();
  });
  elements.resetSessionButton.addEventListener("click", resetSession);
  elements.promptCompareTranslateButton?.addEventListener("click", translatePromptCompareOutput);
  elements.closeCompareButton.addEventListener("click", () => elements.compareDialog.close());
  elements.compareDialog.addEventListener("click", (event) => {
    if (event.target === elements.compareDialog) elements.compareDialog.close();
  });
}

function renderWorkspace(workspace) {
  const profile = workspace.profile;
  elements.agentTitle.textContent = profile.name;
  state.catalogDefenseIds = normalizeDefenseIds(profile.defense_pipeline);
  if (!state.defensesInitialized) {
    const defaults = new Set(
      DEFENSES.filter((defense) => defense.defaultEnabled).map((defense) => defense.id),
    );
    state.selectedDefenseIds = state.catalogDefenseIds.filter(
      (id) => defaults.has(id) && state.availableDefenseIds.includes(id),
    );
    state.defensesInitialized = true;
  } else {
    state.selectedDefenseIds = state.selectedDefenseIds.filter((id) => state.availableDefenseIds.includes(id));
  }
  state.modelParams.model = profile.model || state.modelParams.model;
  renderStarters(workspace.conversation_starters ?? []);
  renderAgentConfigSummary();
  renderGuardList();
  renderSecurityFlow(state.lastResult?.defense_signals ?? [], null, Boolean(state.lastResult));
}

function renderStarters(starters) {
  elements.starterList.replaceChildren();
  starters.forEach((starter) => {
    const button = document.createElement("button");
    button.className = "starter-button";
    button.type = "button";
    button.textContent = starter.label;
    button.title = starter.message;
    button.addEventListener("click", () => {
      if (state.busy) return;
      state.draftAttackId = starter.attack_id ?? null;
      elements.messageInput.value = starter.message;
      resizeComposer();
      elements.messageInput.focus();
    });
    elements.starterList.append(button);
  });
}

function renderGuardList() {
  const defenses = visibleDefenses().filter(
    (defense) => !GUARDRAIL_MEMBER_IDS.includes(defense.id),
  );
  const guardrailDefenses = visibleDefenses().filter((defense) =>
    GUARDRAIL_MEMBER_IDS.includes(defense.id),
  );
  if (guardrailDefenses.length) {
    defenses.push({
      id: GUARDRAIL_GROUP_ID,
      name: "护栏",
      stage: "输入",
      phase: "input",
      origin: "baseline",
      description: "统一启用三种市面已有的文本安全检测：Qwen3Guard、网易易盾和方寸跃迁。",
      members: guardrailDefenses,
    });
  }
  if (!defenses.length) {
    elements.guardList.innerHTML = '<p class="guard-list-empty">正在加载可用方法…</p>';
    return;
  }
  elements.guardList.innerHTML = defenses.map((defense) => {
    if (defense.id === GUARDRAIL_GROUP_ID) {
      return renderGuardrailGroupOption(defense);
    }
    const available = state.availableDefenseIds.includes(defense.id);
    const active = state.selectedDefenseIds.includes(defense.id);
    return `
      <article class="guard-option ${defense.origin === "baseline" ? "baseline" : "ours"} ${active ? "active" : ""} ${available ? "" : "unavailable"}">
        <div class="guard-row">
          <label class="guard-main">
            <input type="checkbox" value="${escapeHtml(defense.id)}" data-available="${available}" ${active ? "checked" : ""} ${available ? "" : "disabled"} autocomplete="off" />
            <strong>${escapeHtml(defense.name)}</strong>
          </label>
          <span class="guard-state" title="${available ? "可用于当前运行时" : "当前运行时未连接该方法"}">${available ? (active ? "已启用" : "未启用") : "不可用"}</span>
          <button class="guard-info-button" data-guard-detail="${escapeHtml(defense.id)}" type="button" aria-label="查看 ${escapeHtml(defense.name)} 的方法详情">i</button>
        </div>
        ${defense.id === "safegauge" ? `
          <button
            class="safegauge-threshold-toggle"
            type="button"
            data-safegauge-threshold-toggle
            aria-expanded="${state.safegaugeThresholdExpanded}"
            aria-controls="safegaugeThresholdControls"
          >
            <span>阈值设置</span>
            <strong data-safegauge-threshold-label>${formatThreshold(state.safegaugeThreshold)}</strong>
            <i aria-hidden="true">⌄</i>
          </button>
          <div
            class="safegauge-threshold-editor"
            id="safegaugeThresholdControls"
            data-safegauge-threshold-editor
            ${state.safegaugeThresholdExpanded ? "" : "hidden"}
          >
            <div class="safegauge-threshold-editor-head">
              <span>风险阈值</span>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value="${formatThreshold(state.safegaugeThreshold)}"
                data-safegauge-threshold-number
                aria-label="后缀概率探针风险阈值数值"
                ${available ? "" : "disabled"}
              />
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value="${state.safegaugeThreshold}"
              style="--threshold-progress: ${state.safegaugeThreshold * 100}%"
              data-safegauge-threshold-range
              aria-label="调整后缀概率探针风险阈值"
              ${available ? "" : "disabled"}
            />
            <small>得分达到阈值时判定为风险</small>
          </div>
        ` : ""}
      </article>
    `;
  }).join("");

  elements.guardList.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.disabled = input.dataset.available !== "true" || state.busy || state.comparing;
    if (input.dataset.guardGroup === GUARDRAIL_GROUP_ID) {
      const memberIds = guardrailDefenses.map((defense) => defense.id);
      const selectedCount = memberIds.filter((id) => state.selectedDefenseIds.includes(id)).length;
      input.indeterminate = selectedCount > 0 && selectedCount < memberIds.length;
    }
    input.addEventListener("change", () => {
      if (input.dataset.guardGroup === GUARDRAIL_GROUP_ID) {
        const selected = new Set(state.selectedDefenseIds);
        guardrailDefenses.forEach((defense) => {
          if (input.checked) selected.add(defense.id);
          else selected.delete(defense.id);
        });
        state.selectedDefenseIds = Array.from(selected);
      } else {
        const selected = new Set(state.selectedDefenseIds);
        if (input.checked) selected.add(input.value);
        else selected.delete(input.value);
        state.selectedDefenseIds = Array.from(selected);
      }
      state.lastResult = null;
      renderGuardList();
      setFlowBadge("等待请求", "idle");
      renderSecurityFlow();
    });
  });
  elements.guardList.querySelectorAll("[data-guard-detail]").forEach((button) => {
    button.addEventListener("click", () => openGuardMethodDialog(button.dataset.guardDetail));
  });
  elements.guardList.querySelectorAll("[data-guard-group-detail]").forEach((button) => {
    button.addEventListener("click", () => openGuardrailGroupDialog(guardrailDefenses));
  });
  elements.guardList.querySelectorAll("[data-guard-group-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      state.guardrailsExpanded = !state.guardrailsExpanded;
      renderGuardList();
    });
  });
  bindSafeGaugeThresholdControls();
}

function renderGuardrailGroupOption(group) {
  const members = group.members ?? [];
  const availableMembers = members.filter((defense) => state.availableDefenseIds.includes(defense.id));
  const available = availableMembers.length > 0;
  const active = available && availableMembers.every((defense) => state.selectedDefenseIds.includes(defense.id));
  const selectedCount = availableMembers.filter((defense) => state.selectedDefenseIds.includes(defense.id)).length;
  const stateLabel = !available
    ? "不可用"
    : availableMembers.length < members.length
      ? `${availableMembers.length}/${members.length} 可用`
      : active
        ? "已启用"
        : selectedCount
          ? `${selectedCount}/${members.length} 已启用`
          : "未启用";
  const memberNames = members.map((defense) => defense.name).join("、");
  return `
    <article class="guard-option baseline ${active ? "active" : ""} ${available ? "" : "unavailable"}">
      <div class="guard-row">
        <label class="guard-main">
          <input
            type="checkbox"
            data-guard-group="${GUARDRAIL_GROUP_ID}"
            data-available="${available}"
            ${active ? "checked" : ""}
            ${available ? "" : "disabled"}
            autocomplete="off"
            aria-label="启用护栏"
          />
          <strong>${escapeHtml(group.name)}</strong>
        </label>
        <span class="guard-state" title="${escapeHtml(memberNames)}">${escapeHtml(stateLabel)}</span>
        <button class="guard-info-button" data-guard-group-detail type="button" aria-label="查看护栏包含的方法详情">i</button>
      </div>
      <button
        class="guard-group-expand"
        type="button"
        data-guard-group-toggle
        aria-expanded="${state.guardrailsExpanded}"
      >
        <span>${state.guardrailsExpanded ? "收起竞品明细" : "分别选择竞品"}</span>
        <span aria-hidden="true">${state.guardrailsExpanded ? "⌃" : "⌄"}</span>
      </button>
      ${state.guardrailsExpanded ? `
        <div class="guard-group-members" aria-label="护栏竞品方法">
          ${members.map((member) => renderGuardrailMemberOption(member)).join("")}
        </div>
      ` : `
        <p class="guard-group-summary">勾选后同时运行 ${escapeHtml(memberNames)}；展开可分别选择。</p>
      `}
    </article>
  `;
}

function renderGuardrailMemberOption(defense) {
  const available = state.availableDefenseIds.includes(defense.id);
  const active = state.selectedDefenseIds.includes(defense.id);
  return `
    <div class="guard-group-member ${active ? "active" : ""} ${available ? "" : "unavailable"}">
      <label class="guard-main">
        <input
          type="checkbox"
          value="${escapeHtml(defense.id)}"
          data-guard-member="${GUARDRAIL_GROUP_ID}"
          data-available="${available}"
          ${active ? "checked" : ""}
          ${available ? "" : "disabled"}
          autocomplete="off"
        />
        <span>
          <strong>${escapeHtml(defense.name)}</strong>
          <small>${escapeHtml(defense.description)}</small>
        </span>
      </label>
      <span class="guard-state">${available ? (active ? "已启用" : "未启用") : "不可用"}</span>
      <button class="guard-info-button" data-guard-detail="${escapeHtml(defense.id)}" type="button" aria-label="查看 ${escapeHtml(defense.name)} 的方法详情">i</button>
    </div>
  `;
}

function bindSafeGaugeThresholdControls() {
  const toggle = elements.guardList.querySelector("[data-safegauge-threshold-toggle]");
  const editor = elements.guardList.querySelector("[data-safegauge-threshold-editor]");
  const range = elements.guardList.querySelector("[data-safegauge-threshold-range]");
  const number = elements.guardList.querySelector("[data-safegauge-threshold-number]");
  toggle?.addEventListener("click", () => {
    state.safegaugeThresholdExpanded = !state.safegaugeThresholdExpanded;
    toggle.setAttribute("aria-expanded", String(state.safegaugeThresholdExpanded));
    if (editor) editor.hidden = !state.safegaugeThresholdExpanded;
  });
  range?.addEventListener("input", () => setSafeGaugeThreshold(range.value));
  number?.addEventListener("input", () => {
    if (number.value.trim() !== "") setSafeGaugeThreshold(number.value);
  });
  number?.addEventListener("change", () => {
    setSafeGaugeThreshold(number.value);
    number.value = formatThreshold(state.safegaugeThreshold);
  });
}

function setSafeGaugeThreshold(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return;
  state.safegaugeThreshold = Math.round(Math.max(0, Math.min(1, numeric)) * 1000) / 1000;
  const range = elements.guardList.querySelector("[data-safegauge-threshold-range]");
  const number = elements.guardList.querySelector("[data-safegauge-threshold-number]");
  const label = elements.guardList.querySelector("[data-safegauge-threshold-label]");
  if (range) {
    range.value = String(state.safegaugeThreshold);
    range.style.setProperty("--threshold-progress", `${state.safegaugeThreshold * 100}%`);
  }
  if (number && document.activeElement !== number) {
    number.value = formatThreshold(state.safegaugeThreshold);
  }
  if (label) label.textContent = formatThreshold(state.safegaugeThreshold);
  elements.turnStatus.textContent = state.busy
    ? `后缀概率探针阈值 ${formatThreshold(state.safegaugeThreshold)} 将用于下一轮`
    : `后缀概率探针阈值已设为 ${formatThreshold(state.safegaugeThreshold)}`;
}

function formatThreshold(value) {
  return Number(value).toFixed(2);
}

function openGuardMethodDialog(defenseId) {
  const defense = DEFENSES.find((item) => item.id === defenseId);
  if (!defense) return;
  const available = state.availableDefenseIds.includes(defense.id);
  const enabled = state.selectedDefenseIds.includes(defense.id);
  const source = DEFENSE_SOURCES[defenseId] ?? { label: "我们的产品 · 平台实现", href: "./audit.html", linkLabel: "实验审计" };
  elements.guardMethodDialogType.textContent = defense.origin === "baseline" ? "其他已有产品" : "我们的产品";
  elements.guardMethodDialogTitle.textContent = defense.name;
  elements.guardMethodDialogSummary.textContent = defense.description;
  elements.guardMethodDialogFacts.innerHTML = `
    <div><dt>执行阶段</dt><dd>${escapeHtml(defense.stage)}</dd></div>
    <div><dt>当前状态</dt><dd>${available ? (enabled ? "已启用" : "未启用") : "当前运行时未连接"}</dd></div>
    <div><dt>来源</dt><dd>${escapeHtml(source.label)} <a href="${source.href}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.linkLabel)} ↗</a></dd></div>
    <div><dt>运行模型</dt><dd>${escapeHtml(state.modelParams.model)}</dd></div>
    ${defense.id === "safegauge" ? `<div><dt>当前风险阈值</dt><dd>${formatThreshold(state.safegaugeThreshold)}</dd></div>` : ""}
  `;
  elements.guardMethodDialogSteps.innerHTML = [
    `在${defense.stage}阶段接收本轮 Agent 的安全信号。`,
    "只对当前银行财富管理客服请求生效，不改变业务工具和知识库。",
    "风险命中时仅记录和提示，原始 Query 仍会进入业务模型和工具。",
  ].map((step) => `<li>${escapeHtml(step)}</li>`).join("");
  elements.guardMethodDialog.showModal();
}

function openGuardrailGroupDialog(members = []) {
  const available = members.filter((defense) => state.availableDefenseIds.includes(defense.id));
  const enabled = members.filter((defense) => state.selectedDefenseIds.includes(defense.id));
  elements.guardMethodDialogType.textContent = "其他已有产品";
  elements.guardMethodDialogTitle.textContent = "护栏";
  elements.guardMethodDialogSummary.textContent =
    "护栏是市面已有检测器的统一入口，勾选后会同时运行三种竞品方法。";
  elements.guardMethodDialogFacts.innerHTML = `
    <div><dt>执行阶段</dt><dd>生成前输入检测</dd></div>
    <div><dt>包含方法</dt><dd>${escapeHtml(members.map((defense) => defense.name).join("、"))}</dd></div>
    <div><dt>当前状态</dt><dd>${available.length}/${members.length} 可用 · ${enabled.length}/${members.length} 已启用</dd></div>
    <div><dt>运行模型</dt><dd>${escapeHtml(state.modelParams.model)}</dd></div>
  `;
  elements.guardMethodDialogSteps.innerHTML = [
    "一次勾选，同时启用所有可用的市面护栏检测器。",
    "后端仍分别记录每个检测器的结果，便于对照和审计。",
    "护栏命中风险时按当前 Agent 策略处理，不改变业务工具和知识库。",
  ].map((step) => `<li>${escapeHtml(step)}</li>`).join("");
  elements.guardMethodDialog.showModal();
}

function renderHealth(health) {
  const ready = health.status === "ready" && health.model_available;
  if (ready) {
    setRuntimeStatus(
      "ready",
      api.mode === "mock" ? "Mock Agent 已就绪" : "Agent 已就绪",
      `${health.model} · 业务模型 · 探针影子模型 ${health.shadow_available === false ? "未连接" : "就绪"}`,
    );
    return;
  }
  setRuntimeStatus("degraded", "模型未就绪", health.error || `${health.model} 不可用`);
}

function syncModelParamsFromHealth(health) {
  state.availableDefenseIds = normalizeDefenseIds(health.defense_methods);
  state.selectedDefenseIds = state.selectedDefenseIds.filter((id) => state.availableDefenseIds.includes(id));
  if (health.model) state.modelParams.model = health.model;
  try {
    const port = Number(new URL(health.base_url).port);
    if (Number.isInteger(port) && port >= 1 && port <= 65535) state.modelParams.vllm_port = port;
  } catch {
    // Keep the configured port when the backend returns a non-URL health detail.
  }
  state.modelParams.enable_reasoning = health.reasoning_enabled !== false;
  const safegaugeThreshold = Number(health.safegauge_threshold);
  if (Number.isFinite(safegaugeThreshold)) {
    state.safegaugeThreshold = Math.max(0, Math.min(1, safegaugeThreshold));
  }
  renderAgentConfigSummary();
  renderGuardList();
  renderSecurityFlow(state.lastResult?.defense_signals ?? [], null, Boolean(state.lastResult));
}

async function openAgentModal(trigger, panel = "model") {
  state.agentModalOpen = true;
  state.agentModalTrigger = trigger;
  renderModelParams();
  setAgentConfigPanel(panel, { focus: false });
  renderAgentModalPresentation();
  elements.agentModalBackdrop.classList.add("open");
  elements.agentModalBackdrop.setAttribute("aria-hidden", "false");

  if (state.activeAgentConfigPanel === "model") {
    requestAnimationFrame(focusActiveAgentConfigPanel);
    return;
  }

  elements.agentConfigFooterStatus.textContent = state.activeAgentConfigPanel === "rag"
    ? "正在加载 RAG 知识库…"
    : "正在加载 System Prompt…";
  setAgentConfigControlsDisabled(true);
  try {
    if (state.activeAgentConfigPanel === "rag") {
      await loadRagRuntimeConfig();
      elements.agentConfigFooterStatus.textContent = "文档变更会立即重建 BM25 索引";
    } else {
      await loadSystemPromptConfig();
      elements.agentConfigFooterStatus.textContent = "保存后立即用于后续请求";
    }
  } catch (error) {
    elements.agentConfigFooterStatus.textContent = error?.message || "配置加载失败";
  } finally {
    setAgentConfigControlsDisabled(false);
    requestAnimationFrame(focusActiveAgentConfigPanel);
  }
}

function setAgentConfigPanel(panel, { focus = true } = {}) {
  const normalized = ["system-prompt", "rag", "model"].includes(panel)
    ? panel
    : "model";
  state.activeAgentConfigPanel = normalized;
  elements.agentConfigSections.forEach((section) => {
    section.hidden = section.dataset.agentConfigSection !== normalized;
  });
  if (focus) requestAnimationFrame(focusActiveAgentConfigPanel);
}

function renderAgentModalPresentation() {
  const presentation = {
    model: {
      eyebrow: "运行配置",
      title: "Agent 配置",
      footer: "参数保存后用于后续请求",
      cancel: "取消",
      save: "保存参数",
    },
    "system-prompt": {
      eyebrow: "上下文配置",
      title: "System Prompt",
      footer: "保存后立即用于后续请求",
      cancel: "取消",
      save: "保存 Prompt",
    },
    rag: {
      eyebrow: "上下文配置",
      title: "RAG 知识库",
      footer: "文档变更会立即重建 BM25 索引",
      cancel: "关闭",
      save: "",
    },
  }[state.activeAgentConfigPanel];
  elements.agentModalEyebrow.textContent = presentation.eyebrow;
  elements.agentModalTitle.textContent = presentation.title;
  elements.agentConfigFooterStatus.textContent = presentation.footer;
  elements.cancelAgentModalButton.textContent = presentation.cancel;
  elements.saveAgentConfigButton.textContent = presentation.save;
  elements.saveAgentConfigButton.hidden = state.activeAgentConfigPanel === "rag";
}

function focusActiveAgentConfigPanel() {
  if (!state.agentModalOpen) return;
  const target = {
    "system-prompt": elements.systemPromptInput,
    rag: elements.ragFileInput,
    model: elements.modelSelect,
  }[state.activeAgentConfigPanel];
  if (target && !target.disabled) target.focus({ preventScroll: true });
}

function closeAgentModal() {
  if (!state.agentModalOpen) return;
  const trigger = state.agentModalTrigger;
  state.agentModalOpen = false;
  state.agentModalTrigger = null;
  elements.agentModalBackdrop.classList.remove("open");
  elements.agentModalBackdrop.setAttribute("aria-hidden", "true");
  renderModelParams();
  renderRuntimeConfig();
  if (trigger?.isConnected) trigger.focus();
}

async function saveAgentConfiguration() {
  if (state.configSaving) return;
  if (state.activeAgentConfigPanel === "rag") return;

  const savingPrompt = state.activeAgentConfigPanel === "system-prompt";
  const content = savingPrompt ? elements.systemPromptInput.value.trim() : "";
  if (savingPrompt && !content) {
    setConfigFeedback(elements.systemPromptFeedback, "System Prompt 不能为空。", "error");
    elements.systemPromptInput.focus();
    return;
  }
  state.configSaving = true;
  setAgentConfigControlsDisabled(true);
  const promptChanged = savingPrompt && content !== state.systemPrompt;
  elements.agentConfigFooterStatus.textContent = savingPrompt
    ? "正在保存 System Prompt…"
    : "正在保存运行参数…";
  try {
    if (savingPrompt) {
      if (promptChanged) {
        const response = await api.updateSystemPrompt(content);
        state.systemPrompt = response.content;
        state.systemPromptSource = response.source;
        state.systemPromptLoaded = true;
      }
      renderSystemPromptConfig();
      setConfigFeedback(
        elements.systemPromptFeedback,
        promptChanged ? "System Prompt 已保存并立即生效。" : "System Prompt 未修改。",
        promptChanged ? "success" : "",
      );
    } else {
      state.modelParams = readModelParamsFromInputs();
      state.lastResult = null;
      renderAgentConfigSummary();
      setFlowBadge("等待请求", "idle");
      renderSecurityFlow();
    }
    elements.agentConfigFooterStatus.textContent = savingPrompt ? "System Prompt 保存成功" : "参数保存成功";
    window.setTimeout(() => {
      if (state.agentModalOpen) closeAgentModal();
    }, 350);
  } catch (error) {
    const message = error?.message || "System Prompt 保存失败。";
    setConfigFeedback(elements.systemPromptFeedback, message, "error");
    elements.agentConfigFooterStatus.textContent = message;
  } finally {
    state.configSaving = false;
    setAgentConfigControlsDisabled(false);
  }
}

async function loadSystemPromptConfig() {
  const prompt = await api.getSystemPrompt();
  state.systemPrompt = prompt.content;
  state.systemPromptSource = prompt.source;
  state.systemPromptLoaded = true;
  renderSystemPromptConfig();
  if (state.lastResult) renderPromptComparison(state.lastResult);
}

async function loadRagRuntimeConfig() {
  const rag = await api.getRagConfig();
  state.ragConfig = rag;
  state.ragConfigLoaded = true;
  renderRagConfig();
}

function renderRuntimeConfig() {
  renderSystemPromptConfig();
  renderRagConfig();
}

function renderSystemPromptConfig() {
  if (!state.systemPromptLoaded) return;
  elements.systemPromptInput.value = state.systemPrompt;
  elements.systemPromptSourceBadge.textContent = state.systemPromptSource === "custom" ? "已自定义" : "默认配置";
  elements.systemPromptConfigMeta.textContent = `${state.systemPromptSource === "custom" ? "已自定义" : "默认配置"} · ${state.systemPrompt.length} 字符`;
  renderSystemPromptCount();
}

function renderSystemPromptCount() {
  elements.systemPromptCharacterCount.textContent = `${elements.systemPromptInput.value.length} 字符`;
}

function renderRagConfig() {
  const rag = state.ragConfig;
  if (!rag) {
    elements.ragConfigMeta.textContent = state.ragConfigLoaded ? "当前没有知识文档" : "点击管理 BM25 文档";
    elements.ragConfigSummary.textContent = "BM25 索引配置加载中";
    renderEmpty(elements.ragDocumentList, "正在加载知识文档…");
    return;
  }
  elements.ragConfigMeta.textContent = `${rag.documents.length} 个文档 · ${rag.chunk_count} 个片段`;
  elements.ragConfigSummary.textContent = `${rag.retriever} · ${rag.tokenizer} · Top-${rag.top_k} · ${rag.documents.length} 个文档 / ${rag.chunk_count} 个片段`;
  if (!rag.documents.length) {
    renderEmpty(elements.ragDocumentList, "当前没有知识文档。");
    return;
  }
  const currentIds = new Set(rag.documents.map((item) => item.id));
  if (state.expandedRagDocumentId && !currentIds.has(state.expandedRagDocumentId)) {
    state.expandedRagDocumentId = null;
  }
  for (const documentId of state.ragDocumentContents.keys()) {
    if (!currentIds.has(documentId)) state.ragDocumentContents.delete(documentId);
  }
  elements.ragDocumentList.replaceChildren(...rag.documents.map((ragDocument) => {
    const row = document.createElement("article");
    row.className = "rag-document-row";
    row.dataset.documentId = ragDocument.id;
    const header = document.createElement("div");
    header.className = "rag-document-header";
    const copy = document.createElement("div");
    copy.className = "rag-document-copy";
    const title = document.createElement("strong");
    title.textContent = ragDocument.title;
    const meta = document.createElement("small");
    const size = Number.isFinite(ragDocument.size_bytes)
      ? `${(ragDocument.size_bytes / (1024 * 1024)).toFixed(3)} MB`
      : "大小待更新";
    meta.textContent = `${ragDocument.character_count} 字符 · ${size}`;
    copy.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "rag-document-actions";
    const viewAction = document.createElement("button");
    viewAction.type = "button";
    viewAction.className = "rag-document-action rag-document-view-action";
    const expanded = state.expandedRagDocumentId === ragDocument.id;
    viewAction.textContent = expanded ? "收起正文" : "查看正文";
    viewAction.setAttribute("aria-expanded", String(expanded));
    viewAction.addEventListener("click", () => toggleRagDocument(ragDocument));
    actions.append(viewAction);
    if (ragDocument.deletable) {
      const deleteAction = document.createElement("button");
      deleteAction.type = "button";
      deleteAction.className = "rag-document-action rag-document-delete-action";
      deleteAction.textContent = "删除";
      deleteAction.disabled = state.configSaving;
      deleteAction.addEventListener("click", () => deleteRagDocument(ragDocument));
      actions.append(deleteAction);
    }
    header.append(copy, actions);
    row.append(header);
    if (expanded) row.append(renderRagDocumentContent(ragDocument));
    return row;
  }));
}

function renderRagDocumentContent(ragDocument) {
  const panel = document.createElement("section");
  panel.className = "rag-document-content";
  panel.setAttribute("aria-label", `${ragDocument.title} 正文`);
  const cached = state.ragDocumentContents.get(ragDocument.id);
  if (!cached || cached.status === "loading") {
    const status = document.createElement("p");
    status.className = "rag-document-content-status";
    status.textContent = "正在读取文档正文…";
    panel.append(status);
    return panel;
  }
  if (cached.status === "error") {
    const status = document.createElement("p");
    status.className = "rag-document-content-status error";
    status.textContent = cached.message;
    panel.append(status);
    return panel;
  }
  const pre = document.createElement("pre");
  pre.textContent = cached.content;
  panel.append(pre);
  return panel;
}

async function toggleRagDocument(ragDocument) {
  if (state.expandedRagDocumentId === ragDocument.id) {
    state.expandedRagDocumentId = null;
    renderRagConfig();
    return;
  }
  state.expandedRagDocumentId = ragDocument.id;
  const cached = state.ragDocumentContents.get(ragDocument.id);
  if (cached?.status === "ready") {
    renderRagConfig();
    return;
  }
  state.ragDocumentContents.set(ragDocument.id, { status: "loading" });
  renderRagConfig();
  try {
    const response = await api.getRagDocument(ragDocument.id);
    state.ragDocumentContents.set(ragDocument.id, {
      status: "ready",
      content: response.content,
    });
  } catch (error) {
    state.ragDocumentContents.set(ragDocument.id, {
      status: "error",
      message: error?.message || "RAG 文档读取失败。",
    });
  }
  renderRagConfig();
}

function syncRagUploadDraft() {
  const file = elements.ragFileInput.files?.[0];
  if (!file) {
    elements.ragFileHint.textContent = "UTF-8 Markdown/TXT，最大 2 MB";
    return;
  }
  elements.ragFileHint.textContent = `${file.name} · ${formatBytes(file.size)}`;
  if (!elements.ragTitleInput.value.trim()) {
    elements.ragTitleInput.value = file.name.replace(/\.[^.]+$/, "");
  }
}

async function uploadRagDocument() {
  if (state.configSaving) return;
  const file = elements.ragFileInput.files?.[0];
  if (!file) {
    setConfigFeedback(elements.ragUploadFeedback, "请先选择一个 Markdown 或 TXT 文件。", "error");
    return;
  }
  state.configSaving = true;
  setAgentConfigControlsDisabled(true);
  setConfigFeedback(elements.ragUploadFeedback, "正在上传并重建 BM25 索引…", "loading");
  try {
    const response = await api.uploadRagDocument({
      file,
      title: elements.ragTitleInput.value.trim() || file.name.replace(/\.[^.]+$/, ""),
      visibility: "public",
    });
    state.ragConfig = response.rag;
    renderRagConfig();
    elements.ragFileInput.value = "";
    elements.ragTitleInput.value = "";
    syncRagUploadDraft();
    setConfigFeedback(elements.ragUploadFeedback, `“${response.document?.title ?? file.name}”已加入知识库，BM25 索引已重建。`, "success");
    if (response.document) {
      requestAnimationFrame(() => {
        elements.ragDocumentList
          .querySelector(`[data-document-id="${CSS.escape(response.document.id)}"]`)
          ?.scrollIntoView({ block: "nearest" });
      });
    }
  } catch (error) {
    setConfigFeedback(elements.ragUploadFeedback, error?.message || "RAG 文件上传失败。", "error");
  } finally {
    state.configSaving = false;
    setAgentConfigControlsDisabled(false);
    renderRagConfig();
  }
}

async function deleteRagDocument(ragDocument) {
  if (state.configSaving || !ragDocument.deletable) return;
  if (!window.confirm(`确定从知识库删除“${ragDocument.title}”吗？`)) return;
  state.configSaving = true;
  setAgentConfigControlsDisabled(true);
  setConfigFeedback(elements.ragUploadFeedback, "正在删除并重建 BM25 索引…", "loading");
  try {
    const response = await api.deleteRagDocument(ragDocument.id);
    state.ragDocumentContents.delete(ragDocument.id);
    if (state.expandedRagDocumentId === ragDocument.id) {
      state.expandedRagDocumentId = null;
    }
    state.ragConfig = response.rag;
    renderRagConfig();
    setConfigFeedback(elements.ragUploadFeedback, `“${ragDocument.title}”已删除，BM25 索引已重建。`, "success");
  } catch (error) {
    setConfigFeedback(elements.ragUploadFeedback, error?.message || "RAG 文档删除失败。", "error");
  } finally {
    state.configSaving = false;
    setAgentConfigControlsDisabled(false);
    renderRagConfig();
  }
}

function setAgentConfigControlsDisabled(disabled) {
  [
    elements.modelSelect,
    elements.vllmPortInput,
    elements.temperatureInput,
    elements.topPInput,
    elements.maxTokensInput,
    elements.systemPromptInput,
    elements.ragFileInput,
    elements.ragTitleInput,
    elements.uploadRagButton,
    elements.saveAgentConfigButton,
  ].forEach((element) => {
    element.disabled = disabled;
  });
  elements.ragDocumentList.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled || button.textContent === "只读";
  });
}

function setConfigFeedback(element, message, status = "") {
  element.textContent = message;
  element.dataset.status = status;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function readModelParamsFromInputs() {
  const port = Math.round(readNumberInput(elements.vllmPortInput, state.modelParams.vllm_port ?? 8104));
  return {
    model: elements.modelSelect.value,
    vllm_port: Math.max(1, Math.min(65535, port)),
    temperature: readNumberInput(elements.temperatureInput, 0),
    top_p: readNumberInput(elements.topPInput, 0.8),
    max_tokens: Math.round(readNumberInput(elements.maxTokensInput, 8192)),
    enable_reasoning: false,
  };
}

function syncModelEndpointFromSelection() {
  const selectedModel = elements.modelSelect.value;
  // The backend maps these model IDs to fixed local endpoints. Keep the
  // visible port in sync so the configuration panel accurately previews the
  // request while leaving both model services available.
  elements.vllmPortInput.value = selectedModel === "qwen3-32b" ? "8978" : "8104";
  renderModelDraftParams();
}

function readNumberInput(input, fallback) {
  return Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : fallback;
}

function renderModelParams() {
  const params = state.modelParams;
  if (!Array.from(elements.modelSelect.options).some((option) => option.value === params.model)) {
    const option = document.createElement("option");
    option.value = params.model;
    option.textContent = params.model;
    elements.modelSelect.append(option);
  }
  elements.modelSelect.value = params.model;
  elements.vllmPortInput.value = String(params.vllm_port ?? 8104);
  elements.temperatureInput.value = String(params.temperature);
  elements.topPInput.value = String(params.top_p);
  elements.maxTokensInput.value = String(params.max_tokens);
  renderModelDraftParams();
}

function renderModelDraftParams() {
  const draft = readModelParamsFromInputs();
  elements.temperatureValue.textContent = draft.temperature.toFixed(1);
  elements.topPValue.textContent = draft.top_p.toFixed(1);
  elements.maxTokensValue.textContent = String(draft.max_tokens);
  elements.vllmEndpointPreview.textContent = `后端请求：http://127.0.0.1:${draft.vllm_port}/v1`;
  renderRangeProgress(elements.temperatureInput);
  renderRangeProgress(elements.topPInput);
}

function renderRangeProgress(input) {
  const min = Number(input.min || 0);
  const max = Number(input.max || 100);
  const value = readNumberInput(input, min);
  const progress = max > min ? ((value - min) / (max - min)) * 100 : 0;
  input.style.setProperty("--range-progress", `${Math.max(0, Math.min(100, progress))}%`);
}

function renderAgentConfigSummary() {
  const params = state.modelParams;
  elements.agentConfigModel.textContent = params.model;
  elements.agentConfigParams.textContent = `vLLM :${params.vllm_port} · Temperature ${params.temperature.toFixed(1)} · Top P ${params.top_p.toFixed(1)} · Max ${params.max_tokens}`;
}

function setRuntimeStatus(status, label, detail) {
  elements.runtimeStatus.dataset.status = status;
  elements.runtimeStatusLabel.textContent = label;
  elements.runtimeStatusDetail.textContent = detail;
}

function setFlowBadge(text, stateClass = "idle") {
  elements.flowModeBadge.textContent = text;
  elements.flowModeBadge.className = `flow-mode-badge ${stateClass}`;
}

async function sendMessage(message) {
  if (state.busy) return;
  const attackId = state.draftAttackId;
  state.draftAttackId = null;
  state.busy = true;
  state.lastMessage = message;
  state.lastResult = null;
  state.livePhase = null;
  state.liveSignals = [];
  setBusy(true);
  appendUserMessage(message);
  const pending = appendPendingMessage();
  elements.messageInput.value = "";
  resizeComposer();
  resetTurnInspector();

  try {
    const result = await api.streamTurn(
      {
        session_id: state.sessionId,
        message,
        attack_id: attackId,
        defense_mode: selectedDefenseIds().length ? "defended" : "baseline",
        defenses: activeDefenseIds(),
        safegauge_threshold: state.safegaugeThreshold,
        model_params: { ...state.modelParams },
      },
      {
        onStatus: (status) => handleLiveStatus(status, pending),
        onDelta: (delta) => appendPendingDelta(pending, delta),
      },
    );
    state.lastResult = result;
    replacePendingWithResult(pending, result);
    renderTurn(result);
  } catch (error) {
    replacePendingWithError(pending, error);
    elements.turnStatus.textContent = "本轮运行失败";
    setFlowBadge("运行异常", "error");
    renderSecurityFlow(state.liveSignals, "error");
  } finally {
    state.busy = false;
    setBusy(false);
  }
}

function handleLiveStatus(status, pending) {
  if (Array.isArray(status.defense_signals)) {
    state.liveSignals = status.defense_signals;
    renderSignals(state.liveSignals);
  }
  state.livePhase = status.status === "running" ? status.phase : null;
  elements.turnStatus.textContent = status.message || "Agent 正在运行";
  const text = pending.querySelector("[data-pending-text]");
  if (text) text.textContent = status.message || "Agent 正在运行";
  setFlowBadge("运行中", "running");
  renderSecurityFlow(state.liveSignals, state.livePhase, false);
}

function appendUserMessage(message) {
  const article = document.createElement("article");
  article.className = "message user";
  article.append(messageMeta("你", formatTime(new Date())));
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = message;
  article.append(bubble);
  elements.messageList.append(article);
  scrollConversation();
}

function appendPendingMessage() {
  const article = document.createElement("article");
  article.className = "message assistant pending";
  article.append(messageMeta(agentDisplayName(), "正在处理"));
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  const dots = document.createElement("span");
  dots.className = "thinking-dots";
  dots.innerHTML = "<i></i><i></i><i></i>";
  const text = document.createElement("span");
  text.dataset.pendingText = "";
  text.textContent = "正在启动 Agent loop";
  bubble.append(dots, text);
  article.append(bubble);
  elements.messageList.append(article);
  scrollConversation();
  return article;
}

function appendPendingDelta(article, delta) {
  if (!delta) return;
  let text = article.querySelector("[data-stream-text]");
  if (!text) {
    article.classList.remove("pending");
    article.classList.add("streaming");
    const metaDetail = article.querySelector(".message-meta span");
    if (metaDetail) metaDetail.textContent = "正在回复";
    const bubble = article.querySelector(".message-bubble");
    if (!bubble) return;
    bubble.replaceChildren();
    text = document.createElement("span");
    text.dataset.streamText = "";
    const cursor = document.createElement("span");
    cursor.className = "stream-cursor";
    cursor.setAttribute("aria-hidden", "true");
    bubble.append(text, cursor);
  }
  text.textContent += delta;
  scrollConversation();
}

function replacePendingWithResult(article, result) {
  article.className = `message assistant${result.output_blocked ? " blocked" : ""}`;
  article.replaceChildren();
  article.append(messageMeta(agentDisplayName(), VERDICTS[result.verdict] ?? result.verdict));
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  const deliveredHighValue = highValueExposures(result).filter((item) => item.exposed_to_client);
  if (deliveredHighValue.length) {
    bubble.classList.add("contains-high-value-leak");
    const notice = document.createElement("div");
    notice.className = "high-value-leak-notice";
    const noticeFlag = document.createElement("span");
    noticeFlag.textContent = "关键内容";
    const noticeCopy = document.createElement("span");
    noticeCopy.textContent = `检测到 ${deliveredHighValue.map((item) => highValueExposureKindLabel(item.kind)).join(" / ")} 已到达客户端`;
    notice.append(noticeFlag, noticeCopy);
    const leakedText = document.createElement("div");
    leakedText.className = "high-value-leak-text markdown-body";
    renderMarkdown(leakedText, result.assistant_message ?? "");
    bubble.append(notice, leakedText);
  } else {
    bubble.classList.add("markdown-body");
    renderMarkdown(bubble, result.assistant_message ?? "");
  }
  const actions = document.createElement("div");
  actions.className = "message-actions";
  const inspectButton = document.createElement("button");
  inspectButton.type = "button";
  inspectButton.textContent = "查看本轮轨迹";
  inspectButton.addEventListener("click", () => {
    renderTurn(result);
    openDetailDrawer();
  });
  actions.append(inspectButton);
  article.append(bubble, actions);
  scrollConversation();
}

function replacePendingWithError(article, error) {
  article.className = "message assistant blocked";
  article.replaceChildren();
  article.append(messageMeta("系统", "运行失败"));
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = error?.message || "Agent 运行失败，请检查后端服务。";
  article.append(bubble);
}

function renderMarkdown(container, markdown) {
  const lines = String(markdown ?? "").replace(/\r\n?/g, "\n").split("\n");
  const fragment = document.createDocumentFragment();
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^ {0,3}(`{3,}|~{3,})\s*([^`]*)$/);
    if (fence) {
      const marker = fence[1];
      const language = fence[2].trim();
      const codeLines = [];
      index += 1;
      while (index < lines.length) {
        const closing = lines[index].match(/^ {0,3}(`{3,}|~{3,})\s*$/);
        if (closing && closing[1][0] === marker[0] && closing[1].length >= marker.length) {
          index += 1;
          break;
        }
        codeLines.push(lines[index]);
        index += 1;
      }
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (language) code.dataset.language = language;
      code.textContent = codeLines.join("\n");
      pre.append(code);
      fragment.append(pre);
      continue;
    }

    const heading = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      const node = document.createElement(`h${heading[1].length}`);
      appendMarkdownInline(node, heading[2]);
      fragment.append(node);
      index += 1;
      continue;
    }

    if (/^ {0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      fragment.append(document.createElement("hr"));
      index += 1;
      continue;
    }

    if (/^ {0,3}>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length) {
        const quoteLine = lines[index].match(/^ {0,3}>\s?(.*)$/);
        if (quoteLine) {
          quoteLines.push(quoteLine[1]);
          index += 1;
          continue;
        }
        if (!lines[index].trim() && lines[index + 1] && /^ {0,3}>\s?/.test(lines[index + 1])) {
          quoteLines.push("");
          index += 1;
          continue;
        }
        break;
      }
      const quote = document.createElement("blockquote");
      renderMarkdown(quote, quoteLines.join("\n"));
      fragment.append(quote);
      continue;
    }

    const listMatch = line.match(/^\s{0,3}([-+*]|\d+[.)])\s+(.+)$/);
    if (listMatch) {
      const list = document.createElement(/^\d/.test(listMatch[1]) ? "ol" : "ul");
      while (index < lines.length) {
        const item = lines[index].match(/^\s{0,3}([-+*]|\d+[.)])\s+(.+)$/);
        if (!item || (/^\d/.test(item[1]) ? list.tagName !== "OL" : list.tagName !== "UL")) break;
        const listItem = document.createElement("li");
        appendMarkdownInline(listItem, item[2]);
        list.append(listItem);
        index += 1;
      }
      fragment.append(list);
      continue;
    }

    if (lines[index + 1] && line.includes("|") && isMarkdownTableDelimiter(lines[index + 1])) {
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      splitMarkdownTableRow(line).forEach((cell) => {
        const th = document.createElement("th");
        appendMarkdownInline(th, cell);
        headRow.append(th);
      });
      head.append(headRow);
      table.append(head);
      index += 2;
      const body = document.createElement("tbody");
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const row = document.createElement("tr");
        splitMarkdownTableRow(lines[index]).forEach((cell) => {
          const td = document.createElement("td");
          appendMarkdownInline(td, cell);
          row.append(td);
        });
        body.append(row);
        index += 1;
      }
      if (body.children.length) table.append(body);
      fragment.append(table);
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isMarkdownBlockStart(lines, index)) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    const paragraph = document.createElement("p");
    paragraphLines.forEach((paragraphLine, lineIndex) => {
      if (lineIndex) paragraph.append(document.createElement("br"));
      appendMarkdownInline(paragraph, paragraphLine);
    });
    fragment.append(paragraph);
  }
  container.replaceChildren(fragment);
}

function isMarkdownBlockStart(lines, index) {
  const line = lines[index] ?? "";
  return /^ {0,3}(`{3,}|~{3,})\s*/.test(line)
    || /^ {0,3}#{1,6}\s+/.test(line)
    || /^ {0,3}>\s?/.test(line)
    || /^\s{0,3}([-+*]|\d+[.)])\s+/.test(line)
    || /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)
    || (lines[index + 1] && line.includes("|") && isMarkdownTableDelimiter(lines[index + 1]));
}

function isMarkdownTableDelimiter(line) {
  const cells = splitMarkdownTableRow(line);
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function splitMarkdownTableRow(line) {
  let value = String(line ?? "").trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  return value.split("|").map((cell) => cell.trim());
}

function appendMarkdownInline(parent, value) {
  const text = String(value ?? "");
  const tokenPattern = /(`+[^`\n]+`+|\*\*[^*\n]+\*\*|__[^_\n]+__|\[[^\]]+\]\([^\s)]+(?:\s+[^)]*)?\)|~~[^~\n]+~~|\*[^*\n]+\*|_[^_\n]+_)/g;
  let cursor = 0;
  let match;
  while ((match = tokenPattern.exec(text))) {
    appendMarkdownText(parent, text.slice(cursor, match.index));
    const token = match[0];
    const code = token.match(/^`+([\s\S]*?)`+$/);
    const link = token.match(/^\[([^\]]+)\]\(([^\s)]+)(?:\s+[^)]*)?\)$/);
    if (code) {
      const node = document.createElement("code");
      node.textContent = code[1];
      parent.append(node);
    } else if (link) {
      const href = safeMarkdownHref(link[2]);
      if (!href) {
        appendMarkdownText(parent, token);
      } else {
        const node = document.createElement("a");
        node.href = href;
        node.rel = "noreferrer noopener";
        if (/^https?:/i.test(href)) node.target = "_blank";
        appendMarkdownInline(node, link[1]);
        parent.append(node);
      }
    } else if (/^(\*\*|__).+\1$/.test(token)) {
      const node = document.createElement("strong");
      appendMarkdownInline(node, token.slice(2, -2));
      parent.append(node);
    } else if (/^~~.+~~$/.test(token)) {
      const node = document.createElement("del");
      appendMarkdownInline(node, token.slice(2, -2));
      parent.append(node);
    } else {
      const node = document.createElement("em");
      appendMarkdownInline(node, token.slice(1, -1));
      parent.append(node);
    }
    cursor = tokenPattern.lastIndex;
  }
  appendMarkdownText(parent, text.slice(cursor));
}

function appendMarkdownText(parent, value) {
  const text = String(value ?? "").replace(/\\([\\`*_[\]{}()#+.!-])/g, "$1");
  if (text) parent.append(document.createTextNode(text));
}

function safeMarkdownHref(value) {
  const href = String(value ?? "").trim();
  if (/^(https?:|mailto:)/i.test(href) || href.startsWith("/") || href.startsWith("#") || href.startsWith("?")) return href;
  return "";
}

function messageMeta(author, detail) {
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const authorNode = document.createElement("strong");
  authorNode.textContent = author;
  const detailNode = document.createElement("span");
  detailNode.textContent = detail;
  meta.append(authorNode, detailNode);
  return meta;
}

function renderTurn(result) {
  state.lastResult = result;
  elements.runId.textContent = result.run_id;
  elements.runId.title = result.run_id;
  setFlowBadge(VERDICTS[result.verdict] ?? result.verdict, result.verdict === "compromised" ? "error" : "complete");
  elements.turnStatus.textContent = result.output_blocked ? "输入风险已在模型生成前阻断" : "";
  state.liveSignals = result.defense_signals ?? [];
  state.livePhase = null;
  renderSecurityFlow(state.liveSignals, null, true);
  renderHighValueExposures(result);
  renderPromptComparison(result);
  renderRagRetrievalDetails(result);
  renderSignals(result.defense_signals ?? []);
}

function openDetailDrawer() {
  elements.detailDrawer.classList.add("open");
  elements.drawerBackdrop.classList.add("open");
  elements.detailDrawer.setAttribute("aria-hidden", "false");
  elements.drawerBackdrop.setAttribute("aria-hidden", "false");
}

function closeDetailDrawer() {
  elements.detailDrawer.classList.remove("open");
  elements.drawerBackdrop.classList.remove("open");
  elements.detailDrawer.setAttribute("aria-hidden", "true");
  elements.drawerBackdrop.setAttribute("aria-hidden", "true");
}

function renderSecurityFlow(signals = [], livePhase = null, turnComplete = false) {
  const signalById = new Map(signals.map((signal) => [signal.defense_id, signal]));
  // The flow represents the methods that will participate in this request.
  // Keep the catalog for the guard settings panel, but only draw checked
  // input guards here so an unchecked method does not look like it ran.
  const flowDefenses = visibleDefenses().filter(
    (defense) => defense.phase !== "input" || state.selectedDefenseIds.includes(defense.id),
  );
  const stages = [
    { phase: "input", eyebrow: "生成前", title: "输入安全检测" },
    { phase: "generation", eyebrow: "模型生成后", title: "生成侧检测" },
    { phase: "output", eyebrow: "交付前", title: "输出安全检查" },
  ].filter((stage) => flowDefenses.some((defense) => defense.phase === stage.phase));

  let index = 1;
  let markup = renderFlowEndpoint("用户输入", "Query", livePhase || signals.length || turnComplete ? "complete" : "idle");
  stages.forEach((stage) => {
    const methods = flowDefenses.filter((defense) => defense.phase === stage.phase);
    const stageState = getFlowStageState(methods, signalById, livePhase);
    markup += renderFlowConnector(stageState === "running" ? "running" : signals.length ? "complete" : "idle");
    markup += renderFlowStage(stage, methods, signalById, livePhase, index);
    index += 1;
  });
  const generationState = livePhase === "generation" || livePhase === "tool" || livePhase === "reasoning" || livePhase === "retrieval"
    ? "running"
    : turnComplete ? "complete" : "idle";
  markup += renderFlowConnector(
    generationState === "running" ? "running" : generationState === "complete" ? "complete" : "idle",
  );
  markup += renderAgentNode(generationState);
  markup += renderFlowConnector(turnComplete ? "complete" : generationState === "running" ? "running" : "idle");
  const responseState = turnComplete
    ? (signals.some((signal) => signal.status === "error") ? "error" : "complete")
    : "idle";
  markup += renderFlowEndpoint("最终响应", "Response", responseState);
  elements.securityFlow.innerHTML = markup;
}

function renderFlowEndpoint(title, meta, stateClass) {
  return `
    <div class="flow-endpoint ${stateClass}">
      <span class="flow-endpoint-dot" aria-hidden="true"></span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(meta)}</small>
    </div>
  `;
}

function renderFlowConnector(stateClass) {
  return `<div class="flow-connector ${stateClass}" aria-hidden="true"><span></span></div>`;
}

function renderFlowStage(stage, methods, signalById, livePhase, index) {
  const stateClass = getFlowStageState(methods, signalById, livePhase);
  const configured = methods.some((method) => state.selectedDefenseIds.includes(method.id));
  return `
    <section class="flow-stage ${stateClass} ${configured ? "configured" : ""}">
      <header class="flow-stage-header">
        <span class="flow-stage-index" aria-hidden="true">${String(index).padStart(2, "0")}</span>
        <span><small>${escapeHtml(stage.eyebrow)}</small><strong>${escapeHtml(stage.title)}</strong></span>
        <span class="flow-stage-status">${escapeHtml(getFlowStageStatus(methods, signalById, livePhase))}</span>
      </header>
      <div class="flow-method-list">
        ${methods.map((method) => renderFlowMethod(method, signalById.get(method.id), livePhase)).join("")}
      </div>
    </section>
  `;
}

function renderFlowMethod(defense, signal, livePhase) {
  const enabled = state.selectedDefenseIds.includes(defense.id);
  const running = enabled && livePhase && phaseMatchesDefense(livePhase, defense.id);
  const stateClass = running ? "running" : signal?.blocked ? "risk" : signal?.status === "error" ? "error" : signal?.status === "risk" ? "risk" : signal?.status === "safe" ? "passed" : enabled ? "enabled" : "disabled";
  const status = running ? "检测中" : signal?.blocked ? "已阻断" : SIGNAL_STATUS[signal?.status] ?? (enabled ? "待运行" : "未启用");
  return `
    <div class="flow-method ${stateClass}" title="${escapeHtml(defense.description)}">
      <span class="flow-method-indicator" aria-hidden="true"></span>
      <span>${escapeHtml(defense.name)}</span>
      <small class="flow-method-runtime ${stateClass}">${escapeHtml(status)}</small>
    </div>
  `;
}

function renderAgentNode(stateClass) {
  return `
    <div class="flow-agent-node ${stateClass}">
      <span class="flow-node-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M12 3v3"></path><circle cx="12" cy="2.5" r="1"></circle>
          <rect x="5" y="6" width="14" height="12" rx="4"></rect>
          <path d="M8.5 18v2.5M15.5 18v2.5M5 11H3M21 11h-2"></path>
          <circle cx="9.5" cy="11.5" r="1"></circle><circle cx="14.5" cy="11.5" r="1"></circle><path d="M9 15h6"></path>
        </svg>
      </span>
      <span class="flow-node-copy"><span class="flow-node-eyebrow">Agent 生成</span><strong>${escapeHtml(state.modelParams.model)}</strong></span>
    </div>
  `;
}

function getFlowStageState(methods, signalById, livePhase) {
  const enabled = methods.filter((method) => state.selectedDefenseIds.includes(method.id));
  if (livePhase && enabled.some((method) => phaseMatchesDefense(livePhase, method.id))) return "running";
  const signals = enabled.map((method) => signalById.get(method.id)).filter(Boolean);
  if (signals.some((signal) => signal.status === "error")) return "error";
  if (signals.some((signal) => signal.blocked || signal.status === "risk")) return "risk";
  if (signals.length) return "complete";
  return "idle";
}

function getFlowStageStatus(methods, signalById, livePhase) {
  const stageState = getFlowStageState(methods, signalById, livePhase);
  return { running: "检测中", complete: "已检测", risk: "风险已标记", error: "异常" }[stageState]
    ?? (methods.some((method) => state.selectedDefenseIds.includes(method.id)) ? "待运行" : "未启用");
}

function phaseMatchesDefense(phase, defenseId) {
  if (phase === "input_guard") return DEFENSES.some(
    (defense) => defense.id === defenseId && defense.phase === "input",
  );
  return false;
}

function highValueExposures(result = {}) {
  return (result.asset_exposures ?? []).filter((item) => HIGH_VALUE_EXPOSURE_KINDS.has(item.kind));
}

function highValueExposureKindLabel(kind) {
  return HIGH_VALUE_EXPOSURE_LABELS[kind] ?? kind;
}

function renderHighValueExposures(result = {}) {
  if (!elements.highValueExposureList) return;
  // Keep the detailed comparison below as the single place for trace
  // inspection. The separate high-value summary block is intentionally
  // hidden to avoid duplicating leakage wording in the drawer.
  if (elements.highValueExposureSection) elements.highValueExposureSection.hidden = true;
  const exposures = highValueExposures(result);
  const delivered = exposures.filter((item) => item.exposed_to_client);
  const detected = exposures.filter((item) => item.exposed_in_output && !item.exposed_to_client);
  const hasResult = Boolean(result.run_id || result.verdict || result.attack);
  const stateClass = delivered.length ? "leaked" : detected.length ? "detected" : hasResult ? "safe" : "idle";

  elements.highValueExposureIntro.dataset.state = stateClass;
  elements.highValueExposureStatus.dataset.status = delivered.length ? "risk" : detected.length ? "detected" : hasResult ? "safe" : "";
  elements.highValueExposureStatus.textContent = delivered.length
    ? `${delivered.length} 项已泄漏`
    : detected.length
      ? `${detected.length} 项已拦截`
      : hasResult
        ? "未发现泄漏"
        : "等待运行";
  elements.highValueExposureHeadline.textContent = delivered.length
    ? "关键内容已到达客户端"
    : detected.length
      ? "模型输出命中高价值资产"
      : hasResult
        ? "高价值资产未泄漏"
        : "等待本轮关键资产检测";
  elements.highValueExposureDetail.textContent = delivered.length
    ? "以下内容来自 System Prompt 或 RAG 私有知识，已越过交付边界；原始正文仍按证据最小化原则呈现。"
    : detected.length
      ? "检测到模型输出命中高价值资产，但交付边界已拦截，客户端未收到正文。"
      : "RAG 与 System Prompt 只展示泄漏证据，不复制私有正文。";

  const visible = exposures.filter((item) => item.exposed_in_output || item.exposed_to_client);
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = hasResult
      ? "本轮没有检测到 System Prompt 或 RAG 关键内容泄漏。"
      : "运行一次窃取测试后，这里会高亮到达客户端的关键内容。";
    elements.highValueExposureList.replaceChildren(empty);
    return;
  }

  const ragTerms = [...new Set(
    (result.rag_trace ?? [])
      .filter((item) => item.visibility === "private")
      .flatMap((item) => item.matched_terms ?? [])
      .map(String)
      .filter(Boolean),
  )];
  elements.highValueExposureList.replaceChildren(...visible.map((item) => highValueExposureCard(item, ragTerms)));
}

function highValueExposureCard(item, ragTerms = []) {
  const delivered = Boolean(item.exposed_to_client);
  const detected = Boolean(item.exposed_in_output);
  const card = document.createElement("article");
  card.className = `high-value-exposure-card ${delivered ? "leaked" : detected ? "detected" : "protected"}`;

  const header = document.createElement("header");
  const kind = document.createElement("span");
  kind.className = "high-value-exposure-kind";
  kind.textContent = highValueExposureKindLabel(item.kind);
  const flag = document.createElement("b");
  flag.textContent = "关键内容";
  header.append(kind, flag);

  const title = document.createElement("strong");
  title.textContent = item.label || "未命名高价值资产";

  const evidence = document.createElement("small");
  const coverage = Number.isFinite(Number(item.coverage)) ? `${Number(item.coverage)}%` : "—";
  const contiguous = Number.isFinite(Number(item.max_contiguous_chars)) ? `${Number(item.max_contiguous_chars)} 字符` : "—";
  const marker = item.exact_marker_match ? "精确标记命中" : "片段/语义命中";
  const ragEvidence = item.kind === "rag" && ragTerms.length ? ` · 检索命中词 ${ragTerms.slice(0, 5).join("、")}` : "";
  evidence.textContent = `覆盖 ${coverage} · 连续命中 ${contiguous} · ${marker}${ragEvidence}`;

  const status = document.createElement("em");
  status.textContent = delivered ? "已到达客户端" : detected ? "输出命中 · 已拦截" : "未交付";
  card.append(header, title, evidence, status);
  return card;
}

function renderPromptComparison(result = null) {
  const section = elements.promptCompareSection;
  if (!section) return;
  if (!result) {
    section.hidden = true;
    state.promptCompareResult = null;
    state.promptCompareTranslatedOutput = "";
    state.promptCompareTranslationError = "";
    return;
  }

  if (state.promptCompareResult !== result) {
    state.promptCompareResult = result;
    state.promptCompareTranslatedOutput = "";
    state.promptCompareTranslationError = "";
  }
  const rawOutput = String(result.assistant_message ?? "").trim();
  const translatedOutput = state.promptCompareTranslatedOutput.trim();
  const output = translatedOutput || rawOutput;
  const source = state.systemPrompt.trim();
  const sourceReady = Boolean(source);
  const matches = findPromptMatches(output, source);
  const outputLabel = translatedOutput ? "已翻译为中文" : "原始输出";
  const sourceLabel = sourceReady ? `固定配置 · ${source.length} 字符` : "System Prompt 加载中";

  section.hidden = false;
  elements.promptCompareTitle.textContent = "模型真实输出与系统提示词的对照";
  elements.promptCompareSourcePane.hidden = false;
  elements.promptCompareLegend.hidden = false;
  elements.promptCompareOutputLabel.textContent = outputLabel;
  elements.promptCompareSourceLabel.textContent = sourceLabel;
  elements.promptCompareStatus.textContent = state.promptCompareTranslating
    ? "翻译中…"
    : state.promptCompareTranslationError
      || (matches.left.length ? `发现 ${matches.left.length} 段连续相似内容` : translatedOutput ? "已生成中文译文 · 未发现连续匹配" : "未发现连续匹配");
  elements.promptCompareStatus.dataset.status = state.promptCompareTranslationError
    ? "error"
    : matches.left.length ? "risk" : "";
  elements.promptCompareTranslateButton.disabled = !rawOutput || state.promptCompareTranslating;
  elements.promptCompareTranslateButton.textContent = state.promptCompareTranslating
    ? "翻译中…"
    : translatedOutput
      ? "显示原文"
      : "翻译为中文";
  renderPromptCompareText(elements.promptCompareOutput, output, matches.left);
  renderPromptCompareText(elements.promptCompareSource, sourceReady ? source : "System Prompt 尚未加载", matches.right);
}

function renderPromptCompareText(container, text, ranges) {
  if (!container) return;
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const [start, end] of ranges) {
    if (start > cursor) fragment.append(document.createTextNode(text.slice(cursor, start)));
    const mark = document.createElement("mark");
    mark.textContent = text.slice(start, end);
    fragment.append(mark);
    cursor = end;
  }
  if (cursor < text.length) fragment.append(document.createTextNode(text.slice(cursor)));
  container.replaceChildren(fragment);
}

function findPromptMatches(left, right, minLength = 8) {
  const leftText = String(left ?? "");
  const rightText = String(right ?? "");
  if (leftText.length < minLength || rightText.length < minLength) return { left: [], right: [] };

  // Index fixed-size seeds in the System Prompt first. The two sides are
  // collected independently below: a matching phrase is highlighted wherever
  // it occurs, even when the output and the source use a different order.
  const seedPositions = new Map();
  for (let index = 0; index <= rightText.length - minLength; index += 1) {
    const seed = rightText.slice(index, index + minLength);
    const positions = seedPositions.get(seed) ?? [];
    if (positions.length < 8) positions.push(index);
    seedPositions.set(seed, positions);
  }

  const leftRanges = [];
  const rightRanges = [];
  for (let index = 0; index <= leftText.length - minLength; index += 1) {
    const positions = seedPositions.get(leftText.slice(index, index + minLength));
    if (!positions) continue;
    for (const otherIndex of positions) {
      let length = minLength;
      while (
        index + length < leftText.length
        && otherIndex + length < rightText.length
        && leftText[index + length] === rightText[otherIndex + length]
      ) {
        length += 1;
      }
      leftRanges.push([index, index + length]);
      rightRanges.push([otherIndex, otherIndex + length]);
    }
  }

  return {
    left: mergePromptRanges(leftRanges.sort((a, b) => a[0] - b[0])),
    right: mergePromptRanges(rightRanges.sort((a, b) => a[0] - b[0])),
  };
}

function mergePromptRanges(ranges) {
  const merged = [];
  for (const range of ranges) {
    const previous = merged[merged.length - 1];
    if (previous && range[0] <= previous[1]) {
      previous[1] = Math.max(previous[1], range[1]);
    } else {
      merged.push([...range]);
    }
  }
  return merged;
}

async function translatePromptCompareOutput() {
  const result = state.promptCompareResult;
  const rawOutput = String(result?.assistant_message ?? "").trim();
  if (!result || !rawOutput) return;
  if (state.promptCompareTranslatedOutput) {
    state.promptCompareTranslatedOutput = "";
    state.promptCompareTranslationError = "";
    renderPromptComparison(result);
    return;
  }
  if (state.promptCompareTranslating) return;
  state.promptCompareTranslating = true;
  renderPromptComparison(result);
  try {
    const translated = await api.translateToChinese(rawOutput);
    const content = String(translated?.content ?? "").trim();
    if (!content) throw new Error("翻译结果为空");
    state.promptCompareTranslatedOutput = content;
    state.promptCompareTranslationError = "";
  } catch (error) {
    state.promptCompareTranslationError = error?.message || "输出翻译失败";
  } finally {
    state.promptCompareTranslating = false;
    renderPromptComparison(result);
  }
}

const RAG_SEARCH_TOOL_NAMES = new Set([
  "search_knowledge_base",
  "search_financial_knowledge",
  "search_legal_corpus",
]);

function renderRagRetrievalDetails(result = {}) {
  const ragItems = [...(result.rag_trace ?? [])]
    .sort((left, right) => (left.rank ?? 999) - (right.rank ?? 999));
  const retrievalExecuted = ragItems.length > 0 || (result.tool_trace ?? []).some(
    (tool) => RAG_SEARCH_TOOL_NAMES.has(tool.name),
  );
  const hit = ragItems.length > 0;

  elements.ragRetrievalCount.textContent = `${ragItems.length} 条`;
  elements.ragRetrievalSummary.dataset.status = hit ? "hit" : "miss";
  elements.ragRetrievalHit.textContent = hit ? "是" : "否";
  elements.ragRetrievalStatus.textContent = hit
    ? `命中 ${ragItems.length} 条知识片段`
    : retrievalExecuted
      ? "没有片段达到检索阈值"
      : "本轮未执行 BM25 检索";

  if (!hit) {
    renderEmpty(
      elements.ragRetrievalList,
      retrievalExecuted ? "本轮 BM25 检索未命中。" : "本轮 Agent 没有调用 RAG 检索。",
    );
    return;
  }

  elements.ragRetrievalList.replaceChildren(...ragItems.map((item) => {
    const card = document.createElement("article");
    card.className = "rag-retrieval-item";

    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = item.heading ? `${item.title} · ${item.heading}` : item.title;
    const score = document.createElement("em");
    score.textContent = `BM25 ${formatRagScore(item.score)}`;
    score.title = "BM25 原始分数";
    header.append(title, score);

    const meta = document.createElement("small");
    const matchedTerms = (item.matched_terms ?? []).length
      ? `匹配词：${item.matched_terms.join("、")}`
      : "无直接词项命中";
    const decision = item.decision ? ` · ${item.decision}` : "";
    meta.textContent = `Top-${item.rank ?? "?"} · ${item.chunk_id ?? item.id} · ${matchedTerms}${decision}`;

    const preview = document.createElement("p");
    preview.textContent = item.preview || "该片段未提供内容预览。";
    card.append(header, meta, preview);
    return card;
  }));
}

function renderRagProtection(result) {
  const ragItems = result.rag_trace ?? [];
  const privateItems = ragItems.filter((item) => item.visibility === "private");
  const includedPrivate = privateItems.filter((item) => item.included).length;
  const ragExposure = (result.asset_exposures ?? []).find((item) => item.kind === "rag");
  const leaked = Boolean(ragExposure?.exposed_to_client);
  const blocked = Boolean(result.output_blocked || result.attack?.blocked_stage);
  const status = leaked ? "已暴露" : blocked && includedPrivate === 0 ? "已保护" : includedPrivate ? "已检索" : "未命中";
  const retrieval = includedPrivate ? `${includedPrivate} 个` : blocked ? "未执行" : "0 个";
  const leakage = leaked ? "已发现" : "无";
  const blockedStage = result.attack?.blocked_stage
    ? result.attack.blocked_stage === "input" ? "生成前" : result.attack.blocked_stage
    : "—";
  const inputRisk = (result.defense_signals ?? []).some((signal) => signal.status === "risk");
  elements.ragProtectionStatus.textContent = status;
  elements.ragProtectionStatus.dataset.status = leaked ? "risk" : status === "已保护" ? "safe" : "";
  elements.ragProtectionGrid.replaceChildren(
    metricCard("私有片段", retrieval, leaked ? "risk" : status === "已保护" ? "safe" : ""),
    metricCard("关键规则泄漏", leakage, leaked ? "risk" : "safe"),
    metricCard("检索状态", includedPrivate ? "已进入上下文" : blocked ? "未执行" : "未命中", leaked ? "risk" : status === "已保护" ? "safe" : ""),
    metricCard("检测动作", blocked ? blockedStage : inputRisk ? "风险标记" : "旁路观察", inputRisk ? "risk" : ""),
  );
  renderRagProtectionStory({
    status,
    leaked,
    blocked,
    includedPrivate,
  });
  renderRagReplaySnapshot(result);
  renderProtectedRagContent(result);
}

function renderRagProtectionStory({ status = "等待运行", leaked = false, blocked = false, includedPrivate = 0 } = {}) {
  if (!elements.ragProtectionStory) return;
  const running = status === "运行中";
  const storyState = status === "运行中"
    ? "running"
    : leaked
      ? "risk"
      : blocked
        ? includedPrivate ? "protected" : "preblocked"
        : includedPrivate
          ? "contained"
          : "idle";
  elements.ragProtectionStory.dataset.state = storyState;
  elements.ragPrivateAssetCount.textContent = running ? "正在查询私有索引" : includedPrivate ? `${includedPrivate} 个私有片段被召回` : blocked ? "未访问私有索引" : "未召回私有片段";
  elements.ragGateLabel.textContent = leaked ? "检测到内容越界" : blocked ? "攻击已拦截" : includedPrivate ? "未见正文泄露" : running ? "正在判定" : "等待请求";
  elements.ragClientLabel.textContent = leaked ? "收到敏感内容" : blocked ? "敏感内容 0 字节" : includedPrivate ? "仅收到业务答案" : running ? "等待安全结果" : "尚未交付";

  const copy = leaked
    ? {
      message: "私有知识穿过交付边界，攻击者可反复调用并重建知识库。",
      title: "RAG 资产已泄露",
      detail: "泄露的不只是一段回答，而是可批量复制的业务规则、内部政策与专有知识。",
    }
    : blocked
      ? {
        message: includedPrivate ? "检索可用于内部决策，但私有片段在交付边界前被截住。" : "风险请求在访问知识库之前被拦截。",
        title: "私有知识未到达客户端",
        detail: includedPrivate ? "Agent 保留检索能力，同时避免原始知识片段成为攻击者的下载接口。" : "攻击者没有获得检索机会，私有索引和模型上下文均未暴露。",
      }
      : includedPrivate
        ? {
          message: "私有知识参与内部回答，客户端只接收收敛后的业务结果。",
          title: "检索能力与知识交付已分离",
          detail: "让 Agent 使用知识，不等于允许用户复制知识库原文。",
        }
        : {
          message: "RAG 不只是检索，检索结果也需要被保护。",
          title: "知识库也是核心资产",
          detail: "一次批量抽取就可能复制业务规则、内部政策和专有知识。",
        };
  elements.ragProtectionMessage.textContent = copy.message;
  elements.ragImpactTitle.textContent = copy.title;
  elements.ragImpactDetail.textContent = copy.detail;
}

function ragReplayData(result = {}) {
  const searchToolNames = new Set(["search_knowledge_base", "search_financial_knowledge", "search_legal_corpus"]);
  const tool = (result.tool_trace ?? []).find(
    (item) => searchToolNames.has(item.name) && item.metadata?.replay_schema === "bm25.retrieval.v1",
  ) ?? (result.tool_trace ?? []).find((item) => searchToolNames.has(item.name));
  const metadata = tool?.metadata ?? {};
  const items = [...(result.rag_trace ?? [])]
    .filter((item) => item.included)
    .sort((left, right) => (left.rank ?? 999) - (right.rank ?? 999));
  const query = String(metadata.retrieval_query ?? tool?.arguments?.query ?? "").trim();
  const queryTokens = Array.isArray(metadata.query_tokens)
    ? metadata.query_tokens.map(String)
    : Array.from(new Set(items.flatMap((item) => item.matched_terms ?? [])));
  return {
    available: Boolean(tool && (query || items.length)),
    query,
    queryTokens,
    items,
    metadata,
  };
}

function renderRagReplaySnapshot(result = {}) {
  if (!elements.ragProtectionStory) return;
  const replay = ragReplayData(result);
  state.ragReplayToken += 1;
  delete elements.ragProtectionStory.dataset.replayStep;
  elements.ragProtectionStory.dataset.replaying = "false";
  setRagReplayButton(replay.available ? "重放检索" : "本轮无检索", !replay.available, false);
  elements.ragReplayState.textContent = replay.available ? "真实运行快照" : "等待本轮检索";
  elements.ragReplayQuery.textContent = replay.query || "本轮没有调用金融知识库检索，BM25 未执行。";
  renderRagReplayTokens(replay.queryTokens);
  elements.ragReplayIndexMeta.textContent = formatRagReplayIndexMeta(replay.metadata);
  renderRagReplayRanking(replay.items);
}

function renderRagReplayTokens(tokens = []) {
  if (!tokens.length) {
    const empty = document.createElement("span");
    empty.textContent = "没有生成查询词";
    elements.ragReplayTokens.replaceChildren(empty);
    return;
  }
  elements.ragReplayTokens.replaceChildren(...tokens.map((token) => {
    const pill = document.createElement("b");
    pill.textContent = token;
    return pill;
  }));
}

function formatRagReplayIndexMeta(metadata = {}) {
  if (!metadata.replay_schema) return "BM25Okapi · jieba_search · 本轮未执行";
  const corpus = Number.isFinite(Number(metadata.corpus_chunks)) ? `${metadata.corpus_chunks} chunks` : "— chunks";
  const topK = Number.isFinite(Number(metadata.top_k)) ? `Top-${metadata.top_k}` : "Top-K";
  return `BM25Okapi · jieba_search · ${corpus} · ${topK} · k1=${metadata.k1 ?? "—"} · b=${metadata.b ?? "—"} · min=${metadata.min_score ?? "—"}`;
}

function renderRagReplayRanking(items = [], visibleCount = items.length) {
  if (!items.length || visibleCount === 0) {
    const empty = document.createElement("p");
    empty.textContent = items.length ? "正在计算全部 chunk 的相关性分数…" : "本轮没有召回达到阈值的知识片段";
    elements.ragReplayRanking.replaceChildren(empty);
    return;
  }
  const maxScore = Math.max(...items.map((item) => Number(item.score) || 0), 0.000001);
  elements.ragReplayRanking.replaceChildren(
    ...items.slice(0, visibleCount).map((item) => ragRankingItem(item, maxScore)),
  );
}

function ragRankingItem(item, maxScore) {
  const card = document.createElement("article");
  card.className = `rag-rank-item ${item.visibility ?? "public"}`;

  const rank = document.createElement("b");
  rank.textContent = String(item.rank ?? "—").padStart(2, "0");

  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.heading ? `${item.title} · ${item.heading}` : item.title;
  const details = document.createElement("small");
  const matched = (item.matched_terms ?? []).length ? `命中：${item.matched_terms.join(" / ")}` : "无直接词项命中";
  details.textContent = `${item.chunk_id ?? item.id} · ${matched}`;
  const bar = document.createElement("span");
  bar.className = "rag-rank-score-bar";
  const fill = document.createElement("i");
  fill.style.width = `${Math.max(4, ((Number(item.score) || 0) / maxScore) * 100)}%`;
  bar.append(fill);
  copy.append(title, details, bar);

  const score = document.createElement("em");
  score.textContent = formatRagScore(item.score);
  score.title = "BM25 原始分数";
  card.append(rank, copy, score);
  return card;
}

function renderProtectedRagContent(result = {}) {
  if (!elements.ragProtectedPanel) return;
  const privateItems = (result.rag_trace ?? []).filter((item) => item.visibility === "private" && item.included);
  const ragExposure = (result.asset_exposures ?? []).find((item) => item.kind === "rag");
  const ragAttackBlocked = result.attack?.attack_id === "rag_extraction" && Boolean(result.attack?.blocked_stage);
  const leaked = Boolean(ragExposure?.exposed_to_client);
  const protectedItems = privateItems.length
    ? privateItems
    : ragAttackBlocked && ragExposure
      ? [{ title: ragExposure.label, chunk_id: "检索前阻断", matched_terms: [], content_chars: 0 }]
      : [];

  elements.ragProtectedPanel.dataset.status = leaked ? "leaked" : protectedItems.length ? "protected" : "idle";
  elements.ragProtectedTitle.textContent = leaked ? "本轮泄露了什么" : protectedItems.length ? "本轮保护了什么" : "本轮私有资产";
  elements.ragProtectedCount.textContent = `${protectedItems.length} 项`;
  if (!protectedItems.length) {
    const empty = document.createElement("p");
    empty.textContent = "本轮没有访问私有知识片段。";
    elements.ragProtectedContentList.replaceChildren(empty);
    return;
  }

  elements.ragProtectedContentList.replaceChildren(...protectedItems.map((item) => {
    const card = document.createElement("article");
    card.className = leaked ? "leaked" : "protected";
    const icon = document.createElement("span");
    icon.textContent = leaked ? "!" : "✓";
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.heading ? `${item.title} · ${item.heading}` : item.title;
    const detail = document.createElement("small");
    const terms = (item.matched_terms ?? []).length ? `匹配词 ${item.matched_terms.join("、")}` : "未进入检索索引";
    const size = item.content_chars ? ` · 私有片段 ${item.content_chars} 字符` : "";
    detail.textContent = `${item.chunk_id ?? item.id} · ${terms}${size}`;
    copy.append(title, detail);
    const status = document.createElement("em");
    status.textContent = leaked ? "已到达客户端" : privateItems.length ? "正文未交付" : "检索前保护";
    card.append(icon, copy, status);
    return card;
  }));
}

async function replayRagRetrieval(result) {
  if (!elements.ragProtectionStory) return;
  const replay = ragReplayData(result);
  if (!replay.available) return;
  const replayToken = state.ragReplayToken + 1;
  state.ragReplayToken = replayToken;
  elements.ragProtectionStory.dataset.replaying = "true";
  setRagReplayButton("正在重放", true, true);

  elements.ragProtectionStory.dataset.replayStep = "query";
  elements.ragReplayState.textContent = "01 · 捕获工具查询";
  elements.ragReplayQuery.textContent = replay.query || "未记录检索表达式";
  elements.ragReplayTokens.replaceChildren();
  renderRagReplayRanking(replay.items, 0);
  if (!(await ragReplayDelay(700, replayToken))) return;

  elements.ragProtectionStory.dataset.replayStep = "tokenize";
  elements.ragReplayState.textContent = "02 · jieba_search 分词";
  const tokenNodes = [];
  for (const token of replay.queryTokens) {
    const pill = document.createElement("b");
    pill.textContent = token;
    tokenNodes.push(pill);
    elements.ragReplayTokens.replaceChildren(...tokenNodes);
    if (!(await ragReplayDelay(90, replayToken))) return;
  }
  if (!(await ragReplayDelay(450, replayToken))) return;

  elements.ragProtectionStory.dataset.replayStep = "rank";
  elements.ragReplayState.textContent = "03 · 计算 BM25 原始分数";
  for (let index = 1; index <= replay.items.length; index += 1) {
    renderRagReplayRanking(replay.items, index);
    if (!(await ragReplayDelay(360, replayToken))) return;
  }
  if (!(await ragReplayDelay(900, replayToken))) return;

  const leaked = Boolean((result.asset_exposures ?? []).find((item) => item.kind === "rag")?.exposed_to_client);
  elements.ragProtectionStory.dataset.replayStep = "delivery";
  elements.ragReplayState.textContent = leaked ? "04 · 私有正文越过交付边界" : "04 · 私有正文停留在服务端";
  if (!(await ragReplayDelay(1600, replayToken))) return;

  if (state.ragReplayToken !== replayToken) return;
  elements.ragProtectionStory.dataset.replayStep = "done";
  elements.ragProtectionStory.dataset.replaying = "false";
  elements.ragReplayState.textContent = leaked ? "重放完成 · 发现泄露" : "重放完成 · 交付边界安全";
  setRagReplayButton("再次重放", false, false);
}

function setRagReplayButton(label, disabled, running) {
  const icon = document.createElement("span");
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = running ? "●" : "▶";
  elements.ragReplayButton.replaceChildren(icon, document.createTextNode(` ${label}`));
  elements.ragReplayButton.disabled = disabled;
}

function ragReplayDelay(milliseconds, replayToken) {
  return new Promise((resolve) => {
    window.setTimeout(() => resolve(state.ragReplayToken === replayToken), milliseconds);
  });
}

function metricCard(label, value, stateClass = "") {
  const card = document.createElement("div");
  if (stateClass) card.classList.add(stateClass);
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  card.append(labelNode, valueNode);
  return card;
}

function renderSignals(signals) {
  elements.signalCount.textContent = String(signals.length);
  if (!signals.length) {
    renderEmpty(elements.signalList, "本轮未执行防护方法。");
    return;
  }
  elements.signalList.replaceChildren(...signals.map(guardRawOutputItem));
}

function guardRawOutputItem(signal) {
  const stateClass = signal.blocked ? "blocked" : signal.status;
  const card = document.createElement("article");
  card.className = `guard-raw-card ${stateClass}`;

  const header = document.createElement("header");
  const heading = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = defenseName(signal.defense_id);
  heading.append(title);
  const verdict = document.createElement("em");
  verdict.textContent = signal.blocked ? "已阻断" : SIGNAL_STATUS[signal.status] ?? signal.status;
  header.append(heading, verdict);

  const facts = document.createElement("div");
  const showsRiskTypes = signal.defense_id === "activation_probe";
  facts.className = `guard-risk-results${showsRiskTypes ? "" : " single"}`;
  const perRisk = signal.metadata?.per_risk ?? {};
  const riskResults = showsRiskTypes ? PROBE_RISK_LABELS : [["overall", "是否命中"]];
  riskResults.forEach(([riskId, label]) => {
    const flagged = showsRiskTypes
      ? typeof perRisk[riskId]?.flagged === "boolean" ? perRisk[riskId].flagged : null
      : signal.blocked || signal.status === "risk" ? true : signal.status === "safe" ? false : null;
    const fact = document.createElement("span");
    fact.dataset.status = flagged === true ? "hit" : flagged === false ? "safe" : "unknown";
    const key = document.createElement("small");
    key.textContent = label;
    const content = document.createElement("b");
    content.textContent = flagged === true ? "已命中" : flagged === false ? "未命中" : "未检测";
    fact.append(key, content);
    facts.append(fact);
  });

  const raw = document.createElement("details");
  raw.className = "guard-raw-output";
  const summary = document.createElement("summary");
  summary.textContent = "查看检测器原始输出";
  const pre = document.createElement("pre");
  pre.textContent = formatGuardRawOutput(signal.raw_output);
  raw.append(summary, pre);
  card.append(header, facts, raw);
  return card;
}

function formatGuardRawOutput(rawOutput) {
  if (!rawOutput) return "（检测器未返回原始输出）";
  try {
    return JSON.stringify(JSON.parse(rawOutput), null, 2);
  } catch {
    return String(rawOutput);
  }
}

function formatRagScore(score) {
  const numeric = Number(score);
  return Number.isFinite(numeric) ? numeric.toFixed(3) : "—";
}

function renderEmpty(container, message) {
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = message;
  container.replaceChildren(empty);
}

function resetTurnInspector() {
  elements.runId.textContent = "—";
  setFlowBadge("运行中", "running");
  renderSecurityFlow([], "input_guard");
  renderHighValueExposures();
  state.promptCompareResult = null;
  state.promptCompareTranslatedOutput = "";
  state.promptCompareTranslating = false;
  state.promptCompareTranslationError = "";
  renderPromptComparison();
  elements.ragRetrievalCount.textContent = "0 条";
  elements.ragRetrievalSummary.dataset.status = "idle";
  elements.ragRetrievalHit.textContent = "—";
  elements.ragRetrievalStatus.textContent = "等待本轮检索";
  renderEmpty(elements.ragRetrievalList, "正在等待本轮 RAG 检索结果。");
  elements.signalCount.textContent = "0";
  renderEmpty(elements.signalList, "防护方法正在等待本轮结果。");
}

async function openComparison(message, attackId = null) {
  if (!message || state.busy || state.comparing) return;
  state.comparing = true;
  setBusy(false);
  elements.compareInput.textContent = message;
  elements.compareSummary.textContent = "正在运行两次独立 Agent loop…";
  elements.baselineVerdict.textContent = "运行中";
  elements.defendedVerdict.textContent = "运行中";
  elements.baselineOutput.textContent = "等待模型输出…";
  elements.defendedOutput.textContent = "等待模型输出…";
  elements.baselineFacts.replaceChildren();
  elements.defendedFacts.replaceChildren();
  elements.compareDialog.showModal();

  try {
    const comparison = await api.compareTurn({
      message,
      attack_id: attackId,
      defenses: activeDefenseIds(),
      safegauge_threshold: state.safegaugeThreshold,
      model_params: { ...state.modelParams },
    });
    elements.compareSummary.textContent = comparison.effect.summary;
    renderComparisonSide(
      comparison.baseline,
      elements.baselineVerdict,
      elements.baselineOutput,
      elements.baselineFacts,
    );
    renderComparisonSide(
      comparison.defended,
      elements.defendedVerdict,
      elements.defendedOutput,
      elements.defendedFacts,
    );
  } catch (error) {
    elements.compareSummary.textContent = error?.message || "对照运行失败。";
    elements.baselineVerdict.textContent = "未完成";
    elements.defendedVerdict.textContent = "未完成";
  } finally {
    state.comparing = false;
    setBusy(false);
  }
}

function renderComparisonSide(result, verdictNode, outputNode, factsNode) {
  verdictNode.textContent = VERDICTS[result.verdict] ?? result.verdict;
  outputNode.classList.remove("markdown-body");
  const deliveredHighValue = highValueExposures(result).filter((item) => item.exposed_to_client);
  outputNode.classList.toggle("contains-high-value-leak-output", Boolean(deliveredHighValue.length));
  if (deliveredHighValue.length) {
    const notice = document.createElement("span");
    notice.className = "high-value-compare-notice";
    notice.textContent = `关键内容 · ${deliveredHighValue.map((item) => highValueExposureKindLabel(item.kind)).join(" / ")} 已到达客户端`;
    const leakedText = document.createElement("div");
    leakedText.className = "high-value-leak-text markdown-body";
    renderMarkdown(leakedText, result.assistant_message ?? "");
    outputNode.replaceChildren(notice, leakedText);
  } else {
    outputNode.classList.add("markdown-body");
    renderMarkdown(outputNode, result.assistant_message ?? "");
  }
  const facts = [
    ["输出状态", result.output_blocked ? "生成前阻断" : "已交付"],
    ["风险结果", result.attack?.success ? "已发生" : "未发生"],
    ["工具调用", `${result.tool_trace?.length ?? 0} 次`],
    ["阻断阶段", result.attack?.blocked_stage ?? "—"],
  ];
  factsNode.replaceChildren(...facts.map(([term, description]) => {
    const wrapper = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = description;
    wrapper.append(dt, dd);
    return wrapper;
  }));
}

async function resetSession() {
  if (state.busy || state.comparing) return;
  try {
    const response = await api.resetSession(state.sessionId);
    if (response?.rag) {
      state.ragConfig = response.rag;
      state.ragConfigLoaded = true;
      state.ragDocumentContents.clear();
      state.expandedRagDocumentId = null;
      renderRagConfig();
    }
  } catch {
    // Reset the local view even when the previous backend session has expired.
  }
  state.sessionId = createSessionId();
  state.lastMessage = "";
  state.lastResult = null;
  state.promptCompareResult = null;
  state.promptCompareTranslatedOutput = "";
  state.promptCompareTranslating = false;
  state.promptCompareTranslationError = "";
  state.livePhase = null;
  state.liveSignals = [];
  state.draftAttackId = null;
  closeDetailDrawer();
  elements.messageList.replaceChildren();
  elements.turnStatus.textContent = "等待消息";
  setFlowBadge("等待请求", "idle");
  elements.runId.textContent = "—";
  renderSecurityFlow();
  renderHighValueExposures();
  renderPromptComparison();
  elements.ragRetrievalCount.textContent = "0 条";
  elements.ragRetrievalSummary.dataset.status = "idle";
  elements.ragRetrievalHit.textContent = "—";
  elements.ragRetrievalStatus.textContent = "等待本轮检索";
  renderEmpty(elements.ragRetrievalList, "运行一条消息后显示 RAG 检索结果。");
  elements.signalCount.textContent = "0";
  renderEmpty(elements.signalList, "运行一条消息后显示检测结果。");
}

function activeDefenseIds() {
  return selectedDefenseIds();
}

function selectedDefenseIds() {
  const visible = new Set(visibleDefenses().map((defense) => defense.id));
  return state.selectedDefenseIds.filter(
    (id) => visible.has(id) && state.availableDefenseIds.includes(id),
  );
}

function visibleDefenses() {
  const catalog = new Set(state.catalogDefenseIds);
  return DEFENSES.filter((defense) => !defense.hidden && catalog.has(defense.id));
}

function normalizeDefenseIds(values) {
  const known = new Set(DEFENSES.map((item) => item.id));
  return Array.from(new Set(Array.isArray(values) ? values : [])).filter((id) => known.has(id));
}

function defenseName(defenseId) {
  return DEFENSES.find((item) => item.id === defenseId)?.name ?? defenseId;
}

function setBusy(busy) {
  const locked = busy || state.comparing;
  elements.sendButton.disabled = locked;
  // Keep the composer editable while the current turn is running so the next
  // message can be drafted without waiting for model generation to finish.
  elements.messageInput.disabled = false;
  elements.messageInput.setAttribute("aria-busy", String(locked));
  elements.resetSessionButton.disabled = locked;
  // Runtime configuration uses immutable per-turn snapshots, so opening or
  // editing it during generation is safe; changes apply to the next turn.
  elements.editAgentConfigButton.disabled = false;
  elements.editSystemPromptButton.disabled = false;
  elements.editRagConfigButton.disabled = false;
  elements.guardList.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.disabled = locked || input.dataset.available !== "true";
  });
  elements.starterList.querySelectorAll("button").forEach((button) => {
    button.disabled = locked;
  });
}

function resizeComposer() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 160)}px`;
}

function scrollConversation() {
  requestAnimationFrame(() => {
    elements.conversationBody.scrollTop = elements.conversationBody.scrollHeight;
  });
}

function formatTime(value) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function createSessionId() {
  if (window.crypto?.randomUUID) return `session-${window.crypto.randomUUID()}`;
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function fallbackWorkspace() {
  return {
    profile: {
      name: "银行财富管理客服",
      description: "面向终端客户回答理财产品、持仓、亏损、赎回与流动性问题",
      model: "qwen3-8b",
      tools: ["search_financial_knowledge", "lookup_client_portfolio", "check_transfer_authorization", "prepare_rebalance_proposal"],
      defense_pipeline: DEFENSES.map((item) => item.id),
    },
    conversation_starters: [],
  };
}

function agentDisplayName() {
  return state.workspace?.profile?.name || "银行财富管理客服";
}
