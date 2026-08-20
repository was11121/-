"""本地隔离的长期反馈记忆服务。

每个用户使用独立 SQLite 文件，避免用户记忆跨分区泄漏。提取规则保持保守，
并把纠正、拒绝和忘记作为一等反馈事件。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FEEDBACK_TYPES = {"confirm", "correct", "reject", "forget", "prefer_style", "change_preference"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str | int | None) -> str:
    raw = str(value or "default").strip()
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
    return raw[:80] or "default"


class MemoryService:
    def __init__(self, data_dir: str | Path | None = None):
        root = Path(data_dir or os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        self.root = root / "users"
        self.root.mkdir(parents=True, exist_ok=True)

    def user_dir(self, user_id: str | int | None) -> Path:
        path = self.root / _safe_id(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _connect(self, user_id: str | int | None) -> sqlite3.Connection:
        db = self.user_dir(user_id) / "memory.sqlite3"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                evidence TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interactions (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                reply TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                memory_id TEXT,
                feedback_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        return conn

    def extract_memory_candidates(self, message: str, source: str = "chat") -> list[dict[str, Any]]:
        text = (message or "").strip()
        if not text:
            return []
        specs = [
            ("preference_like", 0.86, r"(?:我|俺|本人)?(?:特别|很|超|比较|挺)?喜欢([^，。！？,.!?]{1,40})"),
            ("preference_dislike", 0.86, r"(?:我|俺|本人)?(?:不太喜欢|不喜欢|讨厌|反感)([^，。！？,.!?]{1,40})"),
            ("need", 0.78, r"(?:我|俺|本人)?(?:想要|需要|希望|打算|准备)([^，。！？,.!?]{1,50})"),
            ("identity", 0.88, r"(?:我叫|我的名字是|你可以叫我|叫我)([^，。！？,.!?]{1,30})"),
            ("boundary", 0.82, r"(?:以后|之后)?(?:不要|别)([^，。！？,.!?]{1,50})"),
            ("instruction", 0.84, r"(?:记住|你要记得|以后你记得)([^。！？.!?]{1,80})"),
        ]
        result: list[dict[str, Any]] = []
        for category, confidence, pattern in specs:
            for match in re.finditer(pattern, text):
                value = re.sub(r"\s+", " ", match.group(1)).strip(" ，。！？,.!?：:")
                if value and len(value) >= 1:
                    result.append({"category": category, "content": value, "confidence": confidence, "source": source, "evidence": text})
        if any(marker in text for marker in ("不是这样", "你记错了", "纠正一下", "更准确地说")):
            result.append({"category": "correction", "content": text[:200], "confidence": 0.7, "source": source, "evidence": text})
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for item in result:
            unique[(item["category"], item["content"])] = item
        return list(unique.values())

    def record_interaction(self, user_id: str, message: str, reply: str, *, source: str = "chat") -> dict[str, Any]:
        uid = _safe_id(user_id)
        conn = self._connect(uid)
        try:
            conn.execute("INSERT INTO interactions VALUES (?, ?, ?, ?, ?)", ("int_" + uuid.uuid4().hex[:12], message, reply, source, _now()))
            candidates = self.extract_memory_candidates(message, source)
            stored = [self._upsert(conn, uid, item) for item in candidates]
            conn.commit()
            return {"user_id": uid, "extracted": len(candidates), "stored": [item for item in stored if item]}
        finally:
            conn.close()

    def _upsert(self, conn: sqlite3.Connection, user_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM memories WHERE category=? AND content=? AND status='active'",
            (item["category"], item["content"]),
        ).fetchone()
        now = _now()
        if row:
            conn.execute("UPDATE memories SET occurrence_count=occurrence_count+1, confidence=MAX(confidence, ?), last_seen_at=?, updated_at=? WHERE id=?", (item["confidence"], now, now, row["id"]))
            return dict(conn.execute("SELECT * FROM memories WHERE id=?", (row["id"],)).fetchone())
        memory_id = "mem_" + uuid.uuid4().hex[:12]
        conn.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?)", (memory_id, item["category"], item["content"], item["confidence"], item["source"], item["evidence"], now, now, now))
        return dict(conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())

    def search_user_memory(self, user_id: str, query: str = "", limit: int = 8) -> list[dict[str, Any]]:
        conn = self._connect(user_id)
        try:
            rows = [dict(row) for row in conn.execute("SELECT * FROM memories WHERE status='active' ORDER BY confidence DESC, last_seen_at DESC LIMIT 300")]
            raw_query = (query or "").strip().lower()
            tokens = {token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", raw_query)}
            if raw_query:
                matched_rows = []
                for row in rows:
                    content_lower = str(row.get("content") or "").lower()
                    evidence_lower = str(row.get("evidence") or "").lower()
                    hit_count = 0
                    if raw_query in content_lower:
                        hit_count += 3
                    elif raw_query in evidence_lower:
                        hit_count += 1
                    for t in tokens:
                        if t in content_lower:
                            hit_count += 2
                        elif t in evidence_lower:
                            hit_count += 1
                    if hit_count > 0:
                        matched_rows.append((hit_count, row))

                matched_rows.sort(
                    key=lambda item: (
                        item[0],
                        item[1]["confidence"],
                        item[1]["occurrence_count"],
                    ),
                    reverse=True,
                )
                return [item[1] for item in matched_rows][: max(1, min(limit, 50))]
            return rows[: max(1, min(limit, 50))]
        finally:
            conn.close()

    def apply_feedback(self, user_id: str, feedback_type: str, memory_id: str | None = None, content: str = "") -> dict[str, Any]:
        if feedback_type not in FEEDBACK_TYPES:
            raise ValueError(f"unsupported feedback type: {feedback_type}")
        conn = self._connect(user_id)
        try:
            feedback_id = "fb_" + uuid.uuid4().hex[:12]
            conn.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?)", (feedback_id, memory_id, feedback_type, content, _now()))
            if memory_id and feedback_type in {"reject", "forget"}:
                conn.execute("UPDATE memories SET status='rejected' WHERE id=?", (memory_id,))
            if memory_id and feedback_type == "confirm":
                conn.execute("UPDATE memories SET confidence=MIN(1.0, confidence + 0.08), updated_at=? WHERE id=?", (_now(), memory_id))
            conn.commit()
            return {"feedback_id": feedback_id, "memory_id": memory_id, "feedback_type": feedback_type}
        finally:
            conn.close()

    def forget_memory(self, user_id: str, memory_id: str) -> bool:
        conn = self._connect(user_id)
        try:
            row = conn.execute("SELECT evidence FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                return False
            # A single utterance can create multiple conservative candidates
            # (for example, both a preference and an instruction). Forgetting
            # one candidate must remove the whole evidence chain.
            changed = conn.execute("UPDATE memories SET status='forgotten', updated_at=? WHERE id=? OR evidence=?", (_now(), memory_id, row["evidence"])).rowcount
            conn.commit()
            return bool(changed)
        finally:
            conn.close()

    def build_user_context(self, user_id: str, query: str = "") -> str:
        memories = self.search_user_memory(user_id, query, limit=6)
        if not memories:
            return ""
        lines = ["【长期用户记忆】"]
        lines.extend(f"- [{item['category']}] {item['content']}" for item in memories)
        return "\n".join(lines)

    def recent_interactions(self, user_id: str, limit: int = 6) -> list[str]:
        conn = self._connect(user_id)
        try:
            rows = conn.execute("SELECT message FROM interactions ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 20)),)).fetchall()
            return [str(row["message"]) for row in reversed(rows)]
        finally:
            conn.close()

    def snapshot(self, user_id: str, limit: int = 20) -> dict[str, Any]:
        return {"user_id": _safe_id(user_id), "memories": self.search_user_memory(user_id, limit=limit)}

    def get_user_profile_stats(self, user_id: str) -> dict[str, Any]:
        """获取指定用户的记忆分类统计与画像概览（供管理员画像面板使用）。"""
        uid = _safe_id(user_id)
        db_file = self.user_dir(uid) / "memory.sqlite3"
        if not db_file.exists():
            return {
                "user_id": uid,
                "total_memories": 0,
                "total_interactions": 0,
                "categories": {},
                "avg_confidence": 0.0,
            }
        conn = self._connect(uid)
        try:
            total_m = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
            total_i = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
            cat_rows = conn.execute("SELECT category, COUNT(*) as c FROM memories WHERE status = 'active' GROUP BY category").fetchall()
            categories = {row["category"]: row["c"] for row in cat_rows}
            avg_conf = conn.execute("SELECT AVG(confidence) FROM memories WHERE status = 'active'").fetchone()[0] or 0.0
            return {
                "user_id": uid,
                "total_memories": total_m,
                "total_interactions": total_i,
                "categories": categories,
                "avg_confidence": round(float(avg_conf), 2),
            }
        finally:
            conn.close()
