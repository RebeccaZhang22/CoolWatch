import { createAgentApiClient } from "./api.js?v=output-guard-config-20260722";
import {
  getFallbackAttackExamples,
  guards,
  scenarioCategories,
  scenarios,
} from "./mock-data.js?v=output-guard-config-20260722";

const QWEN_LABEL_NAMES = {
  Violent: "暴力",
  "Non-violent Illegal Acts": "违法行为",
  "Sexual Content or Sexual Acts": "色情内容",
  PII: "个人信息",
  "Suicide & Self-Harm": "自伤风险",
  "Unethical Acts": "不当行为",
  "Politically Sensitive Topics": "敏感政治",
  "Copyright Violation": "版权风险",
  Jailbreak: "越狱攻击",
};

const YIDUN_LABEL_NAMES = {
  "100": "色情",
  "200": "广告",
  "260": "广告法",
  "300": "暴恐",
  "400": "违禁",
  "500": "涉政",
  "600": "谩骂",
  "700": "灌水",
  "900": "其他",
  "1100": "价值观",
};

const defaultSystemPrompts = new Map(scenarios.map((scenario) => [scenario.id, scenario.systemPrompt]));

const elements = {
  appShell: document.querySelector("#appShell"),
  scenarioCategoryTabs: document.querySelector("#scenarioCategoryTabs"),
  scenarioPickerShell: document.querySelector("#scenarioPickerShell"),
  scenarioPickerTrigger: document.querySelector("#scenarioPickerTrigger"),
  scenarioPickerValue: document.querySelector("#scenarioPickerValue"),
  scenarioPickerMenu: document.querySelector("#scenarioPickerMenu"),
  scenarioOptionList: document.querySelector("#scenarioOptionList"),
  editPromptButton: document.querySelector("#editPromptButton"),
  editAgentConfigButton: document.querySelector("#editAgentConfigButton"),
  agentConfigModel: document.querySelector("#agentConfigModel"),
  agentConfigParams: document.querySelector("#agentConfigParams"),
  guardList: document.querySelector("#guardList"),
  securityFlow: document.querySelector("#securityFlow"),
  flowModeBadge: document.querySelector("#flowModeBadge"),
  promptEditor: document.querySelector("#promptEditor"),
  promptModalBackdrop: document.querySelector("#promptModalBackdrop"),
  promptModalTitle: document.querySelector("#promptModalTitle"),
  promptScenarioName: document.querySelector("#promptScenarioName"),
  closePromptModalButton: document.querySelector("#closePromptModalButton"),
  restorePromptButton: document.querySelector("#restorePromptButton"),
  cancelPromptButton: document.querySelector("#cancelPromptButton"),
  savePromptButton: document.querySelector("#savePromptButton"),
  agentModalBackdrop: document.querySelector("#agentModalBackdrop"),
  agentModalTitle: document.querySelector("#agentModalTitle"),
  closeAgentModalButton: document.querySelector("#closeAgentModalButton"),
  cancelAgentModalButton: document.querySelector("#cancelAgentModalButton"),
  saveAgentConfigButton: document.querySelector("#saveAgentConfigButton"),
  outputConfigModalBackdrop: document.querySelector("#outputConfigModalBackdrop"),
  closeOutputConfigModalButton: document.querySelector("#closeOutputConfigModalButton"),
  cancelOutputConfigButton: document.querySelector("#cancelOutputConfigButton"),
  saveOutputConfigButton: document.querySelector("#saveOutputConfigButton"),
  exactMatchThresholdInput: document.querySelector("#exactMatchThresholdInput"),
  exactMatchThresholdValue: document.querySelector("#exactMatchThresholdValue"),
  rougeLThresholdInput: document.querySelector("#rougeLThresholdInput"),
  rougeLThresholdValue: document.querySelector("#rougeLThresholdValue"),
  messageList: document.querySelector("#messageList"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  attackBar: document.querySelector(".attack-bar"),
  attackPickerTrigger: document.querySelector("#attackPickerTrigger"),
  attackSelectedChip: document.querySelector("#attackSelectedChip"),
  attackClearButton: document.querySelector("#attackClearButton"),
  attackPicker: document.querySelector("#attackPicker"),
  newSessionButton: document.querySelector("#newSessionButton"),
  sidebarCollapseButton: document.querySelector("#sidebarCollapseButton"),
  sidebarOpenButton: document.querySelector("#sidebarOpenButton"),
  modelSelect: document.querySelector("#modelSelect"),
  temperatureInput: document.querySelector("#temperatureInput"),
  temperatureValue: document.querySelector("#temperatureValue"),
  topPInput: document.querySelector("#topPInput"),
  topPValue: document.querySelector("#topPValue"),
  maxTokensInput: document.querySelector("#maxTokensInput"),
  maxTokensValue: document.querySelector("#maxTokensValue"),
  pageTitle: document.querySelector("#pageTitle"),
  pageSubtitle: document.querySelector("#pageSubtitle"),
  runtimeStatus: document.querySelector("#runtimeStatus"),
  drawerBackdrop: document.querySelector("#drawerBackdrop"),
  drawer: document.querySelector("#detailDrawer"),
  closeDrawerButton: document.querySelector("#closeDrawerButton"),
  drawerTitle: document.querySelector("#drawerTitle"),
  comparisonGrid: document.querySelector("#comparisonGrid"),
  metricGrid: document.querySelector("#metricGrid"),
  truthPanel: document.querySelector("#truthPanel"),
  outputPanel: document.querySelector("#outputPanel"),
  ragList: document.querySelector("#ragList"),
  toggleTruthButton: document.querySelector("#toggleTruthButton"),
  rawOutputModalBackdrop: document.querySelector("#rawOutputModalBackdrop"),
  rawOutputModalTitle: document.querySelector("#rawOutputModalTitle"),
  rawOutputModalContent: document.querySelector("#rawOutputModalContent"),
  closeRawOutputModalButton: document.querySelector("#closeRawOutputModalButton"),
};

const state = {
  sessionId: createSessionId(),
  scenarioId: scenarios[0].id,
  scenarioCategory: scenarios[0].category,
  selectedGuards: [],
  modelParams: readModelParamsFromInputs(),
  outputDetectionConfig: {
    exact_match_threshold: 80,
    rouge_l_threshold: 80,
  },
  attackExamples: selectBestAttackByCategory(getFallbackAttackExamples()),
  selectedAttackId: "",
  attackPickerOpen: false,
  scenarioPickerOpen: false,
  attackPickerTab: "",
  messages: [],
  isBusy: false,
  conversationVersion: 0,
  activeDetailMessageId: null,
  activeRawGuardId: null,
  rawOutputModalTrigger: null,
  promptModalOpen: false,
  promptModalTrigger: null,
  agentModalOpen: false,
  agentModalTrigger: null,
  outputConfigModalOpen: false,
  outputConfigModalTrigger: null,
  activeGuardDetailId: null,
  detailTruthVisible: false,
  sidebarCollapsed: false,
  flowPhase: "idle",
  flowResult: null,
  flowRound: 0,
  flowCompletedAt: null,
};

const agentApi = createAgentApiClient();

function init() {
  setSidebarCollapsed(false);
  renderGuardList();
  renderModelParams();
  renderAgentConfigSummary();
  renderOutputDetectionConfig();
  bindEvents();
  applyScenario(scenarios[0].id, { resetMessages: true });
  loadAttackExamples();
}

function bindEvents() {
  elements.chatForm.addEventListener("submit", handleSubmit);
  elements.messageInput.addEventListener("input", resizeMessageInput);
  elements.messageInput.addEventListener("keydown", handleComposerKeydown);
  [elements.modelSelect, elements.temperatureInput, elements.topPInput, elements.maxTokensInput].forEach((input) => {
    input.addEventListener("input", renderModelDraftParams);
    input.addEventListener("change", renderModelDraftParams);
  });
  elements.attackBar.addEventListener("click", (event) => {
    event.stopPropagation();
  });
  elements.newSessionButton.addEventListener("click", () => {
    startNewChat();
  });
  elements.sidebarCollapseButton.addEventListener("click", () => setSidebarCollapsed(true));
  elements.sidebarOpenButton.addEventListener("click", () => setSidebarCollapsed(false));
  elements.scenarioPickerTrigger.addEventListener("click", () => {
    setScenarioPickerOpen(!state.scenarioPickerOpen);
  });
  elements.editPromptButton.addEventListener("click", () => {
    setScenarioPickerOpen(false);
    openPromptModal(elements.scenarioPickerTrigger);
  });
  elements.editAgentConfigButton.addEventListener("click", (event) => openAgentModal(event.currentTarget));
  elements.closePromptModalButton.addEventListener("click", () => closePromptModal());
  elements.cancelPromptButton.addEventListener("click", () => closePromptModal());
  elements.savePromptButton.addEventListener("click", savePromptConfiguration);
  elements.restorePromptButton.addEventListener("click", restoreDefaultPrompt);
  elements.promptModalBackdrop.addEventListener("click", (event) => {
    if (event.target === elements.promptModalBackdrop) {
      closePromptModal();
    }
  });
  elements.closeAgentModalButton.addEventListener("click", () => closeAgentModal());
  elements.cancelAgentModalButton.addEventListener("click", () => closeAgentModal());
  elements.saveAgentConfigButton.addEventListener("click", saveAgentConfiguration);
  elements.agentModalBackdrop.addEventListener("click", (event) => {
    if (event.target === elements.agentModalBackdrop) {
      closeAgentModal();
    }
  });
  [elements.exactMatchThresholdInput, elements.rougeLThresholdInput].forEach((input) => {
    input.addEventListener("input", renderOutputDetectionDraft);
  });
  elements.closeOutputConfigModalButton.addEventListener("click", () => closeOutputConfigModal());
  elements.cancelOutputConfigButton.addEventListener("click", () => closeOutputConfigModal());
  elements.saveOutputConfigButton.addEventListener("click", saveOutputDetectionConfig);
  elements.outputConfigModalBackdrop.addEventListener("click", (event) => {
    if (event.target === elements.outputConfigModalBackdrop) {
      closeOutputConfigModal();
    }
  });
  elements.closeDrawerButton.addEventListener("click", closeDrawer);
  elements.drawerBackdrop.addEventListener("click", closeDrawer);
  elements.closeRawOutputModalButton.addEventListener("click", closeRawOutputModal);
  elements.rawOutputModalBackdrop.addEventListener("click", (event) => {
    if (event.target === elements.rawOutputModalBackdrop) {
      closeRawOutputModal();
    }
  });
  elements.toggleTruthButton.addEventListener("click", () => {
    state.detailTruthVisible = !state.detailTruthVisible;
    renderActiveDetail();
  });
  elements.attackPickerTrigger.addEventListener("click", () => {
    setAttackPickerOpen(!state.attackPickerOpen);
  });
  elements.attackClearButton.addEventListener("click", () => {
    clearSelectedAttack();
    elements.messageInput.focus();
  });
  document.addEventListener("click", (event) => {
    if (state.scenarioPickerOpen && !event.composedPath().includes(elements.scenarioPickerShell)) {
      setScenarioPickerOpen(false);
    }
  });
  document.addEventListener("click", (event) => {
    if (!state.attackPickerOpen || event.composedPath().includes(elements.attackBar)) {
      return;
    }
    setAttackPickerOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.activeRawGuardId) {
      closeRawOutputModal();
      return;
    }
    if (event.key === "Escape" && state.promptModalOpen) {
      closePromptModal();
      return;
    }
    if (event.key === "Escape" && state.agentModalOpen) {
      closeAgentModal();
      return;
    }
    if (event.key === "Escape" && state.outputConfigModalOpen) {
      closeOutputConfigModal();
      return;
    }
    if (event.key === "Escape" && state.scenarioPickerOpen) {
      setScenarioPickerOpen(false);
      elements.scenarioPickerTrigger.focus();
      return;
    }
    if (event.key === "Escape" && state.attackPickerOpen) {
      setAttackPickerOpen(false);
      elements.attackPickerTrigger.focus();
    }
  });
}

