from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTACKS_ROOT = REPO_ROOT / "data" / "cn" / "attacks"
GYM_IPI_DATASET = Path("resources_servers/indirect_prompt_injection/data/example.jsonl")


def load_attack_examples(language: str = "cn", attacks_root: Path = DEFAULT_ATTACKS_ROOT) -> list[dict[str, Any]]:
    if language != "cn" or not attacks_root.exists():
        return []

    examples: list[dict[str, Any]] = []
    for prompt_path in sorted(attacks_root.rglob("prompt.json")):
        data = _read_prompt_json(prompt_path)
        query = str(data.get("query") or "").strip()
        if not query:
            continue

        relative_path = prompt_path.relative_to(REPO_ROOT).as_posix()
        category = str(data.get("category") or "未分类攻击")
        prompt_name = str(data.get("prompt_name") or prompt_path.parent.name)
        attack_set = str(data.get("attack_set") or prompt_path.parts[-4])
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        evaluation = _extract_evaluation(data)

        examples.append(
            {
                "id": str(data.get("id") or prompt_path.relative_to(attacks_root).as_posix()),
                "label": category,
                "type": category,
                "attack_set": attack_set,
                "attack_set_en": str(data.get("attack_set_en") or ""),
                "category": category,
                "category_en": str(data.get("category_en") or ""),
                "prompt_name": prompt_name,
                "query": query,
                "metadata": metadata,
                "evaluation": evaluation,
                "latest_eval": evaluation,
                "source": str(data.get("source") or ""),
                "path": relative_path,
            }
        )

    return sorted(
        _select_best_by_category(examples),
        key=lambda item: (
            item["attack_set"],
            item["category"],
            item["id"],
        ),
    )


def load_gym_prompt_injection_examples(nemo_gym_root: Path) -> list[dict[str, Any]]:
    """Load NeMo Gym IPI attacks for the CoolWatch attack picker.

    The UI uses the embedded injection text as the selectable attack prompt.
    The legitimate user request and sandbox metadata remain attached so a
    future sandbox view can submit the original JSONL row without flattening it.
    """
    dataset_path = nemo_gym_root / GYM_IPI_DATASET
    if not dataset_path.is_file():
        return []

    examples: list[dict[str, Any]] = []
    try:
        lines = dataset_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for index, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        injection = row.get("injection")
        if not isinstance(injection, dict):
            continue
        injection_text = str(injection.get("injection_text") or "").strip()
        if not injection_text:
            continue

        domain = str(row.get("domain") or "unknown")
        category = str(injection.get("category") or "prompt_injection")
        examples.append(
            {
                "id": f"nemo-gym-ipi-{index}",
                "label": f"{domain} · {category}",
                "type": "间接提示词注入",
                "attack_set": "NeMo Gym 间接提示词注入",
                "attack_set_en": "NeMo Gym Indirect Prompt Injection",
                "category": category,
                "category_en": category,
                "prompt_name": f"ipi_{index:03d}",
                "query": injection_text,
                "source": "NVIDIA NeMo Gym",
                "path": f"{GYM_IPI_DATASET.as_posix()}:{index}",
                "metadata": {
                    "domain": domain,
                    "attack_strategy": injection.get("attack_strategy"),
                    "attack_difficulty": injection.get("attack_difficulty"),
                    "vector": injection.get("vector"),
                    "target_tool": injection.get("target_tool"),
                    "target_args": injection.get("target_args"),
                    "legitimate_user_request": _extract_user_request(row),
                    "gym_dataset_row": index,
                },
                "evaluation": {},
                "latest_eval": {},
            }
        )
    return examples


def _extract_user_request(row: dict[str, Any]) -> str:
    create_params = row.get("responses_create_params")
    messages = create_params.get("input", []) if isinstance(create_params, dict) else []
    for message in reversed(messages if isinstance(messages, list) else []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _read_prompt_json(prompt_path: Path) -> dict[str, Any]:
    try:
        with prompt_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _extract_evaluation(data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        global_evaluation = metadata.get("global_attack_evaluation")
        if isinstance(global_evaluation, dict):
            return global_evaluation

    latest_eval = data.get("latest_eval")
    return latest_eval if isinstance(latest_eval, dict) else {}


def _select_best_by_category(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_category: dict[tuple[str, str], dict[str, Any]] = {}
    for example in examples:
        key = (str(example["attack_set"]), str(example["category"]))
        current = best_by_category.get(key)
        if current is None or _is_better_example(example, current):
            best_by_category[key] = example
    return list(best_by_category.values())


def _is_better_example(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    candidate_rate = _success_rate(candidate)
    current_rate = _success_rate(current)
    if candidate_rate != current_rate:
        return candidate_rate > current_rate
    return _prompt_sort_key(str(candidate["prompt_name"])) < _prompt_sort_key(str(current["prompt_name"]))


def _success_rate(example: dict[str, Any]) -> float:
    evaluation = example.get("evaluation")
    if not isinstance(evaluation, dict):
        return -1.0
    success_rate = evaluation.get("success_rate")
    return float(success_rate) if isinstance(success_rate, (int, float)) else -1.0


def _prompt_sort_key(value: str) -> tuple[str, int]:
    prefix = value.rstrip("0123456789")
    suffix = value[len(prefix) :]
    return prefix, int(suffix or 0)
