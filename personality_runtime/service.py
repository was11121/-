"""用户级大五人格档案（集中库版）：识别 -> 工作风格 -> 秘书督促策略。

所有用户画像统一存放在集中库（默认 SQLite: <data>/users.db，
生产可配置 DATABASE_URL 切换 PostgreSQL），profiles/observations 均带 user_id。
对外接口与旧版完全一致。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from storage.db import get_session, init_db
from storage.models import PersonalityObservationRow, PersonalityProfileRow

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
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
    return raw[:80] or "default"


class PersonalityService:
    def __init__(self, data_dir: str | Path | None = None, encoder: BertPersonalityEncoder | None = None):
        self._data_dir = Path(data_dir) if data_dir is not None else Path(
            os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data")
        )
        self.root = self._data_dir / "users"
        self.root.mkdir(parents=True, exist_ok=True)
        init_db(self._data_dir)
        self.encoder = encoder if encoder is not None else BertPersonalityEncoder(autoload=False)

    def user_dir(self, user_id: str | int | None) -> Path:
        path = self.root / _safe_id(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_scores(self, session, user_id: str) -> tuple[dict[str, float], int, str]:  # noqa: ANN001
        row = session.execute(
            select(PersonalityProfileRow).where(PersonalityProfileRow.user_id == user_id)
        ).scalar_one_or_none()
        if not row:
            return {key: 0.5 for key in TRAIT_ORDER}, 0, "none"
        scores = json.loads(row.scores_json)
        return {key: float(scores.get(key, 0.5)) for key in TRAIT_ORDER}, int(row.samples), str(row.backend)

    def observe(self, user_id: str, text: str) -> dict[str, Any]:
        uid = _safe_id(user_id)
        text = (text or "").strip()
        if len(text) < 8:
            return self.get_profile(uid)
        with get_session(self._data_dir) as session:
            prior, samples, _backend = self._load_scores(session, uid)
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
            session.add(PersonalityObservationRow(
                user_id=uid,
                text=text[:2000],
                scores_json=json.dumps(instant, ensure_ascii=False),
                backend=backend,
                created_at=now,
            ))
            profile = session.execute(
                select(PersonalityProfileRow).where(PersonalityProfileRow.user_id == uid)
            ).scalar_one_or_none()
            if profile is None:
                session.add(PersonalityProfileRow(
                    user_id=uid,
                    scores_json=json.dumps(blended, ensure_ascii=False),
                    samples=1,
                    backend=backend,
                    updated_at=now,
                ))
                new_samples = 1
            else:
                profile.scores_json = json.dumps(blended, ensure_ascii=False)
                profile.samples += 1
                profile.backend = backend
                profile.updated_at = now
                new_samples = profile.samples
            session.commit()
            return self._pack(uid, blended, new_samples, backend)

    def get_profile(self, user_id: str) -> dict[str, Any]:
        uid = _safe_id(user_id)
        with get_session(self._data_dir) as session:
            scores, samples, backend = self._load_scores(session, uid)
            return self._pack(uid, scores, samples, backend if samples else ("bert" if self.encoder.available else "heuristic"))

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