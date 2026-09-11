export type Message = { role: "developer" | "system" | "user" | "assistant" | "tool"; content?: string | null; [key: string]: unknown };
export type ModerationResult = { score: number; threshold: number; flagged: boolean };
export type ModerationResponse = { id: string; request_id: string; created: number; detector_model: string; bank_version: string; action: "pass" | "block"; per_risk: Record<"harmful" | "prompt_leakage" | "ipi", ModerationResult>; per_entry: Record<string, number>; triggered_entries: string[]; usage: { input_tokens: number; billable_tokens: number; billable_units: number; unit: string }; latency_ms: { queue: number; prefill?: number; detect: number; total: number } };

export class SiliconProspectAPIError extends Error {
  constructor(message: string, public statusCode?: number, public code?: string, public requestId?: string) { super(message); }
}

export class SiliconProspectGuard {
  readonly moderations: { create: (params: { messages: Message[]; tools?: Record<string, unknown>[]; metadata?: Record<string, string>; idempotency_key?: string; request_id?: string }) => Promise<ModerationResponse> };
  private readonly baseUrl: string;
  private readonly apiKey: string;
  constructor(options: { apiKey?: string; baseUrl?: string; timeoutMs?: number } = {}) {
    this.apiKey = options.apiKey ?? (typeof process !== "undefined" ? process.env.SILICONPROSPECT_API_KEY ?? "" : "");
    if (!this.apiKey) throw new Error("apiKey is required");
    this.baseUrl = (options.baseUrl ?? "http://127.0.0.1:18088").replace(/\/$/, "");
    this.moderations = { create: (params) => this.create(params) };
  }
  private async create(params: Parameters<SiliconProspectGuard["moderations"]["create"]>[0]): Promise<ModerationResponse> {
    const headers: Record<string, string> = { Authorization: `Bearer ${this.apiKey}`, "Content-Type": "application/json" };
    if (params.request_id) headers["X-Request-Id"] = params.request_id;
    if (params.idempotency_key) headers["Idempotency-Key"] = params.idempotency_key;
    const response = await fetch(`${this.baseUrl}/v1/moderations`, { method: "POST", headers, body: JSON.stringify({ messages: params.messages, tools: params.tools, metadata: params.metadata }) });
    const payload = await response.json();
    if (!response.ok) throw new SiliconProspectAPIError(payload?.error?.message ?? `HTTP ${response.status}`, response.status, payload?.error?.code, payload?.error?.request_id ?? response.headers.get("x-request-id") ?? undefined);
    return payload as ModerationResponse;
  }
}
