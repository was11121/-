"""冷启动 / Demo Workspace 支持。

策略：单独维护一张 `demo_seed` 表，只记录"哪些行是 demo"。
- seed_demo() 给指定用户注入：3 条记忆 + 1 份文档 + 1 张看板（3 任务）；
- clear_demo() 按 seed 反查清空已注入的 demo；
- is_demo_seeded() 用于前端决定是否展示"开始体验"按钮。

对原有 ORM / secretary 表结构 0 侵入。
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


DEMO_DOCUMENT = """# Remedy 使用速览

> 你正在阅读的这份文档就是 Remedy 为你准备的第一份示例资料。

## 它能做什么

- **记住你说的话**：偏好、需求、身份都会进入长期记忆
- **督促你执行**：基于大五人格自动生成可开始的任务脚手架
- **联网检索**：在对话里粘贴链接或输入 `!search 关键词` 即可

## 试试看

回到对话页，随便说一句"我喜欢喝什么"或"今天务必做什么"。
你会看到：

1. 对话区出现 AI 回复
2. 总览页"今天先做这件事"卡出现 1 条建议
3. 秘书看板出现可确认的"补丁"
"""


class OnboardingService:
    """demo 数据播种与清理。

    复用现有运行时：
    - 个人数据通过 storage.models 集中库写入；
    - 知识库通过 library_runtime.ingest_document 写入；
    - 看板任务通过 secretary_runtime.SecretaryService.create_task 写入；
    - demo_seed 表仅记录"哪些行是 demo"，清理时反向定位。
    """

    def __init__(self, data_dir: str | Path | None = None):
        from storage.db import get_engine
        from storage.models import Base
        root = Path(data_dir or os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        root.mkdir(parents=True, exist_ok=True)
        self.data_dir = root
        # 触发中央库的 Base metadata，建表
        engine = get_engine(root)
        Base.metadata.create_all(engine)
        # 单独维护 demo_seed 表（与 secretary 同库 / 不同表均可，这里选 secretary 库保持集中）
        self._demo_db_path = root / "secretary.sqlite3"
        self._init_seed_table()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._demo_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_seed_table(self) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_seed (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_demo_seed_user ON demo_seed(user_id)")
            conn.commit()
        finally:
            conn.close()

    def is_demo_seeded(self, user_id: str) -> bool:
        """是否已经为该用户注入过 demo。"""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM demo_seed WHERE user_id = ?", (user_id,)
            ).fetchone()
            return bool(row and row["n"] > 0)
        finally:
            conn.close()

    def seed_demo(self, user_id: str, *, agent=None) -> dict[str, Any]:
        """注入 demo 数据。需要传入已初始化的 UnifiedAgent。

        Returns: { memories: 3, document: 1, tasks: 3, patches: 1 }
        """
        if agent is None:
            raise ValueError("agent is required for demo seeding")

        result = {"memories": 0, "document": 0, "tasks": 0, "patches": 0}

        # 1. 3 条记忆（preference / need / identity）+ interaction 一次性写入
        demo_messages = [
            ("我喜欢喝拿铁咖啡，尤其是早上 9 点那杯。", "chat"),
            ("我准备这周内把项目文档整理完。", "chat"),
            ("你可以叫我小椰，这是我的花名。", "chat"),
        ]
        for text, source in demo_messages:
            try:
                rec = agent.memory.record_interaction(user_id, text, "（示例对话 —— 你的 AI 助手会基于此类消息推断画像）", source=source)
                stored = (rec or {}).get("stored") or []
                for m in stored:
                    if m.get("id"):
                        self._record_seed(user_id, "memory", m["id"])
                        result["memories"] += 1
            except Exception:
                continue

        # 2. 1 份示例文档
        try:
            doc = agent.library.ingest_document(
                "Remedy 使用速览.md",
                DEMO_DOCUMENT,
                source="demo",
                tags=["demo", f"user:{user_id}"],
            )
            doc_id = (doc or {}).get("document", {}).get("document_id") or (doc or {}).get("id")
            if doc_id:
                self._record_seed(user_id, "document", doc_id)
                result["document"] = 1
        except Exception:
            pass

        # 3. 看板：3 个任务（待办 / 进行中 / 完成）和 1 个补丁草稿
        try:
            owner = user_id
            task_specs = [
                ("研究 Remedy 的核心场景", "todo"),
                ("配置 MODEL_API_KEY 让 AI 真正接入", "in_progress"),
                ("上传第一份真实文档到知识库", "done"),
            ]
            for title, status in task_specs:
                task = agent.secretary.create_task("default", title, owner=owner)
                if status != "todo":
                    # 通过补丁更新状态
                    patch = agent.secretary.create_patch(
                        "default", "task", task["id"], "update", status, evidence="demo 自动注入",
                        risk="low", created_by="demo_seed",
                    )
                    self._record_seed(user_id, "task", task["id"])
                    self._record_seed(user_id, "patch", patch["id"])
                    result["tasks"] += 1
                    if status == "done":
                        agent.secretary.confirm_patch(patch["id"], owner)
                    else:
                        # 保留 draft 让用户体验确认流程
                        result["patches"] += 1
                else:
                    self._record_seed(user_id, "task", task["id"])
                    result["tasks"] += 1
        except Exception:
            pass

        return result

    def clear_demo(self, user_id: str, *, agent=None, auth_service=None) -> dict[str, int]:
        """清空 demo 数据。需要传入 agent 与 auth_service 以反向定位引用。"""
        if agent is None or auth_service is None:
            raise ValueError("agent and auth_service are required for clearing demo")

        counts = {"memories": 0, "interactions": 0, "tasks": 0, "patches": 0, "documents": 0}
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT kind, ref_id FROM demo_seed WHERE user_id = ?", (user_id,)
            ).fetchall()
        finally:
            conn.close()

        rows_by_kind: dict[str, list[str]] = {}
        for row in rows:
            rows_by_kind.setdefault(row["kind"], []).append(row["ref_id"])

        from storage.db import get_session
        from storage.models import InteractionRow, MemoryRow

        # memory: 物理删除 demo 标记的记忆
        memory_ids = rows_by_kind.get("memory", [])
        if memory_ids:
            try:
                with get_session(self.data_dir) as session:
                    counts["memories"] = session.query(MemoryRow).filter(MemoryRow.id.in_(memory_ids)).delete(synchronize_session=False)
                    # 同步清理 demo 注入的 interaction（用 source='demo'）
                    counts["interactions"] = session.query(InteractionRow).filter(InteractionRow.user_id == user_id, InteractionRow.source == "demo").delete(synchronize_session=False)
                    session.commit()
            except Exception:
                pass

        # document：library 删除（按 id）
        for doc_id in rows_by_kind.get("document", []):
            try:
                agent.library.delete_document(doc_id)
                counts["documents"] += 1
            except Exception:
                pass

        # tasks / patches: 直接通过 secretary 操作（按 id）
        for task_id in rows_by_kind.get("task", []):
            try:
                agent.secretary.delete_task(task_id, project_id="default")
                counts["tasks"] += 1
            except Exception:
                pass
        for patch_id in rows_by_kind.get("patch", []):
            try:
                agent.secretary.delete_patch(patch_id, project_id="default")
                counts["patches"] += 1
            except Exception:
                pass

        # 清空 seed 记录
        conn = self._conn()
        try:
            conn.execute("DELETE FROM demo_seed WHERE user_id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()

        return counts

    def _record_seed(self, user_id: str, kind: str, ref_id: str, payload: dict[str, Any] | None = None) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO demo_seed VALUES (?, ?, ?, ?, ?, ?)",
                ("S-" + uuid.uuid4().hex[:10].upper(), user_id, kind, ref_id, json.dumps(payload or {}, ensure_ascii=False), _now()),
            )
            conn.commit()
        finally:
            conn.close()
