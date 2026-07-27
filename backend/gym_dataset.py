from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.schemas import ScenarioDocument, ScenarioPayload


GYM_IPI_DATASET = Path("resources_servers/indirect_prompt_injection/data/example.jsonl")

DOMAIN_NAMES = {
    "healthcare": "医疗助手",
    "hr": "招聘助手",
    "ecommerce": "电商助手",
    "education": "教育助手",
    "insurance": "保险助手",
    "it_helpdesk": "IT 服务助手",
    "legal": "法律助手",
    "logistics": "物流助手",
    "real_estate": "房地产助手",
}

CATEGORY_NAMES = {
    "exfiltration": "数据外泄",
    "denial_of_service": "拒绝服务",
    "unauthorized_action": "未授权操作",
}

STRATEGY_NAMES = {
    "task_update": "任务篡改",
    "previous_conversation": "伪造历史指令",
    "urgent_override": "紧急指令覆盖",
    "system_message": "伪造系统消息",
}


def load_gym_tasks(nemo_gym_root: Path) -> list[dict[str, Any]]:
    dataset_path = nemo_gym_root / GYM_IPI_DATASET
    if not dataset_path.is_file():
        return []

    tasks: list[dict[str, Any]] = []
    try:
        lines = dataset_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for index, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not isinstance(row.get("injection"), dict):
            continue
        user_message = extract_message(row, "user").strip()
        injection_text = str(row["injection"].get("injection_text") or "").strip()
        if not user_message or user_message == "..." or not injection_text or injection_text == "...":
            continue
        row["_coolwatch_task_id"] = f"gym-ipi-{index}"
        row["_coolwatch_dataset_row"] = index
        tasks.append(row)
    return tasks


def get_gym_task(nemo_gym_root: Path, task_id: str) -> dict[str, Any] | None:
    for task in load_gym_tasks(nemo_gym_root):
        if task.get("_coolwatch_task_id") == task_id:
            return copy.deepcopy(task)
    return None


def gym_scenarios(nemo_gym_root: Path) -> list[ScenarioPayload]:
    return [task_to_scenario(task) for task in load_gym_tasks(nemo_gym_root)]


def gym_attack_examples(nemo_gym_root: Path) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for task in load_gym_tasks(nemo_gym_root):
        injection = task["injection"]
        domain = str(task.get("domain") or "unknown")
        category = str(injection.get("category") or "prompt_injection")
        task_id = str(task["_coolwatch_task_id"])
        examples.append(
            {
                "id": task_id,
                "label": task_to_scenario(task).name,
                "type": "间接提示词注入",
                "attack_set": "NeMo Gym 沙盒任务",
                "attack_set_en": "NeMo Gym Sandbox Tasks",
                "category": (
                    f"{CATEGORY_NAMES.get(category, category)} · "
                    f"{injection.get('attack_strategy', 'prompt injection')}"
                ),
                "category_en": category,
                "prompt_name": task_id,
                # In an indirect injection benchmark the user sends the
                # legitimate request. The malicious prompt is already planted
                # inside sandbox state and appears only after a tool call.
                "query": extract_message(task, "user"),
                "source": "NVIDIA NeMo Gym",
                "path": f"{GYM_IPI_DATASET.as_posix()}:{task['_coolwatch_dataset_row']}",
                "metadata": {
                    "scenario_id": task_id,
                    "domain": domain,
                    "attack_strategy": injection.get("attack_strategy"),
                    "attack_difficulty": injection.get("attack_difficulty"),
                    "vector": injection.get("vector"),
                    "injection_text": injection.get("injection_text"),
                    "target_tool": injection.get("target_tool"),
                    "target_args": injection.get("target_args"),
                },
                "evaluation": {},
                "latest_eval": {},
            }
        )
    return examples


def task_to_scenario(task: dict[str, Any]) -> ScenarioPayload:
    injection = task["injection"]
    domain = str(task.get("domain") or "unknown")
    category = str(injection.get("category") or "prompt_injection")
    vector = str(injection.get("vector") or "tool_output")
    strategy = str(injection.get("attack_strategy") or "prompt_injection")
    task_id = str(task["_coolwatch_task_id"])
    return ScenarioPayload(
        id=task_id,
        name=(
            f"{DOMAIN_NAMES.get(domain, domain)} · {CATEGORY_NAMES.get(category, category)} · "
            f"{STRATEGY_NAMES.get(strategy, strategy)}"
        ),
        target="System Prompt",
        systemPrompt=extract_message(task, "system"),
        # These examples evaluate whether untrusted tool data can override the
        # agent's system-level policy. They are not RAG data-exfiltration
        # examples, so keep them under System Prompt instead of filling the RAG
        # category with semantically unrelated tasks.
        category="prompt",
        description=(
            f"{DOMAIN_NAMES.get(domain, domain)} · {injection.get('attack_difficulty', 'unknown')} · "
            f"{injection.get('attack_strategy', 'prompt injection')} · 载体 {vector}"
        ),
        normalPrompt=extract_message(task, "user"),
        documents=[
            ScenarioDocument(
                title=f"攻击载体：{vector}",
                type="沙盒工具数据",
                sensitive=True,
                content=str(injection.get("injection_text") or ""),
            )
        ],
    )


def extract_message(task: dict[str, Any], role: str) -> str:
    params = task.get("responses_create_params")
    messages = params.get("input", []) if isinstance(params, dict) else []
    for message in messages if isinstance(messages, list) else []:
        if isinstance(message, dict) and message.get("role") == role:
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""
