"""本地隔离的长期反馈记忆服务（集中库版）。

所有用户数据统一存放在集中库（默认 SQLite: <data>/users.db，
生产可配置 DATABASE_URL 切换 PostgreSQL），每行带 user_id 分区列。
对外接口与旧版完全一致，仅供上层（UnifiedAgent / API）无感调用。

提取规则保持保守，并把纠正、拒绝和忘记作为一等反馈事件。
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update

from storage.db import get_session, init_db
from storage.models import FeedbackRow, InteractionRow, MemoryRow

FEEDBACK_TYPES = {"confirm", "correct", "reject", "forget", "prefer_style", "change_preference", "annotate"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str | int | None) -> str:
    raw = str(value or "default").strip()
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
    return raw[:80] or "default"


class MemoryService:
    def __init__(self, data_dir: str | Path | None = None):
        self._data_dir = Path(data_dir) if data_dir is not None else Path(
            os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data")
        )
        self.root = self._data_dir / "users"
        self.root.mkdir(parents=True, exist_ok=True)
        init_db(self._data_dir)

    # ---------- 兼容接口：旧路径（仅供外部引用，新数据不再写入） ----------
    def user_dir(self, user_id: str | int | None) -> Path:
        path = self.root / _safe_id(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ---------- 记忆提取 ----------
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

    # ---------- 交互记录 ----------
    def record_interaction(self, user_id: str, message: str, reply: str, *, source: str = "chat") -> dict[str, Any]:
        uid = _safe_id(user_id)
        with get_session(self._data_dir) as session:
            session.add(InteractionRow(
                id="int_" + uuid.uuid4().hex[:12],
                user_id=uid,
                message=message,
                reply=reply,
                source=source,
                created_at=_now(),
            ))
            candidates = self.extract_memory_candidates(message, source)
            stored = [self._upsert(session, uid, item) for item in candidates]
            session.commit()
            return {"user_id": uid, "extracted": len(candidates), "stored": [item for item in stored if item]}

    def _upsert(self, session, user_id: str, item: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ANN001
        row = session.execute(
            select(MemoryRow).where(
                MemoryRow.user_id == user_id,
                MemoryRow.category == item["category"],
                MemoryRow.content == item["content"],
                MemoryRow.status == "active",
            )
        ).scalar_one_or_none()
        now = _now()
        if row:
            row.occurrence_count += 1
            row.confidence = max(row.confidence, item["confidence"])
            row.last_seen_at = now
            row.updated_at = now
            session.flush()
            return {
                "id": row.id,
                "category": row.category,
                "content": row.content,
                "confidence": row.confidence,
                "source": row.source,
                "evidence": row.evidence,
                "occurrence_count": row.occurrence_count,
                "status": row.status,
            }
        memory_id = "mem_" + uuid.uuid4().hex[:12]
        memory_row = MemoryRow(
            id=memory_id,
            user_id=user_id,
            category=item["category"],
            content=item["content"],
            confidence=item["confidence"],
            source=item["source"],
            evidence=item["evidence"],
            occurrence_count=1,
            status="active",
            created_at=now,
            last_seen_at=now,
            updated_at=now,
        )
        session.add(memory_row)
        session.flush()
        return {
            "id": memory_id,
            "category": item["category"],
            "content": item["content"],
            "confidence": item["confidence"],
            "source": item["source"],
            "evidence": item["evidence"],
            "occurrence_count": 1,
            "status": "active",
        }

    # ---------- 检索 ----------
    def search_user_memory(self, user_id: str, query: str = "", limit: int = 8) -> list[dict[str, Any]]:
        uid = _safe_id(user_id)
        with get_session(self._data_dir) as session:
            rows = [
                row
                for row in session.execute(
                    select(MemoryRow).where(MemoryRow.user_id == uid, MemoryRow.status == "active")
                    .order_by(MemoryRow.confidence.desc(), MemoryRow.last_seen_at.desc())
                    .limit(300)
                ).scalars()
            ]
            raw_query = (query or "").strip().lower()
            tokens = {token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", raw_query)}
            if raw_query:
                matched_rows = []
                for row in rows:
                    content_lower = str(row.content or "").lower()
                    evidence_lower = str(row.evidence or "").lower()
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
                        item[1].confidence,
                        item[1].occurrence_count,
                    ),
                    reverse=True,
                )
                return [
                    self._to_dict(item[1]) for item in matched_rows[: max(1, min(limit, 50))]
                ]
            return [self._to_dict(r) for r in rows[: max(1, min(limit, 50))]]

    @staticmethod
    def _to_dict(row: MemoryRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "category": row.category,
            "content": row.content,
            "confidence": row.confidence,
            "source": row.source,
            "evidence": row.evidence,
            "occurrence_count": row.occurrence_count,
            "status": row.status,
            "created_at": row.created_at,
            "last_seen_at": row.last_seen_at,
            "updated_at": row.updated_at,
        }

    # ---------- 反馈与遗忘 ----------
    def apply_feedback(self, user_id: str, feedback_type: str, memory_id: str | None = None, content: str = "") -> dict[str, Any]:
        if feedback_type not in FEEDBACK_TYPES:
            raise ValueError(f"unsupported feedback type: {feedback_type}")
        uid = _safe_id(user_id)
        now = _now()
        with get_session(self._data_dir) as session:
            feedback_id = "fb_" + uuid.uuid4().hex[:12]
            session.add(FeedbackRow(
                id=feedback_id,
                user_id=uid,
                memory_id=memory_id,
                feedback_type=feedback_type,
                content=content,
                created_at=now,
            ))
            if memory_id and feedback_type in {"reject", "forget"}:
                session.execute(
                    update(MemoryRow)
                    .where(MemoryRow.id == memory_id, MemoryRow.user_id == uid)
                    .values(status="rejected")
                )
            if memory_id and feedback_type == "confirm":
                row = session.execute(
                    select(MemoryRow).where(MemoryRow.id == memory_id, MemoryRow.user_id == uid)
                ).scalar_one_or_none()
                if row:
                    row.confidence = min(1.0, row.confidence + 0.08)
                    row.updated_at = now
            session.commit()
            return {"feedback_id": feedback_id, "memory_id": memory_id, "feedback_type": feedback_type}

    def forget_memory(self, user_id: str, memory_id: str) -> bool:
        uid = _safe_id(user_id)
        with get_session(self._data_dir) as session:
            row = session.execute(
                select(MemoryRow).where(MemoryRow.id == memory_id, MemoryRow.user_id == uid)
            ).scalar_one_or_none()
            if not row:
                return False
            # A single utterance can create multiple conservative candidates
            # (for example, both a preference and an instruction). Forgetting
            # one candidate must remove the whole evidence chain.
            changed = session.execute(
                update(MemoryRow)
                .where(MemoryRow.user_id == uid, (MemoryRow.id == memory_id) | (MemoryRow.evidence == row.evidence))
                .values(status="forgotten", updated_at=_now())
            ).rowcount
            session.commit()
            return bool(changed)

    # ---------- 上下文 / 快照 / 统计 ----------
    def build_user_context(self, user_id: str, query: str = "") -> str:
        memories = self.search_user_memory(user_id, query, limit=6)
        if not memories:
            return ""
        lines = ["【长期用户记忆】"]
        lines.extend(f"- [{item['category']}] {item['content']}" for item in memories)
        return "\n".join(lines)

    def recent_interactions(self, user_id: str, limit: int = 6) -> list[str]:
        uid = _safe_id(user_id)
        n = max(1, min(limit, 20))
        with get_session(self._data_dir) as session:
            rows = session.execute(
                select(InteractionRow.message)
                .where(InteractionRow.user_id == uid)
                .order_by(InteractionRow.created_at.desc())
                .limit(n)
            ).scalars().all()
            return [str(msg) for msg in reversed(rows)]

    def snapshot(self, user_id: str, limit: int = 20) -> dict[str, Any]:
        return {"user_id": _safe_id(user_id), "memories": self.search_user_memory(user_id, limit=limit)}

    def get_user_profile_stats(self, user_id: str) -> dict[str, Any]:
        """获取指定用户的记忆分类统计与画像概览（供管理员画像面板使用）。"""
        uid = _safe_id(user_id)
        with get_session(self._data_dir) as session:
            total_m = session.execute(
                select(func.count()).select_from(MemoryRow).where(MemoryRow.user_id == uid, MemoryRow.status == "active")
            ).scalar_one() or 0
            total_i = session.execute(
                select(func.count()).select_from(InteractionRow).where(InteractionRow.user_id == uid)
            ).scalar_one() or 0
            cat_rows = session.execute(
                select(MemoryRow.category, func.count().label("c"))
                .where(MemoryRow.user_id == uid, MemoryRow.status == "active")
                .group_by(MemoryRow.category)
            ).all()
            categories = {str(row[0]): int(row[1]) for row in cat_rows}
            avg_conf = session.execute(
                select(func.avg(MemoryRow.confidence)).where(MemoryRow.user_id == uid, MemoryRow.status == "active")
            ).scalar_one() or 0.0
            return {
                "user_id": uid,
                "total_memories": int(total_m),
                "total_interactions": int(total_i),
                "categories": categories,
                "avg_confidence": round(float(avg_conf), 2),
            }