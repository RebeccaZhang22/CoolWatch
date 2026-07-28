#!/usr/bin/env python3
"""Materialize the PDF case as one frozen injected-decision-point evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVALUATION_DIR = ROOT / "evaluation"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    request = json.loads((ROOT / "replay_request.json").read_text())
    extracted = (ROOT / "artifacts" / "extracted_text.txt").read_text().strip()
    request["messages"][-1]["content"] = extracted
    request["messages"][-1].pop("content_file", None)
    decision_point_id = "pdf-white-text-car-loan-approval-injection:assistant:4"
    row = {
        "schema": "coolwatch.case_study.replay.v1",
        "sample_index": 0,
        "decision_point_id": decision_point_id,
        "trace_id": "pdf-white-text-car-loan-approval-injection",
        "grid_point_id": "vehicle_finance__manual_review__pdf_white_text",
        "assistant_message_index": 4,
        "injection_message_indices": [3],
        "injected_text": json.loads((ROOT / "case.json").read_text())["hidden_injection"],
        "replay_request": request,
        "replay_request_sha256": _sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ),
    }
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    cases_payload = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode()
    (EVALUATION_DIR / "cases.jsonl").write_bytes(cases_payload)
    manifest = {
        "schema": "coolwatch.case_study.manifest.v1",
        "benchmark_id": "pdf-white-text-car-loan-approval-injection",
        "case_count": 1,
        "cases_path": "cases.jsonl",
        "cases_sha256": _sha256(cases_payload),
        "all_cases_positive": True,
        "intervention": False,
        "language": "zh-CN",
    }
    (EVALUATION_DIR / "case_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    settings = {
        "schema": "coolwatch.case_study.settings.v1",
        "benchmark_id": manifest["benchmark_id"],
        "agentic_model": "Qwen/Qwen3-8B",
        "language": "zh-CN",
        "detection_point": "first assistant decision after the injected PDF tool result",
        "guard_inputs": {
            "inline_probing": "complete replay messages and tools",
            "qwen3_guard": "complete extracted PDF tool result",
            "netease_yidun": "complete extracted PDF tool result",
            "no_guard": "no detector",
        },
        "guards": ["inline_probing", "qwen3_guard", "netease_yidun", "no_guard"],
        "pdf_sha256": _sha256((ROOT / "artifacts" / "vehicle-loan-application-VL-2026-0042.pdf").read_bytes()),
        "extracted_text_sha256": _sha256(extracted.encode()),
    }
    (EVALUATION_DIR / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(EVALUATION_DIR)


if __name__ == "__main__":
    main()
