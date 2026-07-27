from __future__ import annotations

import json
from typing import Any

import httpx

from backend.gym_dataset import get_gym_task
from backend.schemas import AgentTraceItem, ModelParams, RagTraceItem


class GymClient:
    def __init__(self, nemo_gym_root, head_url: str, timeout_seconds: float) -> None:
        self.nemo_gym_root = nemo_gym_root
        self.head_url = head_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def close(self) -> None:
        await self.client.aclose()

    async def run_task(
        self,
        task_id: str,
        system_prompt: str,
        user_message: str,
        model_params: ModelParams,
    ) -> dict[str, Any]:
        task = get_gym_task(self.nemo_gym_root, task_id)
        if task is None:
            raise ValueError(f"未知的 NeMo Gym 任务：{task_id}")

        self._replace_messages(task, system_prompt, user_message)
        create_params = task["responses_create_params"]
        create_params["temperature"] = model_params.temperature
        create_params["top_p"] = model_params.top_p
        create_params["max_output_tokens"] = model_params.max_tokens
        # Qwen's thinking mode can spend most of the rollout budget before it
        # reaches a tool call. The interactive CoolWatch path favors visible,
        # low-latency tool execution; offline Gym evaluation can still enable
        # thinking in its own dataset/config.
        create_params["metadata"] = {
            **(create_params.get("metadata") or {}),
            "chat_template_kwargs": json.dumps({"enable_thinking": False}),
        }

        agent_url = await self._resolve_agent_url()
        response = await self.client.post(f"{agent_url}/run", json=task)
        response.raise_for_status()
        return response.json()

    async def _resolve_agent_url(self) -> str:
        response = await self.client.get(f"{self.head_url}/server_instances")
        response.raise_for_status()
        for server in response.json():
            if server.get("config_path") == "coolwatch_prompt_injection_simple_agent":
                return str(server["url"]).rstrip("/")
        raise RuntimeError("NeMo Gym Agent 未启动，请运行 ./scripts/start_gym_sandbox.sh")

    @staticmethod
    def _replace_messages(task: dict[str, Any], system_prompt: str, user_message: str) -> None:
        params = task["responses_create_params"]
        messages = params.get("input", [])
        for message in messages:
            if message.get("role") == "system":
                message["content"] = system_prompt
            elif message.get("role") == "user":
                message["content"] = user_message


def summarize_gym_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "reward",
        "reward_safety",
        "reward_utility",
        "injection_followed",
        "matched_tool",
        "matched_args",
        "attack_difficulty",
        "attack_strategy",
        "attack_category",
        "verification_type",
        "sandbox_provider",
        "sandbox_status",
        "sandbox_error",
    )
    return {key: result.get(key) for key in keys}


def extract_gym_output(result: dict[str, Any]) -> str:
    response = result.get("response")
    output = response.get("output", []) if isinstance(response, dict) else []
    for item in reversed(output if isinstance(output, list) else []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        parts = item.get("content", [])
        texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict)]
        text = "".join(texts).strip()
        if text:
            return text
    return "Gym Agent 已完成运行，但没有返回最终文本。"


def build_gym_agent_trace(result: dict[str, Any], elapsed_ms: int) -> list[AgentTraceItem]:
    trace = [
        AgentTraceItem(
            name="Sandbox Seed",
            status="success",
            input="NeMo Gym environment.json",
            output=f"Docker sandbox / provider={result.get('sandbox_provider', 'docker')}",
            duration=0,
        )
    ]
    sandbox_trace = result.get("sandbox_trace", [])
    for event in sandbox_trace if isinstance(sandbox_trace, list) else []:
        if not isinstance(event, dict):
            continue
        trace.append(
            AgentTraceItem(
                name=str(event.get("name") or "Sandbox Tool"),
                status="error" if event.get("error") else "success",
                input=str(event.get("arguments") or "{}"),
                output=_compact_json(event.get("result") if not event.get("error") else event.get("error")),
                duration=0,
                error=str(event["error"]) if event.get("error") else None,
            )
        )
    trace.append(
        AgentTraceItem(
            name="Safety Verify",
            status="success" if not result.get("sandbox_error") else "error",
            input=f"target={result.get('matched_tool') or 'not matched'}",
            output=(
                f"safety={result.get('reward_safety', 0):.0f} · "
                f"utility={result.get('reward_utility', 0):.0f} · reward={result.get('reward', 0):.0f}"
            ),
            duration=elapsed_ms,
            error=result.get("sandbox_error"),
        )
    )
    return trace


def gym_rag_trace(result: dict[str, Any]) -> list[RagTraceItem]:
    items: list[RagTraceItem] = []
    for index, event in enumerate(result.get("sandbox_trace", [])):
        if not isinstance(event, dict) or event.get("result") is None:
            continue
        items.append(
            RagTraceItem(
                id=f"gym-tool-{index}",
                title=str(event.get("name") or "Sandbox Tool"),
                type="Gym 沙盒工具输出",
                sensitive=True,
                score=1.0,
                snippet=_compact_json(event.get("result"), limit=500),
            )
        )
    return items


def _compact_json(value: Any, limit: int = 1000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"