function startNewChat() {
  state.sessionId = createSessionId();
  applyScenario(state.scenarioId, { resetMessages: true });
  elements.messageInput.focus();
}

function setSidebarCollapsed(isCollapsed) {
  state.sidebarCollapsed = isCollapsed;
  elements.appShell.classList.toggle("sidebar-collapsed", isCollapsed);
  elements.sidebarCollapseButton.setAttribute("aria-expanded", String(!isCollapsed));
  elements.sidebarOpenButton.setAttribute("aria-expanded", String(!isCollapsed));
}

function handleComposerKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }

  event.preventDefault();
  if (state.isBusy) {
    return;
  }
  elements.chatForm.requestSubmit();
}

function resizeMessageInput() {
  const textarea = elements.messageInput;
  textarea.style.height = "auto";
  const computedStyle = window.getComputedStyle(textarea);
  const maxHeight = Number.parseFloat(computedStyle.maxHeight);
  const height = Number.isFinite(maxHeight) ? Math.min(textarea.scrollHeight, maxHeight) : textarea.scrollHeight;
  textarea.style.height = `${height}px`;
  textarea.style.overflowY = textarea.scrollHeight > height + 1 ? "auto" : "hidden";
}

function readModelParamsFromInputs() {
  return {
    model: elements.modelSelect.value,
    temperature: readNumberInput(elements.temperatureInput, 0.2),
    top_p: readNumberInput(elements.topPInput, 0.8),
    max_tokens: Math.round(readNumberInput(elements.maxTokensInput, 2048)),
  };
}

function readNumberInput(input, fallback) {
  const value = input.valueAsNumber;
  return Number.isFinite(value) ? value : fallback;
}

function renderModelParams() {
  elements.modelSelect.value = state.modelParams.model;
  elements.temperatureInput.value = String(state.modelParams.temperature);
  elements.topPInput.value = String(state.modelParams.top_p);
  elements.maxTokensInput.value = String(state.modelParams.max_tokens);
  renderModelDraftParams();
}

function renderModelDraftParams() {
  const draft = readModelParamsFromInputs();
  elements.temperatureValue.textContent = draft.temperature.toFixed(1);
  elements.topPValue.textContent = draft.top_p.toFixed(1);
  elements.maxTokensValue.textContent = String(draft.max_tokens);
  renderRangeProgress(elements.temperatureInput);
  renderRangeProgress(elements.topPInput);
}

function renderAgentConfigSummary() {
  const params = state.modelParams;
  elements.agentConfigModel.textContent = params.model;
  elements.agentConfigParams.textContent = `Temperature ${params.temperature.toFixed(1)} · Top P ${params.top_p.toFixed(1)} · Max ${params.max_tokens}`;
}

function renderOutputDetectionConfig() {
  elements.exactMatchThresholdInput.value = String(state.outputDetectionConfig.exact_match_threshold);
  elements.rougeLThresholdInput.value = String(state.outputDetectionConfig.rouge_l_threshold);
  renderOutputDetectionDraft();
}

function renderOutputDetectionDraft() {
  const exactMatchThreshold = Math.round(readNumberInput(elements.exactMatchThresholdInput, 80));
  const rougeLThreshold = Math.round(readNumberInput(elements.rougeLThresholdInput, 80));
  elements.exactMatchThresholdValue.textContent = `${exactMatchThreshold}%`;
  elements.rougeLThresholdValue.textContent = `${rougeLThreshold}%`;
  renderRangeProgress(elements.exactMatchThresholdInput);
  renderRangeProgress(elements.rougeLThresholdInput);
}

function renderRangeProgress(input) {
  const min = Number(input.min || 0);
  const max = Number(input.max || 100);
  const value = readNumberInput(input, min);
  const progress = max > min ? ((value - min) / (max - min)) * 100 : 0;
  input.style.setProperty("--range-progress", `${Math.max(0, Math.min(100, progress))}%`);
}

function renderScenarioCategories() {
  elements.scenarioCategoryTabs.innerHTML = scenarioCategories
    .map(
      (category) => `
        <button class="scenario-type-button ${category.id === state.scenarioCategory ? "active" : ""}"
          data-scenario-category="${category.id}" type="button" aria-pressed="${category.id === state.scenarioCategory}">
          <strong>${escapeHtml(category.name)}</strong>
          <span>${escapeHtml(category.summary)}</span>
        </button>
      `,
    )
    .join("");

  elements.scenarioCategoryTabs.querySelectorAll("[data-scenario-category]").forEach((button) => {
    button.addEventListener("click", () => {
      const categoryId = button.dataset.scenarioCategory;
      if (categoryId === state.scenarioCategory) {
        return;
      }

      const firstScenario = getScenariosByCategory(categoryId)[0] ?? scenarios[0];
      state.scenarioCategory = categoryId;
      applyScenario(firstScenario.id, { resetMessages: true });
    });
  });
}

