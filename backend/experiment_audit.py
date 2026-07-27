from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from backend.guard_inputs import TOOL_RESULT


COOLWATCH_ROOT = Path(__file__).resolve().parents[1]
FOLLOW_YOUR_HEART_ROOT = COOLWATCH_ROOT.parents[1]
EXPERIMENT_ID = "qwen3-8b-held-out-strict-injected-round-100-zh"
EVALUATION_ROOT = (
    COOLWATCH_ROOT
    / "evaluations"
    / "qwen3_8b_held_out_strict_injected_round_100_samples_zh"
)
RESULT_ROOT = COOLWATCH_ROOT / "results" / "guard_detection" / EXPERIMENT_ID
GUARDS = ("inline_probing", "qwen3_guard", "netease_yidun", "no_guard")
GUARD_NAMES = {
    "inline_probing": "Inline Probe",
    "qwen3_guard": "Qwen3Guard",
    "netease_yidun": "网易易盾",
    "no_guard": "No Guard",
}
AUDIT_RISKS = (
    {
        "id": "sensitive_data_exposure",
        "name": "敏感数据泄露",
        "short_name": "数据泄露",
        "status": "coming_soon",
        "endpoint": None,
        "case_endpoint": None,
        "summary": "预留给后续测试员接入敏感信息外泄类审计结果。",
        "sample_count": 0,
        "language": "待接入",
    },
    {
        "id": "unsafe_tool_action",
        "name": "高风险任务",
        "short_name": "高风险任务",
        "status": "coming_soon",
        "endpoint": None,
        "case_endpoint": None,
        "summary": "预留给后续测试员接入越权转账、改密、下单等动作风险审计。",
        "sample_count": 0,
        "language": "待接入",
    },
    {
        "id": "prompt_injection",
        "name": "间接提示注入",
        "short_name": "提示注入",
        "status": "available",
        "endpoint": "/api/audit/experiment",
        "case_endpoint": "/api/audit/experiment/cases/{sample_index}",
        "summary": "审计外部工具返回中的恶意指令是否会影响 Qwen3-8B 的下一步决策。",
        "sample_count": 100,
        "language": "zh-CN",
    },
)


def list_audit_risks() -> dict[str, Any]:
    return {
        "default_risk": "prompt_injection",
        "risks": [dict(row) for row in AUDIT_RISKS],
    }


@lru_cache(maxsize=1)
def load_experiment_overview() -> dict[str, Any]:
    settings = _read_json(EVALUATION_ROOT / "settings.json")
    case_manifest = _read_json(EVALUATION_ROOT / "case_manifest.json")
    run_manifest = _read_json(RESULT_ROOT / "run_manifest.json")
    summary = _read_json(RESULT_ROOT / "summary.json")
    cases = sorted(
        _iter_jsonl(EVALUATION_ROOT / "cases.jsonl"),
        key=lambda row: int(row["sample_index"]),
    )
    results = {
        guard: _index_guard_rows(RESULT_ROOT / f"{guard}.jsonl", guard)
        for guard in GUARDS
    }
    behavior = {
        row["decision_point_id"]: row
        for row in _iter_jsonl(RESULT_ROOT / "behavior.jsonl")
    }
    judgments = {
        row["decision_point_id"]: row
        for row in _iter_jsonl(RESULT_ROOT / "behavior_judgments.jsonl")
    }

    case_rows = []
    for case in cases:
        decision_point_id = str(case["decision_point_id"])
        guard_results = {
            guard: _compact_guard_bundle(guard, results[guard][decision_point_id])
            for guard in GUARDS
        }
        suite, system_prompt, attack = _split_grid_point(case["grid_point_id"])
        case_rows.append(
            {
                "sample_index": int(case["sample_index"]),
                "decision_point_id": decision_point_id,
                "trace_id": str(case["trace_id"]),
                "grid_point_id": str(case["grid_point_id"]),
                "suite": suite,
                "system_prompt": system_prompt,
                "attack": attack,
                "assistant_message_index": int(case["assistant_message_index"]),
                "injection_message_indices": [
                    int(value) for value in case["injection_message_indices"]
                ],
                "detected_by": [
                    guard
                    for guard in GUARDS
                    if any(
                        row["detected"] is True
                        for row in guard_results[guard]["input_modes"].values()
                    )
                ],
                "primary_detected_by": [
                    guard
                    for guard in GUARDS
                    if guard_results[guard]["detected"] is True
                ],
                "guard_results": guard_results,
                "behavior": {
                    "label": judgments[decision_point_id]["label"],
                    "confidence": judgments[decision_point_id]["confidence"],
                    "reason": judgments[decision_point_id]["reason"],
                    "has_tool_calls": bool(
                        (behavior[decision_point_id].get("message") or {}).get(
                            "tool_calls"
                        )
                    ),
                },
            }
        )

    guard_metrics = []
    for guard in GUARDS:
        row = summary["guards"][guard]
        guard_metrics.append(
            {
                "guard": guard,
                "name": GUARD_NAMES[guard],
                "completed": int(row["completed"]),
                "detected": int(row["detected"]),
                "errors": int(row["errors"]),
                "detection_rate": row["detection_rate"],
                "primary_input_mode": row.get("primary_input_mode", _primary_input_mode(guard)),
                "by_input_mode": row.get("by_input_mode") or {},
            }
        )

    setting_rows = []
    for grid_point_id in settings["sampling"]["settings"]:
        suite, system_prompt, attack = _split_grid_point(grid_point_id)
        members = [row for row in case_rows if row["grid_point_id"] == grid_point_id]
        setting_rows.append(
            {
                "grid_point_id": grid_point_id,
                "suite": suite,
                "system_prompt": system_prompt,
                "attack": attack,
                "samples": len(members),
                "detected": {
                    guard: sum(
                        member["guard_results"][guard]["detected"] is True
                        for member in members
                    )
                    for guard in GUARDS
                },
            }
        )

    return {
        "experiment": {
            "id": EXPERIMENT_ID,
            "benchmark_id": settings["benchmark_id"],
            "agentic_model": settings["agentic_model"],
            "source_dataset": settings["source_dataset"],
            "split": settings["split"],
            "sample_count": int(case_manifest["case_count"]),
            "population_count": int(settings["sampling"]["population_samples"]),
            "settings_count": int(settings["sampling"]["population_settings"]),
            "seed": int(settings["sampling"]["seed"]),
            "labeling_protocol": settings["detection_point"]["labeling_protocol"],
            "language": settings["language"],
            "collection_mode": "translated_frozen_replay",
            "evaluation_mode": "chinese_injection_posthoc",
            "threshold": float(run_manifest["inline_probe"]["threshold"]),
            "checkpoint_id": run_manifest["inline_probe"]["checkpoint_id"],
            "layer": int(run_manifest["inline_probe"]["layer"]),
            "position": -1,
            "created_at": "2026-07-26",
        },
        "integrity": {
            "collection_audit": {"inline_request_fields_during_collection": 0},
            "frozen_sources": run_manifest["source_artifacts"],
            "replay_requests": len(cases),
            "distinct_prompt_fingerprints": len(
                {
                    _raw_probe_value(_primary_guard_row("inline_probing", rows), "native_prompt_token_fingerprint")
                    for rows in results["inline_probing"].values()
                }
            ),
            "guard_intervention": bool(run_manifest["methodology"]["guard_intervention"]),
            "replay_continuation_executed": False,
        },
        "behavior_metrics": summary["behavior"],
        "english_reference": summary.get("english_reference"),
        "guard_metrics": guard_metrics,
        "settings": setting_rows,
        "cases": case_rows,
    }


