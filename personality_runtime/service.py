"""用户级大五人格档案：识别 -> 工作风格 -> 秘书督促策略。"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bert_encoder import BertPersonalityEncoder
from .heuristic import heuristic_scores
from .traits import (
    TRAIT_ORDER,
    TRAITS,
    clamp01,
    coaching_playbook,
    coaching_prompt_block,
    derive_work_style,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str | int | None) -> str:
    raw = str(value or "default").strip()
    import re

    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
    return raw[:80] or "default"


class PersonalityService:
    def __init__(self, data_dir: str | Path | None = None, encoder: BertPersonalityEncoder | None = None):
        root = Path(data_dir or os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        self.root = root / "users"
        self.root.mkdir(parents=True, exist_ok=True)
        self.encoder = encoder if encoder is not None else BertPersonalityEncoder(autoload=False)

    def user_dir(self, user_id: str | int | None) -> Path:
        path = self.root / _safe_id(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _connect(self, user_id: str | int | None) -> sqlite3.Connection:
        db = self.user_dir(user_id) / "personality.sqlite3"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                user_id TEXT PRIMARY KEY,
                scores_json TEXT NOT NULL,
                samples INTEGER NOT NULL DEFAULT 0,
                backend TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                scores_json TEXT NOT NULL,
                backend TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        return conn

    def _load_scores(self, conn: sqlite3.Connection, user_id: str) -> tuple[dict[str, float], int, str]:
        row = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {key: 0.5 for key in TRAIT_ORDER}, 0, "none"
        scores = json.loads(row["scores_json"])
        return {key: float(scores.get(key, 0.5)) for key in TRAIT_ORDER}, int(row["samples"]), str(row["backend"])

    def observe(self, user_id: str, text: str) -> dict[str, Any]:
        uid = _safe_id(user_id)
        text = (text or "").strip()
        if len(text) < 8:
            return self.get_profile(uid)
        conn = self._connect(uid)
        try:
            prior, samples, _backend = self._load_scores(conn, uid)
            bert_scores = self.encoder.score(text) if self.encoder.available else {}
            heuristic = heuristic_scores(text, prior)
            if bert_scores:
                # 中文文本 BERT 英文模型会偏弱，与启发式混合
                has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
                bert_weight = 0.35 if has_cjk else 0.7
                instant = {
                    key: clamp01(bert_scores.get(key, heuristic[key]) * bert_weight + heuristic[key] * (1 - bert_weight))
                    for key in TRAIT_ORDER
                }
                backend = "bert+heuristic" if has_cjk else "bert"
            else:
                instant = heuristic
                backend = "heuristic"
            alpha = 0.28 if samples else 1.0
            blended = {key: clamp01(prior[key] * (1 - alpha) + instant[key] * alpha) for key in TRAIT_ORDER}
            blended = {key: round(blended[key], 4) for key in TRAIT_ORDER}
            now = _now()
            conn.execute(
                "INSERT INTO observations(text, scores_json, backend, created_at) VALUES (?, ?, ?, ?)",
                (text[:2000], json.dumps(instant, ensure_ascii=False), backend, now),
            )
            conn.execute(
                """
                INSERT INTO profiles(user_id, scores_json, samples, backend, updated_at)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    scores_json=excluded.scores_json,
                    samples=samples+1,
                    backend=excluded.backend,
                    updated_at=excluded.updated_at
                """,
                (uid, json.dumps(blended, ensure_ascii=False), backend, now),
            )
            conn.commit()
            return self._pack(uid, blended, samples + 1, backend)
        finally:
            conn.close()

    def get_profile(self, user_id: str) -> dict[str, Any]:
        uid = _safe_id(user_id)
        conn = self._connect(uid)
        try:
            scores, samples, backend = self._load_scores(conn, uid)
            return self._pack(uid, scores, samples, backend if samples else ("bert" if self.encoder.available else "heuristic"))
        finally:
            conn.close()

    def _pack(self, user_id: str, scores: dict[str, float], samples: int, backend: str) -> dict[str, Any]:
        work = derive_work_style(scores)
        playbook = coaching_playbook(scores, work)
        encoder_info = self.encoder.info()
        return {
            "user_id": user_id,
            "model": {
                "id": encoder_info.get("model_id"),
                "backend": backend,
                "encoder_available": encoder_info.get("available"),
                "encoder_error": encoder_info.get("error") or "",
                "disclaimer": "估计值仅用于秘书督促，不是心理诊断，也不能控制真人人格。",
            },
            "traits": [
                {
                    **TRAITS[key],
                    "score": scores[key],
                    "band": work["bands"][key],
                }
                for key in TRAIT_ORDER
            ],
            "scores": scores,
            "samples": samples,
            "work_style": work,
            "playbook": playbook,
            "prompt_block": coaching_prompt_block({"scores": scores, "work_style": work, "playbook": playbook}),
        }

    def coaching_tips(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        play = profile.get("playbook") or {}
        tips = []
        for index, focus in enumerate(play.get("today_focus") or []):
            tips.append(
                {
                    "type": "coaching",
                    "title": play.get("headline") or "秘书督促",
                    "message": focus,
                    "alternative_angle": (play.get("tactics") or [""])[min(index, max(0, len(play.get("tactics") or []) - 1))],
                    "confidence": 0.72,
                }
            )
        return tips[:2]