function renderScenarioSelect() {
  const scenarioOptions = getScenariosByCategory(state.scenarioCategory);
  const currentScenario = getCurrentScenario();
  elements.scenarioPickerValue.textContent = currentScenario.name;
  elements.scenarioOptionList.innerHTML = scenarioOptions
    .map(
      (scenario) => `
        <button class="scenario-option ${scenario.id === state.scenarioId ? "active" : ""}"
          data-scenario-id="${escapeHtml(scenario.id)}" type="button" role="option"
          aria-selected="${scenario.id === state.scenarioId}">
          <span>${escapeHtml(scenario.name)}</span>
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="m3 8 3 3 7-7"></path></svg>
        </button>
      `,
    )
    .join("");

  elements.scenarioOptionList.querySelectorAll("[data-scenario-id]").forEach((button) => {
    button.addEventListener("click", () => {
      setScenarioPickerOpen(false);
      if (button.dataset.scenarioId !== state.scenarioId) {
        applyScenario(button.dataset.scenarioId, { resetMessages: true });
      }
      elements.scenarioPickerTrigger.focus();
    });
  });
}

function setScenarioPickerOpen(isOpen) {
  state.scenarioPickerOpen = isOpen;
  elements.scenarioPickerTrigger.classList.toggle("open", isOpen);
  elements.scenarioPickerTrigger.setAttribute("aria-expanded", String(isOpen));
  elements.scenarioPickerMenu.classList.toggle("open", isOpen);
  elements.scenarioPickerMenu.setAttribute("aria-hidden", String(!isOpen));
}

function renderGuardList() {
  elements.guardList.innerHTML = guards
    .filter((guard) => !guard.alwaysRun)
    .map(
      (guard) => `
        <article class="guard-option ${isGuardActive(guard) ? "active" : ""}">
          <div class="guard-row">
            ${renderGuardControl(guard)}
            <span class="guard-state">${escapeHtml(getGuardStateText(guard))}</span>
            <button class="guard-info-button" data-guard-detail="${guard.id}" type="button"
              aria-expanded="${state.activeGuardDetailId === guard.id}" aria-label="查看 ${escapeHtml(guard.name)} 详情">i</button>
          </div>
          ${
            state.activeGuardDetailId === guard.id
              ? `<div class="guard-detail-panel">${renderGuardDetail(guard)}</div>`
              : ""
          }
        </article>
      `,
    )
    .join("");

  const guardInputs = Array.from(elements.guardList.querySelectorAll("input"));
  syncGuardCheckboxes(guardInputs);
  window.requestAnimationFrame(() => syncGuardCheckboxes(guardInputs));

  guardInputs.forEach((input) => {
    input.addEventListener("change", () => {
      const nextGuards = Array.from(elements.guardList.querySelectorAll("input:checked")).map((item) => item.value);
      state.selectedGuards = nextGuards;
      renderGuardList();
      renderSecurityFlow();
      renderSummary();
    });
  });

  elements.guardList.querySelectorAll("[data-guard-detail]").forEach((button) => {
    button.addEventListener("click", () => {
      const guardId = button.dataset.guardDetail;
      state.activeGuardDetailId = state.activeGuardDetailId === guardId ? null : guardId;
      renderGuardList();
    });
  });
}

function syncGuardCheckboxes(inputs = Array.from(elements.guardList.querySelectorAll("input"))) {
  inputs.forEach((input) => {
    const isSelected = state.selectedGuards.includes(input.value);
    input.checked = isSelected;
    input.defaultChecked = isSelected;
  });
}

function renderGuardControl(guard) {
  if (guard.alwaysRun) {
    return `
      <div class="guard-main fixed">
        <span class="guard-fixed-dot" aria-hidden="true"></span>
        <strong>${escapeHtml(guard.name)}</strong>
      </div>
    `;
  }

  return `
    <label class="guard-main">
      <input type="checkbox" value="${escapeHtml(guard.id)}" autocomplete="off" />
      <strong>${escapeHtml(guard.name)}</strong>
    </label>
  `;
}

function renderGuardDetail(guard) {
  return `
    <p>${escapeHtml(getGuardDetailText(guard))}</p>
    <dl>
      <div>
        <dt>执行位置</dt>
        <dd>${escapeHtml(getGuardExecutionText(guard))}</dd>
      </div>
      <div>
        <dt>当前状态</dt>
        <dd>${escapeHtml(getGuardStateText(guard))}</dd>
      </div>
    </dl>
  `;
}

function isGuardActive(guard) {
  return guard.alwaysRun || state.selectedGuards.includes(guard.id);
}

function getGuardStateText(guard) {
  if (guard.alwaysRun) {
    return "固定";
  }
  return state.selectedGuards.includes(guard.id) ? "启用" : "未启用";
}

function getGuardDetailText(guard) {
  if (guard.id === "qwen_guard") {
    return "在 query 进入 Agent Loop 前运行输入检测，给出拦截建议和命中类别。";
  }
  if (guard.id === "netease_yidun") {
    return "在 query 进入 Agent Loop 前调用文本同步检测接口，给出拦截建议和命中类别。";
  }
  return guard.description;
}

function getGuardExecutionText(guard) {
  return "Agent Loop 前";
}

function renderSecurityFlow() {
  const preMethods = guards.filter((guard) => guard.stage === "pre_generation");
  const phase = state.flowPhase;
  renderFlowHeaderStatus();

  elements.securityFlow.innerHTML = `
    ${renderFlowEndpoint("input", "用户输入", "Query", phase === "idle" ? "idle" : "complete")}
    ${renderFlowConnector(getFlowConnectorState("input"))}
    ${renderFlowStage({
      id: "pre",
      eyebrow: "生成前",
      title: "输入安全检测",
      stateClass: `${getFlowStageState("pre")} ${state.selectedGuards.length ? "configured" : ""}`,
      methods: preMethods.map((guard) => renderPreGenerationMethod(guard)).join(""),
    })}
    ${renderFlowConnector(getFlowConnectorState("pre"))}
    <div class="flow-agent-node ${getFlowStageState("generation")}">
      <span class="flow-node-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M12 3v3"></path>
          <circle cx="12" cy="2.5" r="1"></circle>
          <rect x="5" y="6" width="14" height="12" rx="4"></rect>
          <path d="M8.5 18v2.5M15.5 18v2.5M5 11H3M21 11h-2"></path>
          <circle cx="9.5" cy="11.5" r="1"></circle>
          <circle cx="14.5" cy="11.5" r="1"></circle>
          <path d="M9 15h6"></path>
        </svg>
      </span>
      <span class="flow-node-copy">
        <span class="flow-node-eyebrow">Agent 生成</span>
        <strong>${escapeHtml(state.modelParams.model)}</strong>
      </span>
    </div>
    ${renderFlowConnector(getFlowConnectorState("generation"))}
    ${renderFlowStage({
      id: "post",
      eyebrow: "生成后",
      title: "输出泄露检测",
      stateClass: getFlowStageState("post"),
      methods: "",
      configurable: true,
    })}
    ${renderFlowConnector(getFlowConnectorState("post"))}
    ${renderFlowEndpoint("response", "最终响应", "Response", phase === "complete" ? "complete" : phase === "error" ? "error" : "idle")}
  `;

  elements.securityFlow.querySelector("[data-open-output-config]")?.addEventListener("click", (event) => {
    openOutputConfigModal(event.currentTarget);
  });

}

function renderFlowEndpoint(id, title, meta, stateClass) {
  return `
    <div class="flow-endpoint ${stateClass}" data-flow-node="${id}">
      <span class="flow-endpoint-dot" aria-hidden="true"></span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(meta)}</small>
    </div>
  `;
}

function renderFlowStage({ id, eyebrow, title, stateClass, methods, configurable = false }) {
  return `
    <section class="flow-stage ${stateClass} ${methods ? "" : "compact"}" data-flow-stage="${id}">
      <header class="flow-stage-header">
        <span class="flow-stage-index" aria-hidden="true">${id === "pre" ? "01" : "03"}</span>
        <span>
          <small>${escapeHtml(eyebrow)}</small>
          <strong>${escapeHtml(title)}</strong>
        </span>
        <span class="flow-stage-tools">
          <span class="flow-stage-status">${escapeHtml(getFlowStageStatusText(id))}</span>
          ${
            configurable
              ? `<button class="flow-stage-config-button" data-open-output-config type="button" aria-label="配置输出泄露检测" title="配置输出泄露检测">
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <circle cx="12" cy="12" r="3.2"></circle>
                    <path d="M19.1 13.2c.1-.4.1-.8.1-1.2s0-.8-.1-1.2l2-1.5-2-3.4-2.5 1a8 8 0 0 0-2.1-1.2L14.2 3h-4.1l-.4 2.7a8 8 0 0 0-2.1 1.2l-2.5-1-2 3.4 2 1.5A6 6 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.5-1a8 8 0 0 0 2.1 1.2l.4 2.7h4.1l.4-2.7a8 8 0 0 0 2.1-1.2l2.5 1 2-3.4-2.1-1.5Z"></path>
                  </svg>
                </button>`
              : ""
          }
        </span>
      </header>
      ${methods ? `<div class="flow-method-list">${methods}</div>` : ""}
    </section>
  `;
}

