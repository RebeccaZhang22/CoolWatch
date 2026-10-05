const LABELS = { search_knowledge: "知识库检索", refund_ticket: "退票申请", process_refund: "退款处理", change_ticket: "改签申请", send_notification: "发送通知", send_sms: "发送短信", browse_webpage: "网页读取" };

function node(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function typeName(schema) {
  if (typeof schema === "boolean") return schema ? "任意类型" : "不允许";
  if (schema.type === "array") return `${typeName(schema.items || {})}[]`;
  if (Array.isArray(schema.type)) return schema.type.join(" | ");
  return schema.type || (schema.enum ? "枚举" : schema.$ref ? "引用" : "见 Schema");
}

function renderFields(properties, required = [], prefix = "") {
  const list = node("div", "tool-fields");
  for (const [name, schema] of Object.entries(properties || {})) {
    const field = node("article", "tool-field");
    const heading = node("div", "tool-field-heading");
    heading.append(node("code", "tool-field-name", prefix + name), node("span", "tool-type", typeName(schema)),
      node("span", required.includes(name) ? "tool-required" : "tool-optional", required.includes(name) ? "必填" : "可选"));
    field.append(heading, node("p", "tool-field-description", schema.description || "未提供字段说明"));
    const constraints = [];
    for (const [key, label] of Object.entries({enum:"可选值", format:"格式", default:"默认值", minimum:"最小值", maximum:"最大值", minItems:"最少项数", maxItems:"最多项数", minLength:"最短长度", maxLength:"最长长度", pattern:"匹配规则"})) {
      if (schema[key] !== undefined) constraints.push(`${label}：${JSON.stringify(schema[key])}`);
    }
    if (constraints.length) field.append(node("p", "tool-constraints", constraints.join(" · ")));
    if (schema.properties) field.append(renderFields(schema.properties, schema.required, prefix + name + "."));
    if (schema.items?.properties) field.append(renderFields(schema.items.properties, schema.items.required, prefix + name + "[]."));
    list.append(field);
  }
  return list;
}

export function renderToolBrowser(container, profile) {
  container.replaceChildren();
  const tools = new Map((profile.tool_schemas || []).map(tool => [tool.function?.name, tool]));
  const names = profile.tools || [];
  if (!names.length) { container.append(node("p", "tool-empty", "暂无已接入工具")); return; }
  const nav = node("nav", "tool-navigation");
  nav.setAttribute("aria-label", "工具列表");
  const detail = node("section", "tool-detail");
  detail.setAttribute("aria-label", "工具详情");
  const buttons = [];
  function select(name) {
    buttons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.name === name)));
    const tool = tools.get(name);
    const fn = tool?.function;
    detail.replaceChildren();
    const header = node("header", "tool-detail-header");
    header.append(node("span", "tool-kicker", "FUNCTION TOOL"), node("h3", "", LABELS[name] || name), node("code", "tool-identifier", name));
    const description = node("p", "tool-description", fn?.description || profile.tool_descriptions?.[name] || "暂无描述");
    const controls = node("div", "tool-view-controls");
    const fieldsButton = node("button", "tool-view-button", "参数字段");
    const schemaButton = node("button", "tool-view-button", "JSON Schema");
    const content = node("div", "tool-detail-content");
    content.tabIndex = 0;
    content.setAttribute("aria-label", "工具说明与参数");
    const body = node("div", "tool-schema-body");
    function setView(raw) {
      fieldsButton.setAttribute("aria-pressed", String(!raw));
      schemaButton.setAttribute("aria-pressed", String(raw));
      body.replaceChildren();
      if (!fn) body.append(node("p", "tool-empty", "当前服务未提供参数 Schema，请更新服务后查看。"));
      else if (raw) body.append(node("pre", "tool-schema-code", JSON.stringify(tool, null, 2)));
      else {
        const parameters = fn.parameters;
        const count = Object.keys(parameters?.properties || {}).length;
        body.append(node("p", "tool-field-summary", parameters ? `${count} 个顶层字段 · ${(parameters.required || []).length} 个必填` : "未提供参数定义"));
        if (count) body.append(renderFields(parameters.properties, parameters.required));
        else if (parameters) body.append(node("p", "tool-empty", "无显式字段定义，完整约束请查看 JSON Schema。"));
      }
      content.scrollTop = 0;
    }
    fieldsButton.type = schemaButton.type = "button";
    fieldsButton.addEventListener("click", () => setView(false));
    schemaButton.addEventListener("click", () => setView(true));
    controls.append(fieldsButton, schemaButton);
    content.append(description, body);
    detail.append(header, controls, content);
    setView(false);
  }
  for (const name of names) {
    const button = node("button", "tool-nav-button");
    button.type = "button";
    button.dataset.name = name;
    button.append(node("span", "tool-nav-title", LABELS[name] || name), node("code", "", name));
    button.addEventListener("click", () => select(name));
    buttons.push(button);
    nav.append(button);
  }
  container.append(nav, detail);
  select(names[0]);
}
