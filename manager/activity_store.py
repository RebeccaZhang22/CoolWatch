"""Persistent demo activity, request outcomes, and review labels for managers."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from manager.config import get_config


def now():
    return datetime.now(UTC).isoformat()


def redact(value):
    """Keep prompts and tool arguments, remove structured credentials at every depth."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            secret = any(word in normalized for word in ("password", "secret", "authorization", "cookie", "api_key"))
            secret = secret or normalized in {"token", "access_token", "refresh_token", "session_digest", "password_digest"}
            result[key] = "[REDACTED]" if secret else redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def risk_findings(payload):
    """Extract observed results only; selected attacks and detector errors are not risks."""
    found = []
    if not isinstance(payload, dict):
        return found
    for branch in ("baseline", "defended"):
        if isinstance(payload.get(branch), dict):
            found.extend({**item, "branch": branch} for item in risk_findings(payload[branch]))
    for signal in payload.get("defense_signals", []):
        if not isinstance(signal, dict):
            continue
        metadata = signal.get("metadata") or {}
        disabled = metadata.get("disabled_risks", [])
        risks = [(key, data) for key, data in metadata.get("per_risk", {}).items()
                 if key not in disabled and isinstance(data, dict) and data.get("flagged") is True]
        if signal.get("status") == "error":
            continue
        if not risks and (signal.get("status") == "risk" or signal.get("blocked")):
            risks = [("detector_risk", signal)]
        for key, data in risks:
            found.append({"kind": key, "detector": signal.get("defense_id"), "stage": signal.get("stage"),
                          "blocked": bool(signal.get("blocked")), "score": data.get("score", signal.get("score")),
                          "threshold": data.get("threshold", signal.get("threshold")), "detail": signal.get("detail", "")})
    for key, data in (payload.get("per_risk") or {}).items():
        if isinstance(data, dict) and data.get("flagged") is True and key not in payload.get("disabled_risks", []):
            found.append({"kind": key, "detector": payload.get("detector_model", "probe_bank"),
                          "blocked": payload.get("action") == "block", "score": data.get("score"), "threshold": data.get("threshold")})
    for exposure in payload.get("asset_exposures", []):
        if exposure.get("exposed_in_output") or exposure.get("exposed_to_client"):
            found.append({"kind": "exposure:" + exposure.get("kind", "unknown"), "asset": exposure.get("asset_id"),
                          "blocked": False, "detail": exposure.get("label", "")})
    if payload.get("verdict") == "compromised" or (payload.get("attack") or {}).get("success") is True:
        found.append({"kind": "attack_succeeded", "blocked": False, "detail": (payload.get("attack") or {}).get("summary", "")})
    if payload.get("output_blocked") or payload.get("blocked") or payload.get("action") == "block":
        if not any(item.get("blocked") for item in found):
            found.append({"kind": "blocked", "blocked": True})
    return found