function renderPreGenerationMethod(guard) {
  const enabled = state.selectedGuards.includes(guard.id);
  const result = getFlowGuardResult(guard.id);
  const methodState = getPreMethodState(enabled, result);
  return `
    <div class="flow-method ${enabled ? "enabled" : "disabled"}" title="${escapeHtml(guard.description)}">
      <span class="flow-method-indicator" aria-hidden="true"></span>
      <span>${escapeHtml(guard.name)}</span>
      <small class="flow-method-runtime ${methodState}">${escapeHtml(getFlowMethodStatusText(methodState))}</small>
    </div>
  `;
}

function getFlowGuardResult(guardId) {
  const guardResults = state.flowResult?.guard_results ?? {};
  return guardResults[guardId] ?? Object.values(guardResults).find((result) => result?.guard_id === guardId);
}

function renderFlowHeaderStatus() {
  let text = "等待请求";
  let stateClass = "idle";
  if (["pre", "generation", "post"].includes(state.flowPhase)) {
    text = `第 ${state.flowRound} 轮 · 检测中`;
    stateClass = "running";
  } else if (state.flowPhase === "complete") {
    text = `最近一轮 · ${formatTime(state.flowCompletedAt ?? new Date())}`;
    stateClass = "complete";
  } else if (state.flowPhase === "error") {
    text = `第 ${state.flowRound} 轮 · 异常`;
    stateClass = "error";
  }
  elements.flowModeBadge.className = `flow-mode-badge ${stateClass}`;
  elements.flowModeBadge.textContent = text;
}

function renderFlowConnector(stateClass) {
  return `<div class="flow-connector ${stateClass}" aria-hidden="true"><span></span></div>`;
}

function getFlowStageState(stage) {
  const phaseOrder = { idle: 0, pre: 1, generation: 2, post: 3, complete: 4, error: 4 };
  const stageOrder = { pre: 1, generation: 2, post: 3 };
  if (state.flowPhase === "error") {
    return stageOrder[stage] <= phaseOrder[state.flowPhase] ? "error" : "idle";
  }
  if (state.flowPhase === stage) {
    return "running";
  }
  if (stage === "pre" && state.flowResult && ["post", "complete"].includes(state.flowPhase)) {
    const selectedResults = state.selectedGuards.map((guardId) => getFlowGuardResult(guardId)).filter(Boolean);
    if (selectedResults.some((result) => !result.connected || result.status === "检测失败")) {
      return "error";
    }
    if (selectedResults.some((result) => result.blocked || result.query_risk === true)) {
      return "risk";
    }
    return "complete";
  }
  if (stage === "post" && state.flowPhase === "complete" && state.flowResult) {
    if (state.flowResult.leakage_summary === "发现泄露") {
      return "danger";
    }
    return "complete";
  }
  if (phaseOrder[state.flowPhase] > stageOrder[stage]) {
    return "complete";
  }
  return stage === "generation" ? "enabled" : "idle";
}

function getFlowConnectorState(afterStage) {
  const phaseOrder = { idle: 0, pre: 1, generation: 2, post: 3, complete: 4, error: 4 };
  const connectorOrder = { input: 1, pre: 2, generation: 3, post: 4 };
  const current = phaseOrder[state.flowPhase] ?? 0;
  if (state.flowPhase === "complete") {
    return "complete";
  }
  if (current > connectorOrder[afterStage]) {
    return "complete";
  }
  if (current === connectorOrder[afterStage]) {
    return "running";
  }
  return "idle";
}

function getFlowStageStatusText(stage) {
  const stateClass = getFlowStageState(stage);
  if (stage === "post" && state.flowResult && state.flowPhase === "complete") {
    return state.flowResult.leakage_summary ?? "检测完成";
  }
  if (stage === "pre" && !state.selectedGuards.length && ["complete", "generation", "post"].includes(state.flowPhase)) {
    return "已跳过";
  }
  if (stage === "pre" && state.flowResult && ["post", "complete"].includes(state.flowPhase)) {
    if (stateClass === "error") {
      return "检测失败";
    }
    if (stateClass === "risk") {
      return "命中风险";
    }
    return "检测通过";
  }
  if (stage === "pre" && state.selectedGuards.length && state.flowPhase === "idle") {
    return "已配置";
  }
  if (stateClass === "running") {
    return "运行中";
  }
  if (stateClass === "complete") {
    return "已完成";
  }
  if (stateClass === "error") {
    return "异常";
  }
  if (stage === "pre" && !state.selectedGuards.length) {
    return "未启用";
  }
  return "待运行";
}

function getPreMethodState(enabled, result) {
  if (!enabled) {
    return "disabled";
  }
  if (result) {
    if (!result.connected || result.status === "检测失败") {
      return "error";
    }
    if (result.blocked || result.query_risk === true) {
      return "risk";
    }
    return "passed";
  }
  if (state.flowPhase === "pre") {
    return "running";
  }
  if (["generation", "post", "complete"].includes(state.flowPhase)) {
    return "checked";
  }
  if (state.flowPhase === "error") {
    return "error";
  }
  return "idle";
}

function getFlowMethodStatusText(methodState) {
  return {
    disabled: "未启用",
    idle: "待运行",
    running: "检测中",
    checked: "已检测",
    passed: "✓ 通过",
    risk: "! 有风险",
    error: "× 失败",
  }[methodState] ?? "";
}

function openPromptModal(trigger) {
  const scenario = getCurrentScenario();
  state.promptModalOpen = true;
  state.promptModalTrigger = trigger;
  elements.promptModalTitle.textContent = `${scenario.name} · System Prompt`;
  elements.promptScenarioName.textContent = scenario.name;
  elements.promptEditor.value = scenario.systemPrompt;
  elements.promptModalBackdrop.classList.add("open");
  elements.promptModalBackdrop.setAttribute("aria-hidden", "false");
  window.requestAnimationFrame(() => elements.promptEditor.focus());
}

function closePromptModal({ restoreFocus = true } = {}) {
  if (!state.promptModalOpen) {
    return;
  }
  const trigger = state.promptModalTrigger;
  state.promptModalOpen = false;
  state.promptModalTrigger = null;
  elements.promptModalBackdrop.classList.remove("open");
  elements.promptModalBackdrop.setAttribute("aria-hidden", "true");
  if (restoreFocus && trigger?.isConnected) {
    trigger.focus();
  }
}

function savePromptConfiguration() {
  getCurrentScenario().systemPrompt = elements.promptEditor.value;
  closePromptModal();
}

function openAgentModal(trigger) {
  state.agentModalOpen = true;
  state.agentModalTrigger = trigger;
  renderModelParams();
  elements.agentModalBackdrop.classList.add("open");
  elements.agentModalBackdrop.setAttribute("aria-hidden", "false");
  window.requestAnimationFrame(() => elements.modelSelect.focus());
}

function closeAgentModal({ restoreFocus = true } = {}) {
  if (!state.agentModalOpen) {
    return;
  }
  const trigger = state.agentModalTrigger;
  state.agentModalOpen = false;
  state.agentModalTrigger = null;
  elements.agentModalBackdrop.classList.remove("open");
  elements.agentModalBackdrop.setAttribute("aria-hidden", "true");
  renderModelParams();
  if (restoreFocus && trigger?.isConnected) {
    trigger.focus();
  }
}

function saveAgentConfiguration() {
  state.modelParams = readModelParamsFromInputs();
  renderAgentConfigSummary();
  renderSecurityFlow();
  closeAgentModal();
}

function openOutputConfigModal(trigger) {
  state.outputConfigModalOpen = true;
  state.outputConfigModalTrigger = trigger;
  renderOutputDetectionConfig();
  elements.outputConfigModalBackdrop.classList.add("open");
  elements.outputConfigModalBackdrop.setAttribute("aria-hidden", "false");
  window.requestAnimationFrame(() => elements.exactMatchThresholdInput.focus());
}

