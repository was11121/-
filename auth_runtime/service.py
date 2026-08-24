"""用户认证、令牌管理与角色权限服务。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = uuid.uuid4().hex
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    ).hex()
    return pwd_hash, salt


class AuthService:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.getenv("MYAGENT_DATA_DIR", "./data")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "auth.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    nickname TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tokens (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );
                """
            )
            # 仅保留 Remedy 管理员，移除测试账号 alice/bob
            remedy_pwd = os.getenv("REMEDY_ADMIN_PASSWORD", "Remedy@2025")
            self._ensure_default_user(conn, "remedy_admin", remedy_pwd, role="admin", nickname="Remedy Admin")
            # 清理遗留测试账号（幂等）
            for legacy in ("alice", "bob"):
                row = conn.execute("SELECT id FROM users WHERE username = ?", (legacy,)).fetchone()
                if row:
                    uid = row["id"]
                    conn.execute("DELETE FROM tokens WHERE user_id = ?", (uid,))
                    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
            conn.commit()
        finally:
            conn.close()

    def _ensure_default_user(self, conn: sqlite3.Connection, username: str, password: str, role: str, nickname: str) -> None:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            uid = f"u_{username}"
            pwd_hash, salt = _hash_password(password)
            now = _utc_now()
            conn.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, username, pwd_hash, salt, role, nickname, now, now),
            )

    def register(self, username: str, password: str, role: str = "user", nickname: str | None = None) -> dict[str, Any]:
        username = username.strip().lower()
        if not username or len(username) < 3:
            raise ValueError("用户名至少需要3个字符")
        if not password or len(password) < 6:
            raise ValueError("密码至少需要6位")
        # 开放注册仅允许 user，禁止前端伪造 admin
        role = "user"

        conn = self._connect()
        try:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                raise ValueError(f"用户名 '{username}' 已被注册")

            uid = f"u_{username}" if not username.startswith("u_") else username
            pwd_hash, salt = _hash_password(password)
            now = _utc_now()
            display_name = nickname.strip() if nickname and nickname.strip() else username

            conn.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, username, pwd_hash, salt, role, display_name, now, now),
            )
            conn.commit()
            return {
                "id": uid,
                "username": username,
                "role": role,
                "nickname": display_name,
                "created_at": now,
            }
        finally:
            conn.close()

    def login(self, username: str, password: str, expires_hours: int = 72) -> dict[str, Any]:
        username = username.strip().lower()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if not row:
                raise ValueError("用户名或密码错误")

            pwd_hash, _ = _hash_password(password, salt=row["salt"])
            if pwd_hash != row["password_hash"]:
                raise ValueError("用户名或密码错误")

            # 签发令牌
            token = "tok_" + uuid.uuid4().hex
            now_dt = datetime.now(timezone.utc)
            expires_dt = now_dt + timedelta(hours=expires_hours)
            now_str = now_dt.isoformat(timespec="seconds")
            expires_str = expires_dt.isoformat(timespec="seconds")

            conn.execute(
                "INSERT INTO tokens VALUES (?, ?, ?, ?)",
                (token, row["id"], expires_str, now_str),
            )
            conn.commit()

            return {
                "token": token,
                "expires_at": expires_str,
                "user": {
                    "id": row["id"],
                    "username": row["username"],
                    "role": row["role"],
                    "nickname": row["nickname"],
                    "created_at": row["created_at"],
                },
            }
        finally:
            conn.close()

    def verify_token(self, token: str) -> dict[str, Any] | None:
        if not token or not token.strip():
            return None
        token = token.strip()
        conn = self._connect()
        try:
            now_str = _utc_now()
            row = conn.execute(
                """
                SELECT u.id, u.username, u.role, u.nickname, u.created_at, t.expires_at
                FROM tokens t
                JOIN users u ON t.user_id = u.id
                WHERE t.token = ? AND t.expires_at > ?
                """,
                (token, now_str),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "nickname": row["nickname"],
                "created_at": row["created_at"],
            }
        finally:
            conn.close()

    def logout(self, token: str) -> bool:
        if not token:
            return False
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM tokens WHERE token = ?", (token.strip(),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT id, username, role, nickname, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_all_users(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id, username, role, nickname, created_at FROM users ORDER BY created_at ASC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