class ActivityStore:
    def __init__(self, path: Path | None = None):
        self.path = path or get_config().data_dir / "activity.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS activity (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    kind TEXT NOT NULL, name TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
                    path TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'completed', http_status INTEGER,
                    duration_ms REAL, is_run INTEGER NOT NULL DEFAULT 0,
                    request_json TEXT NOT NULL DEFAULT '{}', response_json TEXT NOT NULL DEFAULT '{}',
                    risks_json TEXT NOT NULL DEFAULT '[]', risk_count INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0, properties_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS activity_user_time ON activity(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS activity_time ON activity(created_at DESC);
                CREATE INDEX IF NOT EXISTS activity_session ON activity(user_id, session_id);
                CREATE TABLE IF NOT EXISTS leads (
                    user_id TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT NOT NULL,
                    updated_at TEXT NOT NULL, updated_by TEXT NOT NULL
                );
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, user_id, *, kind, name, event_id=None, session_id="", path="", method="",
               status="completed", is_run=False, request=None, properties=None):
        event_id = event_id or "evt_" + uuid4().hex
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO activity "
                       "(id, user_id, created_at, kind, name, session_id, path, method, status, is_run, request_json, properties_json) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (event_id, user_id, now(), kind, name, session_id, path, method, status, int(is_run),
                        json.dumps(redact(request or {}), ensure_ascii=False), json.dumps(redact(properties or {}), ensure_ascii=False)))
        return event_id

    def finish(self, event_id, *, request, response, status, http_status, duration_ms, session_id="", properties=None):
        risks = risk_findings(response)
        with self.connect() as db:
            db.execute("UPDATE activity SET request_json=?, response_json=?, risks_json=?, risk_count=?, blocked=?, "
                       "status=?, http_status=?, duration_ms=?, session_id=CASE WHEN ? != '' THEN ? ELSE session_id END, "
                       "properties_json=? WHERE id=?",
                       (json.dumps(redact(request), ensure_ascii=False), json.dumps(redact(response), ensure_ascii=False),
                        json.dumps(risks, ensure_ascii=False), len(risks), int(any(r.get("blocked") for r in risks)),
                        status, http_status, duration_ms, session_id, session_id,
                        json.dumps(redact(properties or {}), ensure_ascii=False), event_id))

    @staticmethod
    def where(*, user_id="", since="", until="", kind="", risk_only=False, session_id="", q=""):
        clauses, args = ["1=1"], []
        for column, op, value in [("user_id", "=", user_id), ("created_at", ">=", since),
                                  ("created_at", "<=", until), ("kind", "=", kind), ("session_id", "=", session_id)]:
            if value:
                clauses.append(f"{column} {op} ?")
                args.append(value)
        if risk_only:
            clauses.append("risk_count > 0")
        if q:
            clauses.append("(name LIKE ? OR path LIKE ? OR request_json LIKE ? OR properties_json LIKE ?)")
            args.extend([f"%{q}%"] * 4)
        return " AND ".join(clauses), args

    def events(self, *, page=1, page_size=20, **filters):
        where, args = self.where(**filters)
        with self.connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM activity WHERE {where}", args).fetchone()[0]
            pages = max(1, (total + page_size - 1) // page_size)
            page = min(page, pages)
            rows = db.execute(f"SELECT id,user_id,created_at,kind,name,session_id,path,method,status,http_status,"
                              f"duration_ms,is_run,risk_count,blocked,risks_json,properties_json FROM activity WHERE {where} "
                              "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", [*args, page_size, (page - 1) * page_size]).fetchall()
        return {"events": [self.decode(row) for row in rows], "total": total, "page": page, "pages": pages}

    @staticmethod
    def decode(row):
        data = dict(row)
        for key in list(data):
            if key.endswith("_json"):
                data[key[:-5]] = json.loads(data.pop(key))
        return data

    def detail(self, event_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM activity WHERE id = ?", (event_id,)).fetchone()
        return self.decode(row) if row else None

    def metrics(self, **filters):
        where, args = self.where(**filters)
        with self.connect() as db:
            totals = dict(db.execute(f"SELECT COUNT(DISTINCT user_id) AS active_users, "
                                    "COALESCE(SUM(kind='interaction'),0) AS interactions, "
                                    "COALESCE(SUM(kind='request'),0) AS requests, COALESCE(SUM(is_run),0) AS runs, "
                                    "COALESCE(SUM(risk_count>0),0) AS risky_requests, COALESCE(SUM(blocked),0) AS blocked, "
                                    f"COALESCE(SUM(status='error'),0) AS errors FROM activity WHERE {where}", args).fetchone())
            buckets = db.execute(f"SELECT risks_json FROM activity WHERE {where} AND risk_count > 0", args).fetchall()
        counts = {}
        for row in buckets:
            for kind in {item["kind"] for item in json.loads(row[0])}:
                counts[kind] = counts.get(kind, 0) + 1
        return {**totals, "risk_distribution": sorted([{"kind": k, "count": v} for k, v in counts.items()], key=lambda x: -x["count"])}

    def users(self, users, *, q="", engagement="", lead_status="", since="", until="", page=1, page_size=20):
        where, args = self.where(since=since, until=until)
        with self.connect() as db:
            rows = db.execute(f"SELECT user_id,MAX(created_at) AS last_active, COUNT(*) AS events, "
                              "SUM(kind='interaction') AS interactions,SUM(kind='request') AS requests, "
                              "SUM(is_run AND status='completed') AS runs,SUM(risk_count>0) AS risky_requests, "
                              "COUNT(DISTINCT CASE WHEN is_run AND status='completed' THEN substr(created_at,1,10) END) AS run_days "
                              f"FROM activity WHERE {where} GROUP BY user_id", args).fetchall()
            metrics = {row["user_id"]: dict(row) for row in rows}
            leads = {row["user_id"]: dict(row) for row in db.execute("SELECT * FROM leads")}
        result = []
        for user in users.values():
            if q.lower() not in (user["email"] + user["id"]).lower():
                continue
            item = {**user, "last_active": None, "events": 0, "interactions": 0, "requests": 0, "runs": 0, "risky_requests": 0,
                    **metrics.get(user["id"], {}), "lead": leads.get(user["id"], {"status": "unreviewed", "note": ""})}
            item["engagement"] = ("engaged" if item["runs"] >= 5 or item.get("run_days", 0) >= 2 else
                                  "tried" if item["runs"] else "exploring" if item["requests"] or item["interactions"] else "registered")
            if engagement and item["engagement"] != engagement or lead_status and item["lead"]["status"] != lead_status:
                continue
            result.append(item)
        result.sort(key=lambda x: x["last_active"] or x["created_at"], reverse=True)
        total = len(result)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        return {"users": result[(page - 1) * page_size:page * page_size], "total": total, "page": page, "pages": pages}

    def label(self, user_id, status, note, manager):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO leads VALUES (?,?,?,?,?)", (user_id, status, note, now(), manager))