function closeOutputConfigModal({ restoreFocus = true } = {}) {
  if (!state.outputConfigModalOpen) {
    return;
  }
  const trigger = state.outputConfigModalTrigger;
  state.outputConfigModalOpen = false;
  state.outputConfigModalTrigger = null;
  elements.outputConfigModalBackdrop.classList.remove("open");
  elements.outputConfigModalBackdrop.setAttribute("aria-hidden", "true");
  renderOutputDetectionConfig();
  if (restoreFocus && trigger?.isConnected) {
    trigger.focus();
  }
}

function saveOutputDetectionConfig() {
  state.outputDetectionConfig = {
    exact_match_threshold: Math.round(readNumberInput(elements.exactMatchThresholdInput, 80)),
    rouge_l_threshold: Math.round(readNumberInput(elements.rougeLThresholdInput, 80)),
  };
  closeOutputConfigModal();
}

function restoreDefaultPrompt() {
  elements.promptEditor.value = defaultSystemPrompts.get(state.scenarioId) ?? "";
  elements.promptEditor.focus();
}

function applyScenario(scenarioId, { resetMessages }) {
  setScenarioPickerOpen(false);
  state.scenarioId = scenarioId;
  const scenario = getCurrentScenario();
  state.scenarioCategory = scenario.category;

  renderScenarioCategories();
  renderScenarioSelect();
  renderAttackPicker();
  renderSecurityFlow();
  renderSummary();

  if (resetMessages) {
    resetConversation();
  }
}

async function loadAttackExamples() {
  try {
    const payload = await agentApi.listAttacks();
    const attacks = normalizeAttackExamples(payload.attacks);
    if (attacks.length) {
      state.attackExamples = attacks;
      renderAttackPicker();
    }
  } catch (error) {
    console.warn("攻击示例加载失败，使用内置兜底样例。", error);
  }
}

function renderAttackPicker() {
  const attacks = state.attackExamples;
  if (!attacks.length) {
    elements.attackSelectedChip.textContent = "暂无样例";
    elements.attackSelectedChip.classList.add("empty");
    elements.attackClearButton.hidden = true;
    elements.attackPicker.innerHTML = "";
    return;
  }

  let selectedAttack = getAttackExampleById(state.selectedAttackId);
  if (state.selectedAttackId && !selectedAttack) {
    state.selectedAttackId = "";
    selectedAttack = null;
  }
  elements.attackPickerTrigger.setAttribute("aria-expanded", String(state.attackPickerOpen));
  elements.attackPicker.classList.toggle("open", state.attackPickerOpen);
  elements.attackPicker.setAttribute("aria-hidden", String(!state.attackPickerOpen));
  elements.attackSelectedChip.textContent = selectedAttack ? formatAttackOptionLabel(selectedAttack) : "未选择";
  elements.attackSelectedChip.classList.toggle("empty", !selectedAttack);
  elements.attackClearButton.hidden = !selectedAttack;

  const groups = groupAttackExamples(attacks);
  const groupEntries = Array.from(groups.entries());
  const activeTab = getActiveAttackTab(groupEntries);

  elements.attackPicker.innerHTML = `
    <div class="attack-picker-tabs">
      ${groupEntries
        .map(
          ([groupLabel]) => `
            <button class="attack-picker-tab ${groupLabel === activeTab ? "active" : ""}" data-attack-tab="${escapeHtml(
              groupLabel,
            )}" type="button" aria-pressed="${groupLabel === activeTab}">
              ${escapeHtml(groupLabel)}
            </button>
          `,
        )
        .join("")}
    </div>
    <div class="attack-picker-list">
      ${(groups.get(activeTab) ?? []).map((attack) => renderAttackOption(attack, selectedAttack)).join("")}
    </div>
  `;

  elements.attackPicker.querySelectorAll("[data-attack-tab]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.attackPickerTab = button.dataset.attackTab;
      renderAttackPicker();
    });
  });

  elements.attackPicker.querySelectorAll("[data-attack-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectAttackExample(button.dataset.attackId);
    });
  });
}

function renderAttackOption(attack, selectedAttack) {
  const successRate = getAttackSuccessRate(attack);
  const isSelected = selectedAttack?.id === attack.id;
  return `
    <button class="attack-picker-item ${isSelected ? "active" : ""}" data-attack-id="${escapeHtml(attack.id)}"
      type="button" aria-pressed="${isSelected}">
      <span>${escapeHtml(attack.category || attack.label || "攻击样例")}</span>
      ${typeof successRate === "number" ? `<strong>${Math.round(successRate * 100)}%</strong>` : ""}
    </button>
  `;
}

function formatAttackOptionLabel(attack) {
  const categoryName = attack.category || attack.label || "攻击样例";
  const successRate = getAttackSuccessRate(attack);
  if (typeof successRate !== "number") {
    return categoryName;
  }
  return `${categoryName} · 成功率 ${Math.round(successRate * 100)}%`;
}

function getActiveAttackTab(groupEntries) {
  if (groupEntries.some(([groupLabel]) => groupLabel === state.attackPickerTab)) {
    return state.attackPickerTab;
  }
  const firstTab = groupEntries[0]?.[0] ?? "";
  state.attackPickerTab = firstTab;
  return firstTab;
}

function setAttackPickerOpen(isOpen) {
  state.attackPickerOpen = isOpen;
  renderAttackPicker();
}

function selectAttackExample(attackId) {
  const attack = getAttackExampleById(attackId);
  if (!attack) {
    return;
  }
  state.selectedAttackId = attack.id;
  elements.messageInput.value = getAttackQuery(attack);
  resizeMessageInput();
  setAttackPickerOpen(false);
  elements.messageInput.focus();
}

function clearSelectedAttack() {
  state.selectedAttackId = "";
  renderAttackPicker();
}

function groupAttackExamples(attacks) {
  return attacks.reduce((groups, attack) => {
    const groupLabel = attack.attack_set || "攻击示例";
    if (!groups.has(groupLabel)) {
      groups.set(groupLabel, []);
    }
    groups.get(groupLabel).push(attack);
    return groups;
  }, new Map());
}

function normalizeAttackExamples(attacks = []) {
  const normalizedAttacks = attacks
    .map((attack) => ({
      id: String(attack.id ?? ""),
      label: String(attack.label ?? attack.category ?? attack.prompt_name ?? "攻击样例"),
      type: String(attack.type ?? attack.category ?? ""),
      attack_set: String(attack.attack_set ?? ""),
      category: String(attack.category ?? attack.type ?? ""),
      prompt_name: String(attack.prompt_name ?? attack.label ?? ""),
      query: String(attack.query ?? attack.prompt ?? ""),
      metadata: attack.metadata ?? {},
      evaluation: attack.evaluation ?? attack.metadata?.global_attack_evaluation ?? attack.latest_eval ?? {},
      latest_eval: attack.latest_eval ?? {},
      source: String(attack.source ?? ""),
      path: String(attack.path ?? ""),
    }))
    .filter((attack) => attack.id && getAttackQuery(attack));

  return selectBestAttackByCategory(normalizedAttacks);
}

function getAttackExampleById(attackId) {
  if (!attackId) {
    return null;
  }
  return state.attackExamples.find((attack) => attack.id === attackId) ?? null;
}

function getAttackQuery(attack) {
  return String(attack?.query ?? attack?.prompt ?? "").trim();
}

function getAttackType(attack) {
  return String(attack?.category || attack?.type || "").trim();
}

function getAttackSuccessRate(attack) {
  const successRate =
    attack?.metadata?.global_attack_evaluation?.success_rate ??
    attack?.evaluation?.success_rate ??
    attack?.latest_eval?.success_rate;
  return typeof successRate === "number" ? successRate : null;
}

function selectBestAttackByCategory(attacks) {
  const bestByCategory = new Map();
  attacks.forEach((attack) => {
    const key = `${attack.attack_set}\u0000${attack.category}`;
    const current = bestByCategory.get(key);
    if (!current || isBetterAttackExample(attack, current)) {
      bestByCategory.set(key, attack);
    }
  });
  return Array.from(bestByCategory.values());
}

function isBetterAttackExample(candidate, current) {
  const candidateRate = getAttackSuccessRate(candidate) ?? -1;
  const currentRate = getAttackSuccessRate(current) ?? -1;
  if (candidateRate !== currentRate) {
    return candidateRate > currentRate;
  }
  return candidate.prompt_name.localeCompare(current.prompt_name, "zh-CN", { numeric: true }) < 0;
}

function resetConversation() {
  state.conversationVersion += 1;
  state.messages = [
    {
      id: createMessageId(),
      role: "assistant",
      content: "已加载演示场景。你可以先进行正常对话，也可以直接选择攻击示例发起攻击。",
      createdAt: new Date(),
    },
  ];
  state.activeDetailMessageId = null;
  state.flowPhase = "idle";
  state.flowResult = null;
  state.flowRound = 0;
  state.flowCompletedAt = null;
  closeDrawer();
  elements.messageInput.value = getCurrentScenario().normalPrompt;
  state.selectedAttackId = "";
  state.attackPickerOpen = false;
  renderAttackPicker();
  resizeMessageInput();
  renderMessages();
  renderSecurityFlow();
}

async function handleSubmit(event) {
  event.preventDefault();
  if (state.isBusy) {
    return;
  }

  const message = elements.messageInput.value.trim();
  if (!message) {
    return;
  }

  const scenario = getCurrentScenario();
  const requestSessionId = state.sessionId;
  const requestScenarioId = state.scenarioId;
  const requestVersion = state.conversationVersion;
  const attack = getAttackExampleById(state.selectedAttackId);
  const isAttack = Boolean(attack);
  const attackType = getAttackType(attack);

  appendMessage({
    role: "user",
    content: message,
    isAttack,
    attackType,
  });
  const assistantMessage = appendMessage({
    role: "assistant",
    content: "",
    isAttack,
    isStreaming: true,
  });

  elements.messageInput.value = "";
  state.selectedAttackId = "";
  state.attackPickerOpen = false;
  renderAttackPicker();
  resizeMessageInput();
  setBusy(true);
  state.flowRound += 1;
  state.flowPhase = "pre";
  state.flowResult = null;
  state.flowCompletedAt = null;
  renderSecurityFlow();

  try {
    const result = await sendChatRequest({
      scenario,
      message,
      isAttack,
      attackType,
      onStatus: (payload) => {
        if (isCurrentConversation(requestSessionId, requestScenarioId, requestVersion)) {
          elements.runtimeStatus.textContent = payload?.message || "Agent Loop 执行中";
          updateFlowPhaseFromStatus(payload?.message);
        }
      },
      onDelta: (delta) => {
        if (isCurrentConversation(requestSessionId, requestScenarioId, requestVersion)) {
          appendMessageDelta(assistantMessage.id, delta);
        }
      },
    });
    if (!isCurrentConversation(requestSessionId, requestScenarioId, requestVersion)) {
      return;
    }

    updateMessage(assistantMessage.id, {
      content: result.assistant_message,
      result,
      activeGuard: result.active_guard,
      isStreaming: false,
    });
    state.flowResult = result;
    state.flowPhase = "post";
    renderSecurityFlow();
    window.setTimeout(() => {
      if (!isCurrentConversation(requestSessionId, requestScenarioId, requestVersion) || state.flowResult !== result) {
        return;
      }
      state.flowPhase = "complete";
      state.flowCompletedAt = new Date();
      renderSecurityFlow();
    }, 320);
  } catch (error) {
    if (!isCurrentConversation(requestSessionId, requestScenarioId, requestVersion)) {
      return;
    }
    updateMessage(assistantMessage.id, {
      content: assistantMessage.content || error.message || "后端请求失败，请检查 FastAPI 服务或模型连接状态。",
      isAttack: false,
      isStreaming: false,
    });
    state.flowPhase = "error";
    state.flowCompletedAt = new Date();
    renderSecurityFlow();
  } finally {
    setBusy(false);
  }
}

function updateFlowPhaseFromStatus(message = "") {
  if (message.includes("护栏") || message.includes("检测中")) {
    state.flowPhase = "pre";
  } else if (message.includes("生成")) {
    state.flowPhase = "generation";
  }
  renderSecurityFlow();
}

async function sendChatRequest({ scenario, message, isAttack, attackType, onStatus, onDelta }) {
  const modelParams = { ...state.modelParams };
  const payload = {
    session_id: state.sessionId,
    message,
    is_attack: isAttack,
    attack_type: attackType,
    selected_guards: getExecutedGuardIds(),
    model_params: modelParams,
    output_guard: { ...state.outputDetectionConfig },
    scenario_id: scenario.id,
    scenario: {
      id: scenario.id,
      name: scenario.name,
      target: scenario.target,
      systemPrompt: scenario.systemPrompt,
      documents: scenario.documents,
    },
  };

  if (agentApi.sendChatStream) {
    let streamedAnyDelta = false;
    try {
      return await agentApi.sendChatStream({
        scenario,
        payload,
        onStatus,
        onDelta: (delta) => {
          streamedAnyDelta = streamedAnyDelta || Boolean(delta);
          onDelta?.(delta);
        },
      });
    } catch (error) {
      if (streamedAnyDelta) {
        throw error;
      }
    }
  }
  return agentApi.sendChat({ scenario, payload });
}

function isCurrentConversation(sessionId, scenarioId, version) {
  return state.sessionId === sessionId && state.scenarioId === scenarioId && state.conversationVersion === version;
}

function appendMessage(message) {
  const nextMessage = {
    id: createMessageId(),
    createdAt: new Date(),
    ...message,
  };
  state.messages.push(nextMessage);
  renderMessages();
  return nextMessage;
}

function updateMessage(messageId, patch) {
  const message = state.messages.find((item) => item.id === messageId);
  if (!message) {
    return;
  }
  Object.assign(message, patch);
  renderMessages();
}

function appendMessageDelta(messageId, delta) {
  if (!delta) {
    return;
  }
  const message = state.messages.find((item) => item.id === messageId);
  if (!message) {
    return;
  }
  message.content = `${message.content ?? ""}${delta}`;
  renderMessages();
}