@lru_cache(maxsize=128)
def load_case_detail(sample_index: int) -> dict[str, Any]:
    overview = load_experiment_overview()
    case_summary = next(
        (
            row
            for row in overview["cases"]
            if int(row["sample_index"]) == int(sample_index)
        ),
        None,
    )
    if case_summary is None:
        raise KeyError(f"unknown audit sample index: {sample_index}")

    settings = _read_json(EVALUATION_ROOT / "settings.json")
    frozen_case = next(
        (
            row
            for row in _iter_jsonl(EVALUATION_ROOT / "cases.jsonl")
            if int(row["sample_index"]) == int(sample_index)
        ),
        None,
    )
    if frozen_case is None:
        raise KeyError(f"unknown frozen Chinese audit sample index: {sample_index}")
    dataset_root = FOLLOW_YOUR_HEART_ROOT / settings["dataset_root"]
    grid_root = dataset_root / "grid_points" / case_summary["grid_point_id"]
    decision = _find_jsonl_row(
        grid_root / "decision_points.jsonl",
        "decision_point_id",
        case_summary["decision_point_id"],
    )
    trace = _find_jsonl_row(
        grid_root / "traces.jsonl",
        "trace_id",
        case_summary["trace_id"],
    )
    replay = frozen_case["replay_request"]
    injection_indices = set(case_summary["injection_message_indices"])
    messages = [
        {
            "index": index,
            "role": str(message.get("role") or "unknown"),
            "content": _message_text(message),
            "is_injection": index in injection_indices,
            "tool_calls": message.get("tool_calls") or [],
            "tool_call_id": message.get("tool_call_id"),
            "name": message.get("name"),
        }
        for index, message in enumerate(replay["messages"])
    ]
    injected_text = frozen_case["injected_text"]
    exposed_tool_result = "\n\n".join(
        message["content"]
        for message in messages
        if message["is_injection"] and message["role"] == "tool"
    )
    guard_results = {
        guard: _guard_bundle(
            guard,
            _find_guard_rows(
                RESULT_ROOT / f"{guard}.jsonl",
                case_summary["decision_point_id"],
            ),
        )
        for guard in GUARDS
    }
    behavior = _find_last_jsonl_row(
        RESULT_ROOT / "behavior.jsonl",
        "decision_point_id",
        case_summary["decision_point_id"],
    )
    judgment = _find_last_jsonl_row(
        RESULT_ROOT / "behavior_judgments.jsonl",
        "decision_point_id",
        case_summary["decision_point_id"],
    )
    return {
        "case": case_summary,
        "trace": {
            "trace_id": trace["trace_id"],
            "case_id": trace.get("case_id"),
            "repeat_index": trace.get("repeat_index"),
            "injection_round_index": trace.get("injection_round_index") or [],
            "outcome": trace.get("outcome") or {},
        },
        "decision_point": {
            "decision_index": decision.get("decision_index"),
            "assistant_message_index": decision["assistant_message_index"],
            "request_model": replay.get("model"),
            "tool_choice": replay.get("tool_choice"),
            "tool_count": len(replay.get("tools") or []),
            "tool_names": [
                str((tool.get("function") or {}).get("name") or "unknown")
                for tool in replay.get("tools") or []
            ],
            "prompt_token_count": len(decision.get("prompt_token_ids") or []),
            "response_token_count": len(decision.get("response_token_ids") or []),
            "assistant_message": behavior.get("message") or {},
        },
        "messages": messages,
        "injected_text": injected_text,
        "exposed_tool_result": exposed_tool_result or injected_text,
        "guard_results": guard_results,
        "agent_behavior": {
            "message": behavior.get("message") or {},
            "finish_reason": behavior.get("finish_reason"),
            "latency_ms": behavior.get("latency_ms"),
            "label": judgment.get("label"),
            "confidence": judgment.get("confidence"),
            "reason": judgment.get("reason"),
            "judge_model": judgment.get("judge_model"),
        },
        "evidence": {
            "replay_request_sha256": frozen_case["replay_request_sha256"],
            "injected_text_sha256": frozen_case["injected_text_sha256"],
            "native_prompt_token_fingerprint": _raw_probe_value(
                guard_results["inline_probing"],
                "native_prompt_token_fingerprint",
            ),
            "input_attempt_fingerprint": _raw_probe_value(
                guard_results["inline_probing"],
                "input_attempt_fingerprint",
            ),
        },
    }


