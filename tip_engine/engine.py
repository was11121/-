"""轻量、可关闭、带冷却的换角度提示。"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict

from unified_agent.protocol import Tip


class TipEngine:
    def __init__(self):
        self._last_emitted: dict[tuple[str, str], float] = {}
        self._dismissed: defaultdict[str, set[str]] = defaultdict(set)

    def evaluate(self, user_id: str, message: str, history: list[str], *, risks: list[str] | None = None) -> list[Tip]:
        tips: list[Tip] = []
        text = (message or "").strip()
        recent = [item.strip() for item in history[-4:] if item.strip()]
        if len(recent) >= 3 and len(set(recent[-3:])) == 1:
            tips.append(self._make(user_id, "repetition", "换一个问题角度", "你一直在确认同一个判断，要不要换成最小可行动方案？", "把‘能不能做’改成‘今天先做哪一步’？", 0.84))
        if risks and any(key in text for key in ("继续", "先不管", "以后再说")):
            tips.append(self._make(user_id, "risk", "别让风险隐身", "已有风险还没有关闭，是否先给它指定负责人和截止时间？", "把风险变成一个可追踪任务。", 0.8))
        if len(text) > 100 and not any(mark in text for mark in ("因为", "来源", "数据", "证据")):
            tips.append(self._make(user_id, "evidence", "补一条证据", "这段判断比较完整，但还缺少可核验的依据。", "试着补一个来源、样本或反例。", 0.63))
        return [tip for tip in tips if self._allowed(user_id, tip.type)]

    def dismiss(self, user_id: str, tip_type: str) -> None:
        self._dismissed[user_id].add(tip_type)

    def _allowed(self, user_id: str, tip_type: str, cooldown: int = 900) -> bool:
        if tip_type in self._dismissed[user_id]:
            return False
        key = (user_id, tip_type)
        now = time.time()
        if now - self._last_emitted.get(key, 0) < cooldown:
            return False
        self._last_emitted[key] = now
        return True

    @staticmethod
    def _make(user_id: str, tip_type: str, title: str, message: str, angle: str, confidence: float) -> Tip:
        tip_id = "tip_" + hashlib.sha1(f"{user_id}:{tip_type}".encode()).hexdigest()[:12]
        return Tip(tip_id, tip_type, title, message, angle, confidence)