function renderMessages() {
  elements.messageList.innerHTML = state.messages.map((message) => renderMessage(message)).join("");

  elements.messageList.querySelectorAll("[data-detail-id]").forEach((button) => {
    button.addEventListener("click", () => openDetail(button.dataset.detailId));
  });

  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function renderMessage(message) {
  const roleLabel = message.role === "user" ? "用户" : "助手";
  const attackBadge = message.isAttack
    ? `<span class="pill pill-danger">${escapeHtml(message.attackType || "攻击示例")}</span>`
    : "";
  const resultBlock = message.result ? renderResultBlock(message) : "";
  const contentBlock = message.content
    ? renderMarkdown(message.content)
    : message.isStreaming
      ? `<p class="stream-placeholder">正在生成</p>`
      : "";
  const streamingCursor = message.isStreaming ? `<span class="stream-cursor" aria-hidden="true"></span>` : "";

  return `
    <article class="message message-${message.role}">
      <div class="message-avatar">${message.role === "user" ? "U" : "A"}</div>
      <div class="message-body">
        <div class="message-meta">
          <strong>${roleLabel}</strong>
          ${attackBadge}
          <time>${formatTime(message.createdAt)}</time>
        </div>
        <div class="message-content markdown-body">${contentBlock}${streamingCursor}</div>
        ${resultBlock}
      </div>
    </article>
  `;
}

function renderResultBlock(message) {
  const result = message.result;
  const metrics = getLeakageMetrics(result);
  const leakageSummary = result.leakage_summary ?? "未发现泄露";
  const tone = getStatusTone(leakageSummary);

  return `
    <div class="result-card">
      <div class="result-inline">
        <span class="pill ${tone}">${escapeHtml(leakageSummary)}</span>
        <span>输入护栏：<strong>${escapeHtml(getInputGuardSummary(result))}</strong></span>
        <span>Exact：<strong>${metrics.exact_match}%</strong></span>
        <span>ROUGE-L：<strong>${metrics.rouge_l}%</strong></span>
        <button class="button button-ghost button-small" data-detail-id="${message.id}" type="button">查看攻击详情</button>
      </div>
    </div>
  `;
}

function openDetail(messageId) {
  state.activeDetailMessageId = messageId;
  state.detailTruthVisible = true;
  elements.drawer.classList.add("open");
  elements.drawerBackdrop.classList.add("open");
  elements.drawer.setAttribute("aria-hidden", "false");
  elements.drawerBackdrop.setAttribute("aria-hidden", "false");
  renderActiveDetail();
}

function closeDrawer() {
  closeRawOutputModal();
  elements.drawer.classList.remove("open");
  elements.drawerBackdrop.classList.remove("open");
  elements.drawer.setAttribute("aria-hidden", "true");
  elements.drawerBackdrop.setAttribute("aria-hidden", "true");
}

function renderActiveDetail() {
  const message = state.messages.find((item) => item.id === state.activeDetailMessageId);
  if (!message?.result) {
    return;
  }

  const scenario = getCurrentScenario();
  const output = getAssistantOutput(message);
  const referenceText = getReferenceText(scenario, message.result);
  const highlightPhrases = collectHighlightPhrases(referenceText, output, message.result.matched_spans);

  elements.drawerTitle.textContent = `${scenario.name} · 泄露检测`;
  elements.truthPanel.innerHTML = state.detailTruthVisible ? highlightText(referenceText, highlightPhrases) : "内容已折叠";
  elements.truthPanel.classList.toggle("redacted", !state.detailTruthVisible);
  elements.outputPanel.innerHTML = highlightText(output, highlightPhrases);
  elements.toggleTruthButton.textContent = state.detailTruthVisible ? "隐藏原文" : "显示原文";
  renderComparison(message.result);
  renderMetricGrid(message.result);
  renderRagTrace(message.result.rag_trace);
}

function renderComparison(result) {
  const guardResults = getVisibleInputGuardResults(result);
  elements.comparisonGrid.innerHTML = guardResults
    .map((item) => {
      const tone = getGuardDecisionTone(item);
      return `
        <article class="comparison-card">
          <div class="comparison-title">
            <strong>${item.guard_name}</strong>
            <span class="pill ${tone}">${escapeHtml(getGuardDecisionText(item))}</span>
          </div>
          ${renderInputGuardMeta(item)}
          ${renderRawGuardOutput(item)}
        </article>
      `;
    })
    .join("");

  elements.comparisonGrid.querySelectorAll("[data-raw-guard-id]").forEach((button) => {
    button.addEventListener("click", () => openRawOutputModal(button.dataset.rawGuardId, button));
  });
}

function openRawOutputModal(guardId, trigger) {
  const message = state.messages.find((item) => item.id === state.activeDetailMessageId);
  const guard = message?.result?.guard_results?.[guardId];
  const rawOutput = String(guard?.raw_guard_output ?? "");
  if (!rawOutput.trim()) {
    return;
  }

  state.activeRawGuardId = guardId;
  state.rawOutputModalTrigger = trigger;
  elements.rawOutputModalTitle.textContent = `${guard.guard_name} · 原始响应`;
  elements.rawOutputModalContent.textContent = rawOutput;
  elements.rawOutputModalBackdrop.classList.add("open");
  elements.rawOutputModalBackdrop.setAttribute("aria-hidden", "false");
  elements.closeRawOutputModalButton.focus();
}

function closeRawOutputModal() {
  if (!state.activeRawGuardId) {
    return;
  }
  const trigger = state.rawOutputModalTrigger;
  state.activeRawGuardId = null;
  state.rawOutputModalTrigger = null;
  elements.rawOutputModalBackdrop.classList.remove("open");
  elements.rawOutputModalBackdrop.setAttribute("aria-hidden", "true");
  if (trigger?.isConnected) {
    trigger.focus();
  }
}

function renderMetricGrid(result) {
  const metrics = getLeakageMetrics(result);
  const outputGuard = result.output_guard ?? state.outputDetectionConfig;
  const metricItems = [
    {
      name: "Exact Match",
      value: `${metrics.exact_match}%`,
      note: `阻断阈值 ${outputGuard.exact_match_threshold}%`,
    },
    {
      name: "ROUGE-L",
      value: `${metrics.rouge_l}%`,
      note: `阻断阈值 ${outputGuard.rouge_l_threshold}%`,
    },
    {
      name: "字符覆盖率",
      value: `${metrics.coverage}%`,
      note: "输出覆盖敏感内容字符的比例",
    },
  ];

  elements.metricGrid.innerHTML = metricItems
    .map(
      (item) => `
        <article class="metric-card">
          <span>${item.name}</span>
          <strong>${item.value}</strong>
          <p>${item.note}</p>
        </article>
      `,
    )
    .join("");
}

function renderRagTrace(ragTrace) {
  const items = ragTrace ?? [];
  if (!items.length) {
    elements.ragList.innerHTML = `<p class="empty-note">当前场景没有 RAG 召回。</p>`;
    return;
  }

  elements.ragList.innerHTML = items
    .map(
      (item) => `
        <article class="rag-item">
          <div>
            <strong>${item.title}</strong>
            <p>${item.snippet}</p>
          </div>
          <div class="rag-meta">
            <span class="pill ${item.sensitive ? "pill-danger" : "pill-success"}">${item.type}</span>
            <span>${item.score}</span>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderSummary() {
  const scenario = getCurrentScenario();
  elements.pageTitle.textContent = scenario.name;
  elements.pageSubtitle.innerHTML = `
    <span class="summary-chip">
      <span>防护对象</span>
      <strong>${escapeHtml(scenario.target)}</strong>
    </span>
    <span class="summary-chip">
      <span>护栏方法</span>
      <strong>${escapeHtml(getGuardSummaryText())}</strong>
    </span>
  `;
  elements.runtimeStatus.textContent = agentApi.mode === "fastapi" ? "FastAPI 已配置" : "Mock Agent 已就绪";
}

function getExecutedGuardIds() {
  return ["baseline", ...state.selectedGuards.filter((guardId) => guardId !== "baseline")];
}

function getGuardName(guardId) {
  return guards.find((guard) => guard.id === guardId)?.name ?? guardId;
}

function getGuardSummaryText() {
  return state.selectedGuards.length
    ? state.selectedGuards.map(getGuardName).join(" + ")
    : "无防护（固定对照）";
}

function getLeakageMetrics(result) {
  const firstResult = Object.values(result.guard_results ?? {})[0];
  const metrics = firstResult?.leakage ?? {};
  return {
    exact_match: metrics.exact_match ?? 0,
    coverage: metrics.coverage ?? 0,
    rouge_l: metrics.rouge_l ?? 0,
  };
}

function getVisibleInputGuardResults(result) {
  const values = Object.values(result.guard_results ?? {});
  const selected = values.filter((item) => item.guard_id !== "baseline");
  return selected.length ? selected : values.filter((item) => item.guard_id === "baseline");
}

function getInputGuardSummary(result) {
  const selected = Object.values(result.guard_results ?? {}).filter((item) => item.guard_id !== "baseline");
  if (!selected.length) {
    return "未启用";
  }

  return selected
    .map((item) => {
      return `${item.guard_name} ${getGuardDecisionText(item)}`;
    })
    .join(" + ");
}

function renderInputGuardMeta(item) {
  const labels = getGuardLabelItems(item);
  return `
    <dl class="input-guard-meta">
      <div class="guard-field">
        <dt>风险判断</dt>
        <dd>${escapeHtml(getGuardRiskText(item))}</dd>
      </div>
      <div class="guard-field">
        <dt>检测耗时</dt>
        <dd>${escapeHtml(formatLatency(item.latency_ms))}</dd>
      </div>
      <div class="guard-field guard-field-wide">
        <dt>命中类别</dt>
        <dd class="guard-label-list">
          ${labels.map((label) => `<span class="guard-label-chip ${label === "无" ? "empty" : ""}">${escapeHtml(label)}</span>`).join("")}
        </dd>
      </div>
    </dl>
  `;
}

function renderRawGuardOutput(item) {
  if (!["qwen_guard", "netease_yidun"].includes(item.guard_id)) {
    return "";
  }

  const rawOutput = String(item.raw_guard_output ?? "");
  if (!rawOutput.trim()) {
    return "";
  }

  return `
    <button class="guard-raw-trigger" data-raw-guard-id="${escapeHtml(item.guard_id)}" type="button">
      <span class="guard-raw-trigger-icon" aria-hidden="true">{ }</span>
      <span>查看原始响应</span>
      <span class="guard-raw-trigger-arrow" aria-hidden="true">↗</span>
    </button>
  `;
}

function getGuardDecisionText(item) {
  if (item.guard_id === "baseline") {
    return "不检测";
  }
  if (item.status === "未配置") {
    return "未配置";
  }
  if (!item.connected || item.status === "检测失败") {
    return "检测失败";
  }
  if (item.blocked) {
    return "建议拦截";
  }
  if (item.query_risk === true || ["存在争议", "嫌疑"].includes(item.status)) {
    return "建议复核";
  }
  return "放行";
}

function getGuardDecisionTone(item) {
  const decision = getGuardDecisionText(item);
  if (["建议拦截", "检测失败"].includes(decision)) {
    return "pill-danger";
  }
  if (decision === "建议复核") {
    return "pill-warning";
  }
  if (decision === "放行") {
    return "pill-success";
  }
  return "pill-neutral";
}

function getGuardRiskText(item) {
  if (item.guard_id === "baseline") {
    return "未检测";
  }
  if (item.status === "未配置") {
    return "服务未配置";
  }
  if (!item.connected || item.status === "检测失败") {
    return "检测失败";
  }
  if (item.blocked || ["命中风险", "不通过"].includes(item.status)) {
    return "高风险";
  }
  if (item.query_risk === true || ["存在争议", "嫌疑"].includes(item.status)) {
    return "需复核";
  }
  return "无风险";
}

function getGuardLabelItems(item) {
  const labels = (item.matched_labels ?? []).map((label) => formatGuardLabel(item.guard_id, label)).filter(Boolean);
  return labels.length ? Array.from(new Set(labels)) : ["无"];
}

function formatGuardLabel(guardId, label) {
  const value = String(label ?? "").trim();
  if (!value || value.toLowerCase() === "none") {
    return "";
  }
  if (guardId === "qwen_guard") {
    return QWEN_LABEL_NAMES[value] ?? value;
  }
  if (guardId === "netease_yidun") {
    return YIDUN_LABEL_NAMES[value] ?? value;
  }
  return value;
}

function formatLatency(value) {
  const latency = Number(value);
  if (!Number.isFinite(latency) || latency <= 0) {
    return "-";
  }
  return `${Math.round(latency)} ms`;
}

function getAssistantOutput(message) {
  const guardResult = Object.values(message.result?.guard_results ?? {})[0];
  return guardResult?.raw_output ?? message.result?.assistant_message ?? message.content ?? "";
}

function getReferenceText(scenario, result) {
  const sensitiveRag = (result.rag_trace ?? [])
    .filter((item) => item.sensitive)
    .map((item) => `[${item.title}]\n${item.snippet}`)
    .join("\n\n");

  if (scenario.target.toLowerCase().includes("rag") && sensitiveRag) {
    return sensitiveRag;
  }
  return scenario.systemPrompt;
}

function collectHighlightPhrases(referenceText, output, matchedSpans = []) {
  const phrases = matchedSpans.map((item) => item.text).filter(Boolean);
  splitComparableUnits(referenceText).forEach((unit) => {
    const common = longestCommonSubstring(unit, output);
    if (normalizeComparable(common).length >= 4) {
      phrases.push(common.trim());
    }
  });

  return Array.from(new Set(phrases.map((item) => item.trim()).filter((item) => normalizeComparable(item).length >= 4)))
    .sort((left, right) => right.length - left.length)
    .slice(0, 12);
}

function splitComparableUnits(text) {
  return String(text ?? "")
    .split(/[\n。；;,.，]/)
    .map((item) => item.trim())
    .filter((item) => normalizeComparable(item).length >= 4);
}

function longestCommonSubstring(left, right) {
  if (!left || !right) {
    return "";
  }

  const rightText = String(right);
  const previousTemplate = new Array(rightText.length + 1).fill(0);
  let previous = previousTemplate;
  let best = 0;
  let bestEnd = 0;
  for (const leftChar of String(left)) {
    const current = [0];
    for (let index = 0; index < rightText.length; index += 1) {
      const length = leftChar.toLowerCase() === rightText[index].toLowerCase() ? previous[index] + 1 : 0;
      current.push(length);
      if (length > best) {
        best = length;
        bestEnd = index + 1;
      }
    }
    previous = current;
  }
  return rightText.slice(bestEnd - best, bestEnd);
}

function normalizeComparable(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/\s/g, "");
}

function highlightText(value, phrases) {
  const text = String(value ?? "");
  const ranges = findHighlightRanges(text, phrases);
  if (!ranges.length) {
    return escapeHtml(text);
  }

  let html = "";
  let cursor = 0;
  ranges.forEach((range) => {
    html += escapeHtml(text.slice(cursor, range.start));
    html += `<mark>${escapeHtml(text.slice(range.start, range.end))}</mark>`;
    cursor = range.end;
  });
  html += escapeHtml(text.slice(cursor));
  return html;
}

function findHighlightRanges(text, phrases) {
  const candidates = [];
  const lowerText = text.toLowerCase();
  phrases.forEach((phrase) => {
    const needle = String(phrase ?? "").trim();
    if (normalizeComparable(needle).length < 4) {
      return;
    }

    const lowerNeedle = needle.toLowerCase();
    let index = lowerText.indexOf(lowerNeedle);
    while (index >= 0) {
      candidates.push({ start: index, end: index + needle.length });
      index = lowerText.indexOf(lowerNeedle, index + Math.max(needle.length, 1));
    }
  });

  const selected = [];
  candidates
    .sort((left, right) => right.end - right.start - (left.end - left.start))
    .forEach((candidate) => {
      if (!selected.some((range) => candidate.start < range.end && candidate.end > range.start)) {
        selected.push(candidate);
      }
    });

  return selected.sort((left, right) => left.start - right.start);
}

function renderMarkdown(value) {
  const lines = String(value ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraph = [];
  let list = null;
  let codeBlock = null;

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    blocks.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!list) {
      return;
    }
    blocks.push(`<${list.type}>${list.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${list.type}>`);
    list = null;
  };

  lines.forEach((line) => {
    const fenceMatch = line.match(/^```(\w+)?\s*$/);
    if (fenceMatch) {
      if (codeBlock) {
        blocks.push(
          `<pre><code${codeBlock.language ? ` class="language-${escapeHtml(codeBlock.language)}"` : ""}>${escapeHtml(
            codeBlock.lines.join("\n"),
          )}</code></pre>`,
        );
        codeBlock = null;
      } else {
        flushParagraph();
        flushList();
        codeBlock = { language: fenceMatch[1] ?? "", lines: [] };
      }
      return;
    }

    if (codeBlock) {
      codeBlock.lines.push(line);
      return;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      return;
    }

    const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length + 2;
      blocks.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      return;
    }

    const unorderedMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    const orderedMatch = line.match(/^\s*\d+\.\s+(.+)$/);
    if (unorderedMatch || orderedMatch) {
      flushParagraph();
      const type = orderedMatch ? "ol" : "ul";
      if (!list || list.type !== type) {
        flushList();
        list = { type, items: [] };
      }
      list.items.push((unorderedMatch || orderedMatch)[1]);
      return;
    }

    flushList();
    paragraph.push(line);
  });

  if (codeBlock) {
    blocks.push(
      `<pre><code${codeBlock.language ? ` class="language-${escapeHtml(codeBlock.language)}"` : ""}>${escapeHtml(
        codeBlock.lines.join("\n"),
      )}</code></pre>`,
    );
  }
  flushParagraph();
  flushList();
  return blocks.join("");
}

