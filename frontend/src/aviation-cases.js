const $ = (id) => document.getElementById(id);
const state = { cases: [], selected: null, mode: 'off', active: 0, timer: null, expanded: false };
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function stop() {
  clearInterval(state.timer);
  state.timer = null;
  $('playSteps').textContent = '播放过程';
}

function eventsForMode() {
  return state.mode === 'off' ? state.selected.events : state.selected.protected_events;
}

function choose(id) {
  stop();
  state.selected = state.cases.find(row => row.id === id) || state.cases[2];
  state.active = 0;
  state.expanded = false;
  const row = state.selected;
  document.querySelectorAll('[data-case]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.case === row.id)));
  $('caseNumber').textContent = `${row.number} / ${row.tag}`;
  $('caseTitle').textContent = row.title;
  $('caseMechanism').textContent = row.mechanism;
  $('caseQuery').textContent = row.query;
  $('attackOutcome').textContent = row.outcome;
  $('attackEvidence').textContent = row.outcome_detail;
  $('guardOutcome').textContent = row.prevented;
  const blocked = row.protected_events.find(event => event.type === 'check' && event.blocked);
  $('guardEvidence').textContent = blocked
    ? `第 ${blocked.round} 轮生成前 · IPI 风险分数 ${blocked.score.toFixed(4)} ≥ 阈值 ${blocked.threshold.toFixed(2)}。恶意工具返回已进入上下文，下一条 Assistant 消息被拦截。`
    : '本次记录中没有达到阻断阈值的检测点。';
  $('reproductionInfo').innerHTML = `<p>样本 ${escape(row.id)} · ${escape(row.model)} · ${escape(row.mode)} · ${escape(new Date(row.recorded_at).toLocaleString('zh-CN'))}</p><p>探针版本：${escape(blocked?.bank_version || '未记录')}</p>${row.tools.map(tool => `<details><summary>${escape(tool.function.name)}</summary><p>${escape(tool.function.description)}</p></details>`).join('')}`;
  $('downloadEvidence').href = `./data/aviation/${encodeURIComponent(row.id)}.json`;
  const url = new URL(window.location.href);
  url.searchParams.set('case', row.id);
  window.history.replaceState(null, '', url);
  // Keep deep links and refresh consistent inside the persistent app shell.
  if (window.parent !== window) {
    window.parent.postMessage({type: 'aviation-case:selected', caseId: row.id}, window.location.origin);
  }
  render();
}

function renderCheck(event) {
  const intervention = state.mode === 'on' && event.blocked;
  const action = intervention ? '阻断：不再生成下一条 Assistant 消息，也不会执行后续工具。'
    : event.blocked ? '风险已命中；当前为无防护对照，仍继续生成，观察攻击结果。'
    : state.mode === 'on' ? '放行：允许模型生成下一条回复或工具调用。' : '检测未命中；无防护对照继续执行。';
  return `<details class="event-card check ${event.blocked ? 'danger' : ''}"><summary><span class="event-role">CHECK · ${event.round}</span><strong>第 ${event.round} 轮生成前检测 · ${intervention ? '阻断' : event.blocked ? '风险命中（仅观察）' : '未命中风险'}</strong></summary><div class="event-content"><p class="event-meta">检测输入为此刻的 ${event.message_count} 条完整消息 + ${state.selected.tools.length} 个工具定义；这里不重复展示前序消息。</p><div class="check-metrics"><div><span>IPI 风险分数</span><strong>${event.score.toFixed(4)}</strong></div><div><span>阻断阈值</span><strong>${event.threshold.toFixed(2)}</strong></div><div><span>当前消息数</span><strong>${event.message_count}</strong></div></div><div class="score-track"><span style="width:${Math.max(0, Math.min(100, event.score * 100))}%"></span><i style="left:${event.threshold * 100}%" title="阻断阈值"></i></div><p class="check-action">${action}</p><details><summary>查看本次检测原始结果</summary><pre>${escape(JSON.stringify(event.raw, null, 2))}</pre></details></div></details>`;
}

function renderMessage(event) {
  const message = event.message;
  const calls = message.tool_calls || [];
  const injected = event.source === 'injected_fixture';
  const title = message.role === 'system' ? '设置客服职责与安全边界'
    : message.role === 'user' ? '用户提出正常航旅问题'
    : message.role === 'tool' ? (injected ? '检索返回 · 恶意指令进入上下文' : `${message.name} · 返回模拟执行结果`)
    : calls.length ? `模型调用 ${calls.map(call => call.function.name).join(' + ')}` : '模型给出最终回复 · 本次 Loop 结束';
  const source = {fixture: '交接样本中的原始消息', injected_fixture: '固定攻击片段 · 作为工具数据呈现', live_model: '本次真实模型 API 输出', simulated_tool: '本地模拟工具返回 · 无真实业务操作'}[event.source];
  const body = (message.content ? `<pre>${escape(message.content)}</pre>` : '') + calls.map(call => {
    let args = call.function.arguments;
    try { args = JSON.stringify(JSON.parse(args), null, 2); } catch { /* Preserve malformed model output for audit. */ }
    return `<p class="event-meta">${escape(call.function.name)} · ${escape(call.id)}</p><pre>${escape(args)}</pre>`;
  }).join('');
  return `<details class="event-card ${injected ? 'injected' : ''}"><summary><span class="event-role">${escape(message.role.toUpperCase())}</span><strong>${escape(title)}</strong></summary><div class="event-content"><p class="event-meta">${escape(source)}${message.tool_call_id ? ` · ${escape(message.tool_call_id)}` : ''}</p>${body}</div></details>`;
}

function render() {
  const events = eventsForMode();
  state.active = Math.min(state.active, events.length - 1);
  $('messageTimeline').innerHTML = events.map((event, index) => `<li class="timeline-event ${index === state.active ? 'active' : ''}" data-event="${index}">${event.type === 'check' ? renderCheck(event) : renderMessage(event)}</li>`).join('');
  document.querySelectorAll('.timeline-event > details').forEach((detail, index) => {
    detail.open = state.expanded || index === state.active;
    detail.querySelector('summary').addEventListener('click', () => {
      stop(); state.active = index;
      document.querySelectorAll('.timeline-event').forEach((item, i) => item.classList.toggle('active', i === index));
      updateControls(events.length);
    });
  });
  document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mode === state.mode)));
  const blocked = state.mode === 'on' && events.at(-1)?.type === 'check' && events.at(-1).blocked;
  $('traceEnd').classList.toggle('blocked', blocked);
  $('traceEnd').textContent = blocked
    ? `防护路径在第 ${events.at(-1).round} 轮检测结束。危险回复与工具调用没有继续执行。`
    : '模型已给出最终回复，本次 Agent Loop 结束。上方模拟工具结果不代表真实退款或短信送达。';
  $('expandAll').textContent = state.expanded ? '收起消息详情' : '展开全部消息';
  updateControls(events.length);
}

