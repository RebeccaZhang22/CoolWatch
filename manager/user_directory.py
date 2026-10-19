"""Read-only access to demo user metadata and historical usage; no backend imports."""
import json
import sqlite3
from pathlib import Path


class UserDirectory:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def users_by_id(self):
        if not self.path.exists():
            return {}
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute("SELECT id, email, role, created_at FROM users").fetchall()
            return {row["id"]: dict(row) for row in rows}
        finally:
            db.close()

    def list_users(self, *, page=1, page_size=20):
        users = sorted(self.users_by_id().values(), key=lambda item: item["created_at"], reverse=True)
        total = len(users)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        return {"users": users[(page - 1) * page_size:page * page_size], "total": total,
                "page": page, "pages": pages, "page_size": page_size}


class LegacyUsage:
    def __init__(self, path: Path):
        self.path = path

    def events(self):
        if not self.path.exists():
            return []
        result = []
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        result.append(event)
                except ValueError:
                    continue
        return list(reversed(result))

    def counts_by_account(self):
        counts = {}
        for item in self.events():
            user_id = item.get("account_id")
            if user_id:
                counts[user_id] = counts.get(user_id, 0) + 1
        return counts

    def page_all(self, *, page=1, page_size=20):
        events = self.events()
        total = len(events)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        keys = {"created_at", "account_id", "account_email", "request_id", "query", "action",
                "per_risk", "usage", "latency_ms", "detector_model", "bank_version"}
        return {"events": [{key: value for key, value in event.items() if key in keys}
                           for event in events[(page - 1) * page_size:page * page_size]],
                "total": total, "pages": pages, "page": page, "page_size": page_size,
                "blocked": sum(event.get("action") == "block" for event in events)}