function renderInlineMarkdown(value) {
  const codeSpans = [];
  const protectedText = String(value ?? "").replace(/`([^`]+)`/g, (_, code) => {
    const token = `\u0000CODE${codeSpans.length}\u0000`;
    codeSpans.push(`<code>${escapeHtml(code)}</code>`);
    return token;
  });
  let html = escapeHtml(protectedText);

  html = html
    .replace(/\[([^\]]+)]\((https?:\/\/[^\s)]+|mailto:[^\s)]+|#[^\s)]+)\)/g, (_, label, url) => {
      const safeUrl = escapeHtml(url);
      return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    })
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>");

  codeSpans.forEach((code, index) => {
    html = html.replace(`\u0000CODE${index}\u0000`, code);
  });
  return html;
}

function setBusy(isBusy) {
  state.isBusy = isBusy;
  elements.runtimeStatus.textContent = isBusy ? "Agent Loop 执行中" : getReadyStatusText();
  elements.chatForm.classList.toggle("busy", isBusy);
  elements.chatForm.querySelector("button[type='submit']").disabled = isBusy;
}

function getReadyStatusText() {
  return agentApi.mode === "fastapi" ? "FastAPI 已配置" : "Mock Agent 已就绪";
}

function getCurrentScenario() {
  return scenarios.find((scenario) => scenario.id === state.scenarioId) ?? scenarios[0];
}

function getScenariosByCategory(categoryId) {
  return scenarios.filter((scenario) => scenario.category === categoryId);
}

function getStatusTone(status) {
  if (["攻击成功", "发现泄露", "命中风险", "模型服务异常", "检测失败", "不通过"].includes(status)) {
    return "pill-danger";
  }
  if (["存在争议", "嫌疑"].includes(status)) {
    return "pill-warning";
  }
  if (["攻击被拦截", "未命中", "未发现泄露", "通过"].includes(status)) {
    return "pill-success";
  }
  return "pill-neutral";
}

function createSessionId() {
  return `session-${Date.now().toString(36)}`;
}

function createMessageId() {
  return `msg-${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
}

function formatTime(date) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
