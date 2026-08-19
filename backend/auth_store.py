"""Local account, browser-session and CLI-token store for the demo platform."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any


class AuthStore:
    def __init__(self) -> None:
        self.path = Path(__file__).resolve().parents[1] / ".runtime" / "prospectmonitor_auth.json"
        self._lock = RLock()

    def register(self, email: str, password: str) -> dict[str, Any]:
        email = self._normalize_email(email)
        self._validate_password(password)
        with self._lock:
            data = self._read()
            if email in data["users"]:
                raise ValueError("该邮箱已经注册，请直接登录。")
            user_id = f"usr_{secrets.token_hex(8)}"
            data["users"][email] = {
                "id": user_id,
                "email": email,
                "role": "member",
                "password": self._password_record(password),
                "created_at": self._now(),
            }
            session, token = self._issue(data, user_id, email)
            self._write(data)
            return {"user": self._user(data["users"][email]), "session": session, "token": token}

    def ensure_admin(self, email: str, password: str) -> dict[str, str]:
        email = self._normalize_email(email)
        self._validate_password(password)
        with self._lock:
            data = self._read()
            user = data["users"].get(email)
            if user is None:
                user = {
                    "id": f"usr_{secrets.token_hex(8)}",
                    "email": email,
                    "role": "admin",
                    "password": self._password_record(password),
                    "created_at": self._now(),
                }
                data["users"][email] = user
            else:
                user["role"] = "admin"
            self._write(data)
            return self._user(user)

    def reset_admin(self, email: str, password: str) -> dict[str, str]:
        """Replace the development admin identity and invalidate its sessions."""
        email = self._normalize_email(email)
        self._validate_password(password)
        with self._lock:
            data = self._read()
            old_admin_emails = {
                address for address, user in data["users"].items()
                if user.get("role") == "admin"
            }
            for address in old_admin_emails:
                data["users"].pop(address, None)
            for collection in (data["sessions"], data["tokens"]):
                for key in list(collection):
                    if collection[key].get("email") in old_admin_emails:
                        collection.pop(key, None)
            user = {
                "id": f"usr_{secrets.token_hex(8)}",
                "email": email,
                "role": "admin",
                "password": self._password_record(password),
                "created_at": self._now(),
            }
            data["users"][email] = user
            self._write(data)
            return self._user(user)

    def login(self, email: str, password: str) -> dict[str, Any]:
        email = self._normalize_email(email)
        with self._lock:
            data = self._read()
            user = data["users"].get(email)
            if not user or not self._verify_password(password, user["password"]):
                raise ValueError("邮箱或密码不正确。")
            session, token = self._issue(data, user["id"], email)
            self._write(data)
            return {"user": self._user(user), "session": session, "token": token}

    def current_user(self, *, session: str | None = None, token: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            email = None
            if session:
                record = data["sessions"].get(session)
                if record and self._not_expired(record):
                    email = record.get("email")
            if not email and token:
                digest = self._digest(token)
                record = data["tokens"].get(digest)
                if record and self._not_expired(record):
                    email = record.get("email")
            return self._user(data["users"][email]) if email in data["users"] else None

    def rotate_token(self, *, session: str | None = None, token: str | None = None) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            user = self.current_user(session=session, token=token)
            if not user:
                raise ValueError("登录状态已失效，请重新登录。")
            if token:
                data["tokens"].pop(self._digest(token), None)
            _, new_token = self._issue(data, user["id"], user["email"])
            self._write(data)
            return {"token": new_token, "user": user}

    def _issue(self, data: dict[str, Any], user_id: str, email: str) -> tuple[str, str]:
        session = f"sess_{secrets.token_urlsafe(32)}"
        token = f"pm_live_{secrets.token_urlsafe(40)}"
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        data["sessions"][session] = {"user_id": user_id, "email": email, "expires_at": expires}
        data["tokens"][self._digest(token)] = {
            "user_id": user_id,
            "email": email,
            "created_at": self._now(),
            "expires_at": expires,
        }
        return session, token

    @staticmethod
    def _password_record(password: str) -> dict[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
        return {"salt": salt.hex(), "digest": digest.hex()}

    @staticmethod
    def _verify_password(password: str, record: dict[str, str]) -> bool:
        try:
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(record["salt"]), 240_000)
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
    def _not_expired(record: dict[str, Any]) -> bool:
        try:
            return datetime.fromisoformat(record["expires_at"]) > datetime.now(UTC)
        except (KeyError, ValueError):
            return False

    @staticmethod
    def _user(user: dict[str, Any]) -> dict[str, str]:
        return {
            "id": user["id"],
            "email": user["email"],
            "role": user.get("role", "member"),
            "created_at": user["created_at"],
        }

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("users", {})
            data.setdefault("sessions", {})
            data.setdefault("tokens", {})
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"users": {}, "sessions": {}, "tokens": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="auth-", suffix=".tmp", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_name, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
