from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.experiment_audit import load_finvault_case_detail, load_finvault_overview


DEFAULT_REPLAY_CASE = 0
DEFAULT_REPLAY_MODEL = "qwen3-32b"
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[1] / "data" / "finvault" / "system_prompts.jsonl"
FEATURED_SCENARIO_CASES = {
    "00": (0, 1, 3),
    "02": (9, 12),
    "03": (13, 15),
    "15": (55, 56),
    "26": (91, 92),
    "30": (104, 105, 106),
}
GUARD_NAMES = {
    "baseline": "无防护",
    "qwen_guard": "Qwen3Guard",
    "llama_prompt_guard": "Llama Prompt Guard 2",
    "safegauge": "SafeGauge",
    "inline_probing": "Activation Probing",
    "netease_yidun": "网易易盾",
}
GUARD_DETAIL_KEYS = {
    "qwen_guard": "query_guard",
    "llama_prompt_guard": "llama_prompt_guard",
    "safegauge": "suffix_probe",
    "inline_probing": "activation_probe",
    "netease_yidun": "netease_yidun",
}


def _event(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@lru_cache(maxsize=1)
def _source_cases() -> dict[int, dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "data" / "finvault" / "cases.jsonl"
    rows: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows[int(row["sample_index"])] = row
    return rows


@lru_cache(maxsize=1)
def _system_prompts() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with SYSTEM_PROMPT_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows[str(row["scenario_id"])] = row
    return rows


def _prompt_for(source_row: dict[str, Any]) -> str:
    translated = source_row.get("translation") or {}
    source = source_row.get("source") or {}
    return str(translated.get("attack_prompt") or source.get("attack_prompt") or "").strip()


def _system_prompt_for(scenario_id: str) -> str:
    row = _system_prompts().get(str(scenario_id), {})
    return str(row.get("system_prompt_zh") or row.get("system_prompt") or "")


def _candidate(row: dict[str, Any]) -> dict[str, Any]:
    sample_index = int(row["sample_index"])
    source_row = _source_cases()[sample_index]
    risk_name = "、".join(row.get("risk_names") or []) or "高风险任务"
    domain_name = str(row.get("domain_name") or row.get("scenario_name") or "高风险任务")
    return {
        "id": f"finvault-{sample_index}",
        "sample_index": sample_index,
        "label": f"{row['scenario_name']} · {risk_name}",
        "type": risk_name,
        "attack_set": domain_name,
        "category": risk_name,
        "prompt_name": f"Case #{sample_index + 1}",
        "query": _prompt_for(source_row),
        "source": "已记录沙盒轨迹",
        "metadata": {
            "sample_index": sample_index,
            "scenario_id": row["scenario_id"],
            "replay_scenario_id": f"finvault-{row['scenario_id']}",
            "scenario_name": row["scenario_name"],
            "system_prompt_id": source_row.get("system_prompt_id") or "",
            "vulnerability": row.get("vulnerability") or "",
            "severity": row.get("severity") or "HIGH",
            "risk_names": row.get("risk_names") or [],
            "dataset_name": row.get("dataset_name") or "",
            "attack_success": bool((row.get("model_result") or {}).get("attack_success")),
            "model": "Qwen3-32B",
        },
    }


def replay_catalog(limit: int = 18, model: str = DEFAULT_REPLAY_MODEL) -> dict[str, Any]:
    overview = load_finvault_overview(model)
    rows = [
        row
        for row in overview["cases"]
        if row.get("dataset_type") == "original"
        and row.get("evaluation_status") == "unsafe"
        and int(row["sample_index"]) in _source_cases()
    ]
    by_index = {int(row["sample_index"]): row for row in rows}
    selected = [
        by_index[sample_index]
        for sample_indexes in FEATURED_SCENARIO_CASES.values()
        for sample_index in sample_indexes
        if sample_index in by_index
    ]
    candidates = [_candidate(row) for row in selected[: max(1, min(int(limit), 30))]]
    default_candidate = next(
        (item for item in candidates if item["sample_index"] == DEFAULT_REPLAY_CASE),
        candidates[0],
    )
    system_prompt_rows = {
        str(item["metadata"]["scenario_id"]): {
            "scenario_name": item["metadata"]["scenario_name"],
            "content": _system_prompt_for(str(item["metadata"]["scenario_id"])),
        }
        for item in candidates
    }
    replay_scenarios = []
    for source_scenario_id in FEATURED_SCENARIO_CASES:
        scenario_cases = [
            item for item in candidates
            if str(item["metadata"]["scenario_id"]) == source_scenario_id
        ]
        if not scenario_cases:
            continue
        first_case = scenario_cases[0]
        replay_scenarios.append({
            "id": f"finvault-{source_scenario_id}",
            "category": "finvault",
            "name": first_case["metadata"]["scenario_name"],
            "target": "高风险任务",
            "description": "使用已记录的沙盒轨迹复现 Agent 高风险行为与检测判定。",
            "systemPrompt": system_prompt_rows[source_scenario_id]["content"],
            "documents": [],
            "normalPrompt": first_case["query"],
        })
    default_scenario_id = str(default_candidate["metadata"]["replay_scenario_id"])
    default_scenario = next(
        (scenario for scenario in replay_scenarios if scenario["id"] == default_scenario_id),
        replay_scenarios[0],
    )
    return {
        "model": "Qwen3-32B",
        "recorded": True,
        "default_case": default_candidate["sample_index"],
        "scenario": default_scenario,
        "scenarios": replay_scenarios,
        "system_prompts": system_prompt_rows,
        "cases": candidates,
    }


def replay_metadata(sample_index: int = DEFAULT_REPLAY_CASE, model: str = DEFAULT_REPLAY_MODEL) -> dict[str, Any]:
    detail = load_finvault_case_detail(sample_index, model)
    case = detail["case"]
    prompt = str(detail["translation"].get("attack_prompt") or detail["source"].get("attack_prompt") or "")
    system_prompt = str(detail["system_prompt"].get("translation") or detail["system_prompt"].get("content") or "")
    return {
        "sample_index": sample_index,
        "case_key": case["case_key"],
        "scenario_id": case["scenario_id"],
        "scenario_name": case["scenario_name"],
        "dataset_name": case["dataset_name"],
        "vulnerability": case["vulnerability"],
        "severity": case["severity"],
        "risk_names": case.get("risk_names") or [],
        "prompt": prompt,
        "system_prompt": system_prompt,
        "model": detail["evaluation"].get("model") or "Qwen3-32B",
        "recorded": True,
        "tool_calls": detail["evaluation"].get("tool_calls") or 0,
        "attack_success": detail["evaluation"].get("attack_success"),
        "evidence_note": "本次运行只回放已保存的模型输出、沙盒工具结果和检测判定，不请求真实 vLLM。",
    }


def _compact_json(value: Any, limit: int = 520) -> str:
    if value in (None, "", [], {}):
        return "无返回数据"
    text = json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value.strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}\n…"


def _guard_probability(guard_id: str, record: dict[str, Any]) -> float | None:
    if guard_id == "safegauge":
        return record.get("onset_score", record.get("max_score"))
    if guard_id == "inline_probing":
        return record.get("onset_probability", record.get("max_probability"))
    if guard_id == "llama_prompt_guard":
        return record.get("probability")
    return record.get("risk_probability")


def _guard_threshold(guard_id: str, record: dict[str, Any]) -> float | None:
    if guard_id == "inline_probing":
        return record.get("probability_threshold")
    return record.get("threshold")


def _guard_labels(guard_id: str, record: dict[str, Any], detail: dict[str, Any]) -> list[str]:
    labels = record.get("categories") or record.get("labels") or []
    if guard_id == "llama_prompt_guard" and record.get("label"):
        labels = [record["label"]]
    if guard_id == "safegauge" and record.get("risky") is True:
        labels = detail["case"].get("risk_names") or ["high_risk_task"]
    if guard_id == "inline_probing" and record.get("risky") is True:
        labels = ["runtime_hidden_state", *(detail["case"].get("risk_names") or [])]
    return [str(value) for value in labels if str(value).strip()]


def _guard_result(guard_id: str, detail: dict[str, Any], assistant_message: str) -> dict[str, Any]:
    record = detail.get(GUARD_DETAIL_KEYS[guard_id]) or {}
    error = record.get("error")
    available = record.get("status") == "complete" and not error
    risky = record.get("risky") if available else None
    blocked = bool(record.get("blocked") and risky is True)
    status = "检测失败" if not available else "命中风险" if risky else "未命中"
    safety_label = record.get("safety_label") or record.get("label") or record.get("suggestion_text")
    return {
        "guard_id": guard_id,
        "guard_name": GUARD_NAMES[guard_id],
        "status": status,
        "blocked": blocked,
        "latency_ms": int(record.get("latency_ms") or 0),
        "output": assistant_message,
        "raw_output": assistant_message,
        "leakage": {"exact_match": 0, "coverage": 0, "rouge_l": 0},
        "query_risk": risky,
        "matched_labels": _guard_labels(guard_id, record, detail),
        "connected": available,
        "note": (
            "来自该 Case 已保存的审计结果。"
            if available
            else f"该 Case 没有可用的 {GUARD_NAMES[guard_id]} 审计结果。"
        ),
        "safety_label": safety_label,
        "task": "high_risk_task" if guard_id == "safegauge" else "runtime_hidden_state_probe" if guard_id == "inline_probing" else None,
        "probability": _guard_probability(guard_id, record),
        "threshold": _guard_threshold(guard_id, record),
        "raw_guard_output": str(record.get("raw_output") or _compact_json(record, 1600)),
    }


def _tool_name(turn: dict[str, Any]) -> str:
    action = turn.get("parsed_action") or {}
    return str(action.get("tool") or turn.get("environment_info", {}).get("tool_called") or "unknown_tool")


def _tool_args(turn: dict[str, Any]) -> dict[str, Any]:
    action = turn.get("parsed_action") or {}
    return action.get("args") or {}


def _tool_result(turn: dict[str, Any]) -> Any:
    return turn.get("environment_info", {}).get("tool_result") or turn.get("environment_observation") or ""


def _recorded_transcript(detail: dict[str, Any], blocked_by: str | None) -> str:
    if blocked_by:
        guard_name = GUARD_NAMES[blocked_by]
        return (
            f"已识别为 **高风险任务**，{guard_name} 根据保存的审核结果建议拦截。\n\n"
            "请求未进入 Agent，后续工具调用未执行。"
        )

    evaluation = detail["evaluation"]
    turns = evaluation.get("turns") or []
    sections = ["正在按已记录数据复现沙盒轨迹。"]
    for index, turn in enumerate(turns, start=1):
        tool = _tool_name(turn)
        args = _compact_json(_tool_args(turn), 260)
        result = _compact_json(_tool_result(turn), 420)
        sections.append(
            f"### 工具调用 {index} · `{tool}`\n"
            f"参数：\n```json\n{args}\n```\n"
            f"沙盒返回：\n```json\n{result}\n```"
        )

    attack_success = evaluation.get("attack_success") is True
    final_status = str(evaluation.get("final_decision") or "INCOMPLETE")
    risks = "、".join(evaluation.get("vulnerabilities_triggered") or []) or "未触发漏洞"
    verdict = "攻击成功" if attack_success else "安全结束"
    sections.append(f"**沙盒结果：{verdict}** · 最终状态 `{final_status}` · {risks}")
    return "\n\n".join(sections)


def _agent_trace(detail: dict[str, Any], blocked_by: str | None) -> list[dict[str, Any]]:
    prompt = str(detail["translation"].get("attack_prompt") or detail["source"].get("attack_prompt") or "")
    trace = [
        {
            "name": "Recorded Sandbox Load",
            "status": "success",
            "input": f"Case #{detail['case']['sample_index'] + 1}",
            "output": "已载入保存的 System Prompt、用户请求、工具轨迹与 Guard 审计结果。",
            "duration": 0,
            "error": None,
        }
    ]
    if blocked_by:
        trace.append(
            {
                "name": f"{GUARD_NAMES[blocked_by]} Guard Check",
                "status": "success",
                "input": prompt,
                "output": "命中高风险任务，模拟链路在进入 Agent 前停止。",
                "duration": 0,
                "error": None,
            }
        )
        return trace

    for turn in detail["evaluation"].get("turns") or []:
        trace.append(
            {
                "name": f"Recorded Tool · {_tool_name(turn)}",
                "status": "success",
                "input": _compact_json(_tool_args(turn), 900),
                "output": _compact_json(_tool_result(turn), 1200),
                "duration": 0,
                "error": None,
            }
        )
    return trace


def build_replay_response(
    detail: dict[str, Any],
    selected_guards: list[str],
) -> dict[str, Any]:
    guard_ids = [guard_id for guard_id in selected_guards if guard_id in GUARD_DETAIL_KEYS]
    preliminary_results = {
        guard_id: _guard_result(guard_id, detail, "")
        for guard_id in guard_ids
    }
    blocked_by = next((guard_id for guard_id in guard_ids if preliminary_results[guard_id]["blocked"]), None)
    assistant_message = _recorded_transcript(detail, blocked_by)
    baseline_status = "攻击被拦截" if blocked_by else "攻击成功" if detail["evaluation"].get("attack_success") else "安全结束"
    guard_results: dict[str, dict[str, Any]] = {
        "baseline": {
            "guard_id": "baseline",
            "guard_name": GUARD_NAMES["baseline"],
            "status": baseline_status,
            "blocked": False,
            "latency_ms": 0,
            "output": assistant_message,
            "raw_output": assistant_message,
            "leakage": {"exact_match": 0, "coverage": 0, "rouge_l": 0},
            "query_risk": None,
            "matched_labels": detail["case"].get("risk_names") or [],
            "connected": True,
            "note": "使用已保存的 Qwen3-32B 沙盒轨迹，不调用真实模型。",
            "safety_label": None,
            "task": None,
            "probability": None,
            "threshold": None,
            "raw_guard_output": "",
        }
    }
    for guard_id in guard_ids:
        guard_results[guard_id] = _guard_result(guard_id, detail, assistant_message)

    case = detail["case"]
    evaluation = detail["evaluation"]
    leakage_summary = (
        f"{GUARD_NAMES[blocked_by]} 已拦截高风险任务"
        if blocked_by
        else "已复现攻击成功轨迹"
        if evaluation.get("attack_success")
        else "已复现安全轨迹"
    )
    return {
        "active_guard": blocked_by or "baseline",
        "assistant_message": assistant_message,
        "guard_results": guard_results,
        "leakage_summary": leakage_summary,
        "output_blocked": bool(blocked_by),
        "output_guard": {"exact_match_threshold": 80, "rouge_l_threshold": 80},
        "matched_spans": [],
        "rag_trace": [],
        "agent_trace": _agent_trace(detail, blocked_by),
        "replay_result": {
            "finvault_replay": True,
            "recorded": True,
            "sample_index": case["sample_index"],
            "scenario_id": case["scenario_id"],
            "scenario_name": case["scenario_name"],
            "risk_names": case.get("risk_names") or [],
            "vulnerability": case.get("vulnerability") or "",
            "attack_success": evaluation.get("attack_success"),
            "final_decision": evaluation.get("final_decision"),
            "tool_calls": evaluation.get("tool_calls") or 0,
            "blocked_by": blocked_by,
        },
    }


class FinVaultReplayService:
    """Replay saved FinVault evidence through the same SSE shape as chat.

    No model or live sandbox is contacted. The source of truth is the recorded
    case result and per-guard audit artifacts already published by the project.
    """

    def __init__(self, _: Settings) -> None:
        pass

    async def close(self) -> None:
        return None

    async def stream(
        self,
        sample_index: int = DEFAULT_REPLAY_CASE,
        selected_guards: list[str] | None = None,
    ) -> AsyncIterator[str]:
        selected_guards = selected_guards or []
        try:
            detail = load_finvault_case_detail(sample_index, DEFAULT_REPLAY_MODEL)
            response = build_replay_response(detail, selected_guards)
            yield _event("status", {"message": "正在载入已记录沙盒"})
            await asyncio.sleep(0.08)

            for guard_id in selected_guards:
                guard = response["guard_results"].get(guard_id)
                if guard is None:
                    continue
                yield _event(
                    "status",
                    {"message": f"{guard['guard_name']}：{guard['status']}（保存的审计结果）"},
                )
                await asyncio.sleep(0.08)

            if response["replay_result"]["blocked_by"]:
                yield _event("status", {"message": "高风险任务已在进入 Agent 前拦截"})
            else:
                yield _event("status", {"message": "正在复现保存的 Agent 工具轨迹"})

            for block in response["assistant_message"].split("\n\n"):
                yield _event("delta", {"content": f"{block}\n\n"})
                await asyncio.sleep(0.08)

            yield _event("final", response)
            yield _event("done", {"ok": True, "recorded": True})
        except Exception as error:
            yield _event("error", {"message": f"记录轨迹加载失败：{error}"})
