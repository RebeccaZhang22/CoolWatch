import { buildMockChatResult, getFallbackAttackExamples } from "./mock-data.js?v=safegauge-threshold-20260723";

export function createAgentApiClient({
  apiBase = window.AGENT_GUARD_API_BASE ?? defaultApiBase(),
  useMock = window.AGENT_GUARD_USE_MOCK === true,
} = {}) {
  const normalizedBase = apiBase.replace(/\/$/, "");

  return {
    mode: useMock ? "mock" : "fastapi",

    async listAttacks() {
      if (useMock) {
        await sleep(120);
        return { attacks: getFallbackAttackExamples() };
      }

      const response = await fetch(`${normalizedBase}/api/attacks?language=cn`);
      if (!response.ok) {
        const message = await readErrorMessage(response);
        throw new Error(message || `攻击示例加载失败：${response.status}`);
      }

      return response.json();
    },

    async getSafeGaugeInfo() {
      if (useMock) {
        return { meta: { best_threshold: 0.42150071263313293 } };
      }

      const response = await fetch(`${normalizedBase}/api/guards/safegauge/info`);
      if (!response.ok) {
        const message = await readErrorMessage(response);
        throw new Error(message || `SafeGauge 配置加载失败：${response.status}`);
      }
      return response.json();
    },

    async sendChat({ scenario, payload }) {
      if (useMock) {
        await sleep(420);
        return buildMockChatResult({
          scenario,
          message: payload.message,
          isAttack: payload.is_attack,
          attackType: payload.attack_type,
          selectedGuards: payload.selected_guards,
          outputGuard: payload.output_guard,
          safeGaugeThreshold: payload.safegauge?.threshold,
        });
      }

      const response = await fetch(`${normalizedBase}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const message = await readErrorMessage(response);
        throw new Error(message || `请求失败：${response.status}`);
      }

      return response.json();
    },

    async sendChatStream({ scenario, payload, onStatus, onDelta }) {
      if (useMock) {
        return streamMockChatResult({ scenario, payload, onStatus, onDelta });
      }

      const response = await fetch(`${normalizedBase}/api/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok || !response.body) {
        const message = await readErrorMessage(response);
        throw new Error(message || `流式请求失败：${response.status}`);
      }

      return readSseResponse(response, { onStatus, onDelta });
    },
  };
}

function defaultApiBase() {
  return window.location.origin;
}

async function readErrorMessage(response) {
  try {
    const data = await response.json();
    return data.detail || data.message || "";
  } catch {
    return response.statusText;
  }
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function streamMockChatResult({ scenario, payload, onStatus, onDelta }) {
  onStatus?.({ message: "输入护栏检测中" });
  await sleep(180);
  onStatus?.({ message: "模型生成中" });

  const result = buildMockChatResult({
    scenario,
    message: payload.message,
    isAttack: payload.is_attack,
    attackType: payload.attack_type,
    selectedGuards: payload.selected_guards,
    outputGuard: payload.output_guard,
    safeGaugeThreshold: payload.safegauge?.threshold,
  });

  const chunks = splitTextForMockStream(result.assistant_message);
  for (const chunk of chunks) {
    onDelta?.(chunk);
    await sleep(28);
  }
  return result;
}

function splitTextForMockStream(text) {
  const chunks = [];
  let index = 0;
  while (index < text.length) {
    const size = text.charCodeAt(index) > 255 ? 2 : 4;
    chunks.push(text.slice(index, index + size));
    index += size;
  }
  return chunks;
}

async function readSseResponse(response, { onStatus, onDelta }) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalPayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split(/\n\n/);
    buffer = events.pop() ?? "";
    for (const eventBlock of events) {
      const payload = parseSseEvent(eventBlock);
      if (!payload) {
        continue;
      }
      if (payload.event === "status") {
        onStatus?.(payload.data);
      } else if (payload.event === "delta") {
        onDelta?.(payload.data.content ?? "");
      } else if (payload.event === "final") {
        finalPayload = payload.data;
      } else if (payload.event === "error") {
        throw new Error(payload.data.message || "流式请求失败");
      }
    }
  }

  if (buffer.trim()) {
    const payload = parseSseEvent(buffer);
    if (payload?.event === "final") {
      finalPayload = payload.data;
    }
  }

  if (!finalPayload) {
    throw new Error("流式响应未返回最终结果");
  }
  return finalPayload;
}

function parseSseEvent(block) {
  const lines = block.split(/\n/);
  let event = "message";
  const dataLines = [];

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });

  if (!dataLines.length) {
    return null;
  }

  return {
    event,
    data: JSON.parse(dataLines.join("\n")),
  };
}