function updateControls(length) {
  $('stepStatus').textContent = `步骤 ${state.active + 1} / ${length}`;
  $('prevStep').disabled = state.active === 0;
  $('nextStep').disabled = state.active === length - 1;
}

function advance(delta) {
  state.expanded = false;
  state.active = Math.max(0, Math.min(eventsForMode().length - 1, state.active + delta));
  render();
  document.querySelector('.timeline-event.active')?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

$('prevStep').addEventListener('click', () => { stop(); advance(-1); });
$('nextStep').addEventListener('click', () => { stop(); advance(1); });
$('expandAll').addEventListener('click', () => { stop(); state.expanded = !state.expanded; render(); });
$('playSteps').addEventListener('click', () => {
  if (state.timer) { stop(); return; }
  if (state.active === eventsForMode().length - 1) state.active = 0;
  state.expanded = false;
  render();
  $('playSteps').textContent = '暂停播放';
  state.timer = setInterval(() => {
    if (state.active >= eventsForMode().length - 1) { stop(); return; }
    advance(1);
  }, 2200);
});
for (const button of document.querySelectorAll('[data-mode]')) {
  button.addEventListener('click', () => { stop(); state.mode = button.dataset.mode; state.active = 0; state.expanded = false; render(); });
}
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
window.addEventListener('pagehide', stop);

try {
  const response = await fetch('./data/aviation/index.json', {cache: 'no-store'});
  if (!response.ok) throw new Error(`记录加载失败（${response.status}）`);
  state.cases = (await response.json()).cases;
  if (state.cases.length !== 3) throw new Error('三个案例的复现记录尚未齐备');
  $('caseCards').innerHTML = state.cases.map(row => `<button class="aviation-card" type="button" data-case="${escape(row.id)}" aria-pressed="false"><span>${escape(row.number)} · ${escape(row.tag)}</span><strong>${escape(row.title)}</strong><p>${escape(row.short)}</p></button>`).join('');
  document.querySelectorAll('[data-case]').forEach(button => button.addEventListener('click', () => choose(button.dataset.case)));
  $('loadStatus').hidden = true;
  $('caseDetail').hidden = false;
  choose(new URLSearchParams(window.location.search).get('case'));
} catch (error) {
  $('loadStatus').textContent = `无法展示案例：${error.message}。请刷新重试。`;
}
