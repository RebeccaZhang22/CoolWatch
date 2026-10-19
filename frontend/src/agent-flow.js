export function createAgentFlow() {
  return { model: "idle", env: "idle", active: null, rounds: 0, detail: "", checkpoints: [] };
}

// Drive the lights from execution events, never from an animation timer.
export function advanceAgentFlow(flow, event) {
  if (event.heartbeat) return;
  if (event.checkpoint) {
    const checkpoint = { ...event.checkpoint };
    const index = flow.checkpoints.findIndex((item) => item.round === checkpoint.round);
    if (index < 0) flow.checkpoints.push(checkpoint);
    else flow.checkpoints[index] = checkpoint;
  }
  if (event.message === "正在交付最终答复") {
    finishAgentFlow(flow);
    return;
  }
  const node = ["generation", "final_response"].includes(event.phase)
    ? "model" : ["tool", "retrieval"].includes(event.phase) ? "env" : null;
  if (!node) {
    if (event.phase === "input_guard" && event.status === "running" && flow.active) {
      flow[flow.active] = "complete";
      flow.active = null;
    }
    return;
  }
  // Delivery is not another model invocation.
  const finished = event.status !== "running" || event.duration_ms != null
    || event.message === "正在交付最终答复";
  if (flow.active && flow.active !== node) flow[flow.active] = "complete";
  if (node === "model" && !finished && flow.active !== "model") flow.rounds += 1;
  flow[node] = event.status === "error" ? "error" : finished ? "complete" : "running";
  flow.active = finished ? null : node;
  if (node === "env") flow.detail = event.detail || "工具调用 / RAG / 外部环境";
}

export function finishAgentFlow(flow, failed = false) {
  if (failed) {
    for (const checkpoint of flow.checkpoints) {
      if (checkpoint.status === "running") {
        checkpoint.status = "error";
        checkpoint.detail = "检测未完成，运行已中断";
      }
    }
  }
  if (flow.active) flow[flow.active] = failed ? "error" : "complete";
  flow.active = null;
}
