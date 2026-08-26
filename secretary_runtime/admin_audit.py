"""管理员操作审计日志：记录跨用户行为（搜索聊天、删除、标注、查看画像等）。

与 SecretaryService 的 audit_events（项目级）解耦，专门追踪"管理员对普通用户
执行的穿透操作"，便于合规与溯源。
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AdminAuditService:
    def __init__(self, data_dir: str | Path | None = None):
        root = Path(data_dir or os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "admin_audit.sqlite3"
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_user TEXT NOT NULL,
                    target_id TEXT NOT NULL DEFAULT '',
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    ip TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_admin_audit_actor ON admin_audit_events(actor);
                CREATE INDEX IF NOT EXISTS ix_admin_audit_target ON admin_audit_events(target_user);
                CREATE INDEX IF NOT EXISTS ix_admin_audit_created ON admin_audit_events(created_at);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def record(self, actor: str, action: str, target_user: str, *, target_id: str = "", detail: dict[str, Any] | None = None, ip: str = "") -> str:
        """写入一条审计记录，返回事件 id。"""
        event_id = "AA-" + uuid.uuid4().hex[:10].upper()
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO admin_audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, actor, action, target_user, target_id, json.dumps(detail or {}, ensure_ascii=False), ip, _now()),
            )
            conn.commit()
        finally:
            conn.close()
        return event_id

    def list_events(self, *, limit: int = 100, offset: int = 0, actor: str = "", action: str = "", target_user: str = "") -> dict[str, Any]:
        """按条件分页查询审计事件。"""
        where: list[str] = []
        params: list[Any] = []
        if actor:
            where.append("actor = ?")
            params.append(actor)
        if action:
            where.append("action = ?")
            params.append(action)
        if target_user:
            where.append("target_user = ?")
            params.append(target_user)
        where_clause = (" WHERE " + " AND ".join(where)) if where else ""
        conn = self._conn()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM admin_audit_events{where_clause}",
                params,
            ).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM admin_audit_events{where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                try:
                    detail = json.loads(row["detail_json"] or "{}")
                except Exception:
                    detail = {}
                items.append({
                    "id": row["id"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "target_user": row["target_user"],
                    "target_id": row["target_id"],
                    "detail": detail,
                    "ip": row["ip"],
                    "created_at": row["created_at"],
                })
            return {"total": total, "limit": limit, "offset": offset, "items": items}
        finally:
            conn.close()
