from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any


class UsageStore:
    """Small local usage ledger for the demo/API console."""

    def __init__(self) -> None:
        self.path = Path(__file__).resolve().parents[1] / ".runtime" / "usage_events.jsonl"
        self._lock = RLock()

    def append(self, *, user: dict[str, Any], request_id: str,
               messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
               result: dict[str, Any]) -> None:
        query = next(
            (item.get("content", "") for item in reversed(messages) if item.get("role") == "user"),
            messages[-1].get("content", "") if messages else "",
        )
        event = {
            "created_at": datetime.now(UTC).isoformat(),
            "account_id": user.get("id"),
            "account_email": user.get("email"),
            "request_id": request_id,
            "query": query,
            "messages": messages,
            "tools": tools,
            "action": result.get("action"),
            "result": result.get("result", {}),
            "per_risk": result.get("per_risk", {}),
            "per_entry": result.get("per_entry", {}),
            "usage": result.get("usage", {}),
            "latency_ms": result.get("latency_ms", {}),
            "detector_model": result.get("detector_model"),
            "bank_version": result.get("bank_version"),
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def page_for_user(self, user_id: str, *, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                lines = []
        events = []
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("account_id") == user_id:
                events.append(event)
        total = len(events)
        pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, pages))
        start = (page - 1) * page_size
        return {"events": events[start:start + page_size], "total": total,
                "page": page, "page_size": page_size, "pages": pages}

    def list_for_user(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []
        events = []
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("account_id") == user_id:
                events.append(event)
                if len(events) >= max(1, min(limit, 500)):
                    break
        return events

    def page_all(self, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """Return a bounded, admin-safe view of calls across all accounts."""
        events = self._all_events()
        total = len(events)
        pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, pages))
        start = (page - 1) * page_size
        safe_keys = {
            "created_at", "account_id", "account_email", "request_id", "query",
            "action", "per_risk", "usage", "latency_ms", "detector_model", "bank_version",
        }
        selected = [
            {key: value for key, value in event.items() if key in safe_keys}
            for event in events[start:start + page_size]
        ]
        return {
            "events": selected,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "blocked": sum(event.get("action") == "block" for event in events),
        }

    def counts_by_account(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._all_events():
            account_id = event.get("account_id")
            if isinstance(account_id, str) and account_id:
                counts[account_id] = counts.get(account_id, 0) + 1
        return counts

    def _all_events(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []
        events: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events
