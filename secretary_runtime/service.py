"""渠道无关的项目秘书和 RealityPatch 状态机。"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SecretaryService:
    def __init__(self, data_dir: str | Path | None = None):
        root = Path(data_dir or os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "secretary.sqlite3"
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sync_sessions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, status TEXT NOT NULL, draft_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS patches (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, operation TEXT NOT NULL, proposed_change TEXT NOT NULL, evidence TEXT NOT NULL, risk TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL, confirmed_by TEXT NOT NULL DEFAULT '', rollback_data TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action TEXT NOT NULL, target_id TEXT NOT NULL, actor TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL);
            """
        )
        conn.commit()
        conn.close()

    def ensure_project(self, project_id: str = "default", name: str = "现实补丁项目") -> dict[str, Any]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                conn.execute("INSERT INTO projects VALUES (?, ?, ?)", (project_id, name, _now()))
                conn.commit()
                row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return dict(row)
        finally:
            conn.close()

    def create_task(self, project_id: str, title: str, owner: str = "", due_at: str = "") -> dict[str, Any]:
        self.ensure_project(project_id)
        task_id = "T-" + uuid.uuid4().hex[:8].upper()
        now = _now()
        conn = self._conn()
        try:
            conn.execute("INSERT INTO tasks VALUES (?, ?, ?, 'todo', ?, ?, ?, ?)", (task_id, project_id, title.strip(), owner.strip(), due_at.strip(), now, now))
            self._audit(conn, project_id, "task_created", task_id, owner or "agent", {"title": title})
            conn.commit()
            return dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        finally:
            conn.close()

    def draft_sync(self, project_id: str, text: str, actor: str = "agent") -> dict[str, Any]:
        self.ensure_project(project_id)
        tasks = []
        for line in re.split(r"[\n；;]", text):
            line = line.strip(" -•\t")
            if not line:
                continue
            tasks.append({"title": line[:160], "owner": "", "status": "todo"})
        session_id = "S-" + uuid.uuid4().hex[:8].upper()
        draft = {"summary": text[:500], "tasks": tasks, "decisions": [], "risks": []}
        now = _now()
        conn = self._conn()
        try:
            conn.execute("INSERT INTO sync_sessions VALUES (?, ?, 'ready', ?, ?, ?)", (session_id, project_id, json.dumps(draft, ensure_ascii=False), now, now))
            self._audit(conn, project_id, "sync_drafted", session_id, actor, draft)
            conn.commit()
            return {"session_id": session_id, "status": "ready", "draft": draft}
        finally:
            conn.close()

    def confirm_sync(self, session_id: str, actor: str) -> dict[str, Any]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM sync_sessions WHERE id=?", (session_id,)).fetchone()
            if not row or row["status"] == "confirmed":
                raise ValueError("sync session is missing or already confirmed")
            draft = json.loads(row["draft_json"])
            created: list[dict[str, Any]] = []
            for task in draft.get("tasks", []):
                task_id = "T-" + uuid.uuid4().hex[:8].upper()
                now = _now()
                conn.execute("INSERT INTO tasks VALUES (?, ?, ?, 'todo', ?, ?, ?, ?)", (task_id, row["project_id"], task.get("title", "未命名任务"), task.get("owner", ""), task.get("due_at", ""), now, now))
                created.append({"id": task_id, "title": task.get("title", "未命名任务")})
            now = _now()
            conn.execute("UPDATE sync_sessions SET status='confirmed', updated_at=? WHERE id=?", (now, session_id))
            self._audit(conn, row["project_id"], "sync_confirmed", session_id, actor, {"tasks": created})
            conn.commit()
            return {"session_id": session_id, "status": "confirmed", "tasks": created}
        finally:
            conn.close()

    def create_patch(self, project_id: str, target_type: str, target_id: str, operation: str, proposed_change: str, *, evidence: str = "", risk: str = "medium", created_by: str = "agent") -> dict[str, Any]:
        self.ensure_project(project_id)
        patch_id = "P-" + uuid.uuid4().hex[:8].upper()
        now = _now()
        conn = self._conn()
        try:
            conn.execute("INSERT INTO patches VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, '', '', ?, ?)", (patch_id, project_id, target_type, target_id, operation, proposed_change, evidence, risk, created_by, now, now))
            self._audit(conn, project_id, "patch_drafted", patch_id, created_by, {"target_type": target_type, "operation": operation})
            conn.commit()
            return dict(conn.execute("SELECT * FROM patches WHERE id=?", (patch_id,)).fetchone())
        finally:
            conn.close()

    def confirm_patch(self, patch_id: str, actor: str) -> dict[str, Any]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM patches WHERE id=?", (patch_id,)).fetchone()
            if not row or row["status"] != "draft":
                raise ValueError("patch is missing or not confirmable")
            now = _now()
            target_type = row["target_type"]
            target_id = row["target_id"]
            operation = row["operation"]
            proposed_change = row["proposed_change"]
            project_id = row["project_id"]
            rollback_info: dict[str, Any] = {"previous_status": "draft", "target_type": target_type, "operation": operation}

            # 执行实体补丁逻辑
            if target_type == "task":
                if operation == "create":
                    created_task_id = "T-" + uuid.uuid4().hex[:8].upper()
                    conn.execute(
                        "INSERT INTO tasks VALUES (?, ?, ?, 'todo', ?, '', ?, ?)",
                        (created_task_id, project_id, proposed_change, actor, now, now),
                    )
                    rollback_info["created_task_id"] = created_task_id
                    self._audit(conn, project_id, "task_created_by_patch", created_task_id, actor, {"patch_id": patch_id, "title": proposed_change})
                elif operation == "update":
                    existing_task = conn.execute("SELECT * FROM tasks WHERE id=?", (target_id,)).fetchone()
                    if existing_task:
                        rollback_info["previous_task"] = dict(existing_task)
                        # 如果 proposed_change 是状态或者标题
                        if proposed_change in ("todo", "in_progress", "blocked", "done"):
                            conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (proposed_change, now, target_id))
                        else:
                            conn.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=?", (proposed_change, now, target_id))
                        self._audit(conn, project_id, "task_updated_by_patch", target_id, actor, {"patch_id": patch_id, "change": proposed_change})
                elif operation == "delete":
                    existing_task = conn.execute("SELECT * FROM tasks WHERE id=?", (target_id,)).fetchone()
                    if existing_task:
                        rollback_info["deleted_task"] = dict(existing_task)
                        conn.execute("DELETE FROM tasks WHERE id=?", (target_id,))
                        self._audit(conn, project_id, "task_deleted_by_patch", target_id, actor, {"patch_id": patch_id})

            rollback_data = json.dumps(rollback_info, ensure_ascii=False)
            conn.execute("UPDATE patches SET status='applied', confirmed_by=?, rollback_data=?, updated_at=? WHERE id=?", (actor, rollback_data, now, patch_id))
            self._audit(conn, row["project_id"], "patch_applied", patch_id, actor, {"operation": row["operation"], "rollback_info": rollback_info})
            conn.commit()
            return dict(conn.execute("SELECT * FROM patches WHERE id=?", (patch_id,)).fetchone())
        finally:
            conn.close()

    def rollback_patch(self, patch_id: str, actor: str) -> dict[str, Any]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM patches WHERE id=?", (patch_id,)).fetchone()
            if not row or row["status"] != "applied":
                raise ValueError("patch is not applied")
            now = _now()
            rollback_info = {}
            if row["rollback_data"]:
                try:
                    rollback_info = json.loads(row["rollback_data"])
                except Exception:
                    rollback_info = {}

            target_type = rollback_info.get("target_type") or row["target_type"]
            operation = rollback_info.get("operation") or row["operation"]

            if target_type == "task":
                if operation == "create" and rollback_info.get("created_task_id"):
                    conn.execute("DELETE FROM tasks WHERE id=?", (rollback_info["created_task_id"],))
                    self._audit(conn, row["project_id"], "task_rolled_back", rollback_info["created_task_id"], actor, {"patch_id": patch_id})
                elif operation == "update" and rollback_info.get("previous_task"):
                    prev = rollback_info["previous_task"]
                    conn.execute(
                        "UPDATE tasks SET title=?, status=?, owner=?, due_at=?, updated_at=? WHERE id=?",
                        (prev["title"], prev["status"], prev["owner"], prev["due_at"], now, prev["id"]),
                    )
                    self._audit(conn, row["project_id"], "task_rolled_back", prev["id"], actor, {"patch_id": patch_id})
                elif operation == "delete" and rollback_info.get("deleted_task"):
                    prev = rollback_info["deleted_task"]
                    conn.execute(
                        "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (prev["id"], prev["project_id"], prev["title"], prev["status"], prev["owner"], prev["due_at"], prev["created_at"], now),
                    )
                    self._audit(conn, row["project_id"], "task_rolled_back", prev["id"], actor, {"patch_id": patch_id})

            conn.execute("UPDATE patches SET status='rolled_back', updated_at=? WHERE id=?", (now, patch_id))
            self._audit(conn, row["project_id"], "patch_rolled_back", patch_id, actor, {})
            conn.commit()
            return dict(conn.execute("SELECT * FROM patches WHERE id=?", (patch_id,)).fetchone())
        finally:
            conn.close()

    def dashboard(self, project_id: str = "default") -> dict[str, Any]:
        conn = self._conn()
        try:
            tasks = [dict(row) for row in conn.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY updated_at DESC", (project_id,))]
            patches = [dict(row) for row in conn.execute("SELECT * FROM patches WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,))]
            audits = [dict(row) for row in conn.execute("SELECT * FROM audit_events WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,))]
            return {
                "project_id": project_id,
                "counts": {status: sum(1 for task in tasks if task["status"] == status) for status in ("todo", "in_progress", "blocked", "done")},
                "tasks": tasks,
                "patches": patches,
                "audits": audits,
            }
        finally:
            conn.close()

    @staticmethod
    def _audit(conn: sqlite3.Connection, project_id: str, action: str, target_id: str, actor: str, detail: dict[str, Any]) -> None:
        conn.execute("INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)", ("A-" + uuid.uuid4().hex[:10].upper(), project_id, action, target_id, actor, json.dumps(detail, ensure_ascii=False), _now()))