def _compact_guard_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "detected": row.get("detected"),
        "error": row.get("error"),
        "latency_ms": row.get("latency_ms"),
        "score": row.get("score"),
        "threshold": row.get("threshold"),
        "safety_label": row.get("safety_label"),
        "categories": row.get("categories") or [],
        "suggestion": row.get("suggestion"),
        "input_mode": row.get("input_mode"),
        "input_sha256": row.get("input_sha256"),
        "input_chars": row.get("input_chars"),
    }


def _primary_input_mode(guard: str) -> str:
    return TOOL_RESULT if guard in {"qwen3_guard", "netease_yidun"} else "native"


def _row_input_mode(guard: str, row: dict[str, Any]) -> str:
    return str(row.get("input_mode") or _primary_input_mode(guard))


def _index_guard_rows(path: Path, guard: str) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for row in _iter_jsonl(path):
        result.setdefault(str(row["decision_point_id"]), {})[
            _row_input_mode(guard, row)
        ] = row
    return result


def _primary_guard_row(guard: str, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary = _primary_input_mode(guard)
    if primary in rows:
        return rows[primary]
    if rows:
        return next(iter(rows.values()))
    raise KeyError(f"no results for guard {guard}")


def _compact_guard_bundle(
    guard: str,
    rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    value = _compact_guard_result(_primary_guard_row(guard, rows))
    value["primary_input_mode"] = _primary_input_mode(guard)
    value["input_modes"] = {
        mode: _compact_guard_result(row) for mode, row in sorted(rows.items())
    }
    return value


def _guard_bundle(guard: str, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    value = dict(_primary_guard_row(guard, rows))
    value["primary_input_mode"] = _primary_input_mode(guard)
    value["input_modes"] = {mode: row for mode, row in sorted(rows.items())}
    return value


def _find_guard_rows(path: Path, decision_point_id: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    guard = path.stem
    for row in _iter_jsonl(path):
        if row.get("decision_point_id") == decision_point_id:
            rows[_row_input_mode(guard, row)] = row
    if not rows:
        raise KeyError(f"could not find decision_point_id={decision_point_id!r} in {path}")
    return rows


def _split_grid_point(value: str) -> tuple[str, str, str]:
    parts = str(value).split("__", 2)
    if len(parts) != 3:
        return str(value), "unknown", "unknown"
    return parts[0], parts[1], parts[2]


def _raw_probe_value(row: dict[str, Any], key: str) -> Any:
    raw = row.get("raw_output")
    if not raw:
        return None
    try:
        return json.loads(raw).get(key)
    except json.JSONDecodeError:
        return None


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            value = item.get("text", item.get("content"))
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def _find_jsonl_row(path: Path, key: str, value: Any) -> dict[str, Any]:
    for row in _iter_jsonl(path):
        if row.get(key) == value:
            return row
    raise KeyError(f"could not find {key}={value!r} in {path}")


def _find_last_jsonl_row(path: Path, key: str, value: Any) -> dict[str, Any]:
    result = None
    for row in _iter_jsonl(path):
        if row.get(key) == value:
            result = row
    if result is None:
        raise KeyError(f"could not find {key}={value!r} in {path}")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open() as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"expected JSON object row: {path}")
                yield value
