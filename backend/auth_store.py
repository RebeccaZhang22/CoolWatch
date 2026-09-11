"""SQLite-backed accounts, browser sessions, and API tokens."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any


class AuthStore:
    """Persist authentication state locally without storing plaintext tokens."""

    def __init__(self, path: Path | None = None, legacy_path: Path | None = None) -> None:
        runtime = Path(__file__).resolve().parents[1] / ".runtime"
        self.path = path or runtime / "prospectmonitor.db"
        self.legacy_path = legacy_path or runtime / "prospectmonitor_auth.json"
        self._lock = RLock()
        self._initialize()

    def register(self, email: str, password: str) -> dict[str, Any]:
        email = self._normalize_email(email)
        self._validate_password(password)
        password_record = self._password_record(password)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise ValueError("该邮箱已经注册，请直接登录。")
            user_id = f"usr_{secrets.token_hex(8)}"
            connection.execute(
                "INSERT INTO users (id, email, role, password_salt, password_digest, created_at) "
                "VALUES (?, ?, 'member', ?, ?, ?)",
                (user_id, email, password_record["salt"], password_record["digest"], self._now()),
            )
            session, token = self._issue(connection, user_id)
            user = self._user_row(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
            return {"user": user, "session": session, "token": token}

    def ensure_admin(self, email: str, password: str) -> dict[str, str]:
        """Create an admin if absent, or promote an existing account."""
        email = self._normalize_email(email)
        self._validate_password(password)
        password_record = self._password_record(password)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None:
                user_id = f"usr_{secrets.token_hex(8)}"
                connection.execute(
                    "INSERT INTO users (id, email, role, password_salt, password_digest, created_at) "
                    "VALUES (?, ?, 'admin', ?, ?, ?)",
                    (user_id, email, password_record["salt"], password_record["digest"], self._now()),
                )
            else:
                user_id = row["id"]
                connection.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))
            return self._user_row(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def reset_admin(self, email: str, password: str) -> dict[str, str]:
        """Replace development admin identities and invalidate their credentials."""
        email = self._normalize_email(email)
        self._validate_password(password)
        password_record = self._password_record(password)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM users WHERE role = 'admin'")
            user_id = f"usr_{secrets.token_hex(8)}"
            connection.execute(
                "INSERT INTO users (id, email, role, password_salt, password_digest, created_at) "
                "VALUES (?, ?, 'admin', ?, ?, ?)",
                (user_id, email, password_record["salt"], password_record["digest"], self._now()),
            )
            return self._user_row(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def login(self, email: str, password: str) -> dict[str, Any]:
        email = self._normalize_email(email)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None or not self._verify_password(
                password, {"salt": row["password_salt"], "digest": row["password_digest"]}
            ):
                raise ValueError("邮箱或密码不正确。")
            session, token = self._issue(connection, row["id"])
            return {"user": self._user_row(row), "session": session, "token": token}

    def set_password(self, email: str, password: str) -> dict[str, str]:
        """Change one account password and revoke its existing credentials."""
        email = self._normalize_email(email)
        self._validate_password(password)
        password_record = self._password_record(password)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None:
                raise ValueError("账号不存在。")
            connection.execute(
                "UPDATE users SET password_salt = ?, password_digest = ? WHERE id = ?",
                (password_record["salt"], password_record["digest"], row["id"]),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            connection.execute("DELETE FROM api_tokens WHERE user_id = ?", (row["id"],))
            return self._user_row(row)

    def set_role(self, email: str, role: str) -> dict[str, str]:
        """Assign an account role without interrupting its current login."""
        email = self._normalize_email(email)
        if role not in {"member", "admin"}:
            raise ValueError("不支持的账户角色。")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None:
                raise ValueError("账号不存在。")
            connection.execute("UPDATE users SET role = ? WHERE id = ?", (role, row["id"]))
            updated = connection.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            return self._user_row(updated)

    def current_user(self, *, session: str | None = None, token: str | None = None) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = self._authenticated_user(connection, session=session, token=token)
            return self._user_row(row) if row is not None else None

    def rotate_token(self, *, session: str | None = None, token: str | None = None) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._authenticated_user(connection, session=session, token=token)
            if row is None:
                raise ValueError("登录状态已失效，请重新登录。")
            if token:
                connection.execute("DELETE FROM api_tokens WHERE token_digest = ?", (self._digest(token),))
            new_token = f"pm_live_{secrets.token_urlsafe(40)}"
            now = self._now()
            expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
            connection.execute(
                "INSERT INTO api_tokens (token_digest, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (self._digest(new_token), row["id"], now, expires),
            )
            return {"token": new_token, "user": self._user_row(row)}

    def list_users(self, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            pages = max(1, (total + page_size - 1) // page_size)
            page = max(1, min(page, pages))
            rows = connection.execute(
                "SELECT id, email, role, created_at FROM users "
                "ORDER BY datetime(created_at) DESC, email ASC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            return {
                "users": [dict(row) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
            }

    def users_by_id(self) -> dict[str, dict[str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT id, email, role, created_at FROM users").fetchall()
            return {row["id"]: dict(row) for row in rows}

    def _issue(self, connection: sqlite3.Connection, user_id: str) -> tuple[str, str]:
        session = f"sess_{secrets.token_urlsafe(32)}"
        token = f"pm_live_{secrets.token_urlsafe(40)}"
        now = self._now()
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        connection.execute(
            "INSERT INTO sessions (session_digest, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (self._digest(session), user_id, now, expires),
        )
        connection.execute(
            "INSERT INTO api_tokens (token_digest, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (self._digest(token), user_id, now, expires),
        )
        return session, token

    def _authenticated_user(
        self, connection: sqlite3.Connection, *, session: str | None, token: str | None
    ) -> sqlite3.Row | None:
        now = self._now()
        if session:
            row = connection.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.session_digest = ? AND sessions.expires_at > ?",
                (self._digest(session), now),
            ).fetchone()
            if row is not None:
                return row
        if token:
            return connection.execute(
                "SELECT users.* FROM api_tokens JOIN users ON users.id = api_tokens.user_id "
                "WHERE api_tokens.token_digest = ? AND api_tokens.expires_at > ?",
                (self._digest(token), now),
            ).fetchone()
        return None

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'admin')),
                    password_salt TEXT NOT NULL,
                    password_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_digest TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_tokens (
                    token_digest TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS api_tokens_user_id_idx ON api_tokens(user_id);
                """
            )
            migrated = connection.execute(
                "SELECT 1 FROM auth_meta WHERE key = 'legacy_json_migrated_v1'"
            ).fetchone()
            if migrated is None:
                self._migrate_legacy_json(connection)
                connection.execute(
                    "INSERT INTO auth_meta (key, value) VALUES ('legacy_json_migrated_v1', ?)",
                    (self._now(),),
                )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _migrate_legacy_json(self, connection: sqlite3.Connection) -> None:
        try:
            data = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        users = data.get("users", {}) if isinstance(data, dict) else {}
        for email, user in users.items():
            if not isinstance(user, dict):
                continue
            password = user.get("password") or {}
            if not all(isinstance(password.get(key), str) for key in ("salt", "digest")):
                continue
            normalized = self._normalize_email(user.get("email") or email)
            connection.execute(
                "INSERT OR IGNORE INTO users "
                "(id, email, role, password_salt, password_digest, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user.get("id") or f"usr_{secrets.token_hex(8)}",
                    normalized,
                    "admin" if user.get("role") == "admin" else "member",
                    password["salt"],
                    password["digest"],
                    user.get("created_at") or self._now(),
                ),
            )
        users_by_email = {
            row["email"]: row["id"]
            for row in connection.execute("SELECT id, email FROM users").fetchall()
        }
        for session, record in (data.get("sessions", {}) or {}).items():
            if not isinstance(record, dict):
                continue
            user_id = users_by_email.get(str(record.get("email", "")).lower()) or record.get("user_id")
            if not user_id or not connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                continue
            connection.execute(
                "INSERT OR IGNORE INTO sessions (session_digest, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (self._digest(session), user_id, record.get("created_at") or self._now(), record.get("expires_at") or self._now()),
            )
        for token_digest, record in (data.get("tokens", {}) or {}).items():
            if not isinstance(record, dict):
                continue
            user_id = users_by_email.get(str(record.get("email", "")).lower()) or record.get("user_id")
            if not user_id or not connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                continue
            connection.execute(
                "INSERT OR IGNORE INTO api_tokens (token_digest, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_digest, user_id, record.get("created_at") or self._now(), record.get("expires_at") or self._now()),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _password_record(password: str) -> dict[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
        return {"salt": salt.hex(), "digest": digest.hex()}

    @staticmethod
    def _verify_password(password: str, record: dict[str, str]) -> bool:
        try:
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(record["salt"]), 240_000
            )
            return secrets.compare_digest(digest.hex(), record["digest"])
        except (KeyError, ValueError):
            return False

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise ValueError("密码至少需要 8 位。")

    @staticmethod
    def _normalize_email(email: str) -> str:
        value = email.strip().lower()
        if "@" not in value or len(value) > 254:
            raise ValueError("请输入有效邮箱。")
        return value

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _user_row(row: sqlite3.Row) -> dict[str, str]:
        return {
            "id": row["id"],
            "email": row["email"],
            "role": row["role"],
            "created_at": row["created_at"],
        }
