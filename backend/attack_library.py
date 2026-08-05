from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTACKS_ROOT = REPO_ROOT / "data" / "system_prompt_extraction" / "cn" / "attacks"


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
