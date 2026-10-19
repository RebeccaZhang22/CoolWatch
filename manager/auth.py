"""Independent manager identities. Never accepts customer sessions or API tokens."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from manager.config import get_config
COOKIE = "pm_manager_session"


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or len(value) > 254:
        raise ValueError("请输入有效邮箱。")
    return value


def password_record(password: str) -> dict[str, str]:
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return {"salt": salt.hex(), "digest": hashed.hex()}


def verify_password(password: str, record: dict) -> bool:
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(record["salt"]), 240_000)
    return secrets.compare_digest(hashed.hex(), record["digest"])


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ManagerAuthStore:
    def __init__(self, path: Path | None = None):
        self.path = path or get_config().data_dir / "manager.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS managers (
                    email TEXT PRIMARY KEY, salt TEXT NOT NULL, digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manager_sessions (
                    digest TEXT PRIMARY KEY, email TEXT NOT NULL, expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    identity TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at TEXT NOT NULL
                );
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def provision(self, email: str, password: str):
        email = normalize_email(email)
        if len(password) < 8:
            raise ValueError("管理者密码至少需要 8 位。")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM managers WHERE email = ?", (email,)).fetchone()
            if row and verify_password(password, dict(row)):
                return
            record = password_record(password)
            db.execute("INSERT OR REPLACE INTO managers VALUES (?, ?, ?)",
                       (email, record["salt"], record["digest"]))
            db.execute("DELETE FROM manager_sessions WHERE email = ?", (email,))

    def login(self, email: str, password: str, client: str):
        email = email.strip().lower()
        now = datetime.now(UTC)
        # Rate-limit source and identity separately, including across workers/restarts.
        identities = ["ip:" + client, "email:" + email]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_attempts WHERE reset_at <= ?", (now.isoformat(),))
            db.execute("DELETE FROM manager_sessions WHERE expires_at <= ?", (now.isoformat(),))
            for identity in identities:
                attempt = db.execute("SELECT attempts FROM login_attempts WHERE identity = ?", (identity,)).fetchone()
                if attempt and attempt["attempts"] >= 10:
                    raise PermissionError("尝试过于频繁，请在 15 分钟后重试。")
            row = db.execute("SELECT * FROM managers WHERE email = ?", (email,)).fetchone()
            record = dict(row) if row else {"salt": "00" * 16, "digest": "00" * 32}
            valid = verify_password(password, record) and row is not None
            if not valid:
                for identity in identities:
                    db.execute("INSERT INTO login_attempts VALUES (?, 1, ?) ON CONFLICT(identity) "
                               "DO UPDATE SET attempts = attempts + 1",
                               (identity, (now + timedelta(minutes=15)).isoformat()))
            else:
                db.execute("DELETE FROM login_attempts WHERE identity = ?", ("email:" + email,))
                session = secrets.token_urlsafe(48)
                db.execute("INSERT INTO manager_sessions VALUES (?, ?, ?)",
                           (digest(session), email, (now + timedelta(hours=8)).isoformat()))
        if not valid:
            raise ValueError("管理者账号或密码不正确。")
        return {"email": email}, session

    def current(self, session: str | None):
        if not session:
            return None
        with self.connect() as db:
            row = db.execute("SELECT email FROM manager_sessions WHERE digest = ? AND expires_at > ?",
                             (digest(session), datetime.now(UTC).isoformat())).fetchone()
            return dict(row) if row else None

    def logout(self, session: str | None):
        with self.connect() as db:
            db.execute("DELETE FROM manager_sessions WHERE digest = ?", (digest(session or ""),))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="创建或更新独立管理者账号，更新密码会撤销旧会话。")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("管理者密码（至少 8 位）: ")
    if password != getpass.getpass("再次输入密码: "):
        parser.error("两次密码不一致")
    ManagerAuthStore().provision(args.email, password)
    print("管理者账号已保存，请访问 /manager/login.html")
