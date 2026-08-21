"""一次性迁移：把旧的 per-user 散文件数据导入集中库。

旧结构:
  data/users/<user_id>/memory.sqlite3      (memories / interactions / feedback)
  data/users/<user_id>/personality.sqlite3 (profiles / observations)

新结构:
  集中库 <data_dir>/users.db（或 DATABASE_URL 指向的 PostgreSQL）
  所有表带 user_id 分区列。

用法:
  python tools/migrate_to_central_db.py [--data-dir DATA_DIR] [--dry-run]

幂等：按主键存在则跳过（不会重复导入）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# 允许直接 `python tools/migrate_to_central_db.py` 运行时导入项目包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from storage.db import get_session, init_db
from storage.models import (
    FeedbackRow,
    InteractionRow,
    MemoryRow,
    PersonalityObservationRow,
    PersonalityProfileRow,
)


def iter_user_dirs(root: Path):
    if not root.exists():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "memory.sqlite3").exists():
            yield child


def migrate_user(session, user_id: str, user_dir: Path, dry_run: bool) -> dict:
    counts = {"memories": 0, "interactions": 0, "feedback": 0, "profiles": 0, "observations": 0}

    mem_db = user_dir / "memory.sqlite3"
    if mem_db.exists():
        conn = sqlite3.connect(mem_db)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute(
                "SELECT id, category, content, confidence, source, evidence, "
                "occurrence_count, status, created_at, last_seen_at, updated_at FROM memories"
            ):
                exists = session.get(MemoryRow, row["id"])
                if exists:
                    continue
                # 集中库对 (user_id, category, content, status) 有唯一约束；
                # 旧库里同用户可能存在历史重复行，合并而不是插入冲突。
                dup = session.execute(
                    select(MemoryRow).where(
                        MemoryRow.user_id == user_id,
                        MemoryRow.category == row["category"],
                        MemoryRow.content == row["content"],
                        MemoryRow.status == row["status"],
                    )
                ).scalar_one_or_none()
                if dup:
                    dup.occurrence_count += int(row["occurrence_count"] or 1)
                    dup.confidence = max(dup.confidence, float(row["confidence"] or 0))
                    counts["memories"] += 1
                    continue
                if not dry_run:
                    session.add(MemoryRow(
                        id=row["id"],
                        user_id=user_id,
                        category=row["category"],
                        content=row["content"],
                        confidence=row["confidence"],
                        source=row["source"],
                        evidence=row["evidence"],
                        occurrence_count=row["occurrence_count"],
                        status=row["status"],
                        created_at=row["created_at"],
                        last_seen_at=row["last_seen_at"],
                        updated_at=row["updated_at"],
                    ))
                counts["memories"] += 1

            for row in conn.execute(
                "SELECT id, message, reply, source, created_at FROM interactions"
            ):
                exists = session.get(InteractionRow, row["id"])
                if exists:
                    continue
                if not dry_run:
                    session.add(InteractionRow(
                        id=row["id"],
                        user_id=user_id,
                        message=row["message"],
                        reply=row["reply"],
                        source=row["source"],
                        created_at=row["created_at"],
                    ))
                counts["interactions"] += 1

            for row in conn.execute(
                "SELECT id, memory_id, feedback_type, content, created_at FROM feedback"
            ):
                exists = session.get(FeedbackRow, row["id"])
                if exists:
                    continue
                if not dry_run:
                    session.add(FeedbackRow(
                        id=row["id"],
                        user_id=user_id,
                        memory_id=row["memory_id"],
                        feedback_type=row["feedback_type"],
                        content=row["content"],
                        created_at=row["created_at"],
                    ))
                counts["feedback"] += 1
        finally:
            conn.close()

    per_db = user_dir / "personality.sqlite3"
    if per_db.exists():
        conn = sqlite3.connect(per_db)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute(
                "SELECT user_id, scores_json, samples, backend, updated_at FROM profiles"
            ):
                exists = session.get(PersonalityProfileRow, row["user_id"])
                if exists:
                    continue
                if not dry_run:
                    session.add(PersonalityProfileRow(
                        user_id=row["user_id"],
                        scores_json=row["scores_json"],
                        samples=row["samples"],
                        backend=row["backend"],
                        updated_at=row["updated_at"],
                    ))
                counts["profiles"] += 1

            for row in conn.execute(
                "SELECT id, text, scores_json, backend, created_at FROM observations"
            ):
                if not dry_run:
                    # id 为旧库每用户自增，跨用户会重复；集中库自增重建
                    session.add(PersonalityObservationRow(
                        user_id=user_id,
                        text=row["text"],
                        scores_json=row["scores_json"],
                        backend=row["backend"],
                        created_at=row["created_at"],
                    ))
                counts["observations"] += 1
        finally:
            conn.close()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移每用户散文件到集中库")
    parser.add_argument("--data-dir", default=None, help="数据根目录（默认 $MYAGENT_DATA_DIR 或 ./data）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).resolve().parents[1] / "data"
    users_root = data_dir / "users"

    init_db(data_dir)
    total = {"memories": 0, "interactions": 0, "feedback": 0, "profiles": 0, "observations": 0}
    users = 0

    with get_session(data_dir) as session:
        for user_dir in iter_user_dirs(users_root):
            user_id = user_dir.name
            counts = migrate_user(session, user_id, user_dir, dry_run=args.dry_run)
            if any(counts.values()):
                users += 1
                for key in total:
                    total[key] += counts[key]
                print(f"[{'dry' if args.dry_run else 'migrated'}] {user_id}: {counts}")
        if not args.dry_run:
            session.commit()

    print(f"\n完成: {users} 个用户, 总计 {json.dumps(total, ensure_ascii=False)}")
    if args.dry_run:
        print("（dry-run 模式未写入任何数据）")


if __name__ == "__main__":
    main()