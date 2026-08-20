"""可插拔认知计算接口，默认使用纯 Python fallback。"""

from __future__ import annotations

import ctypes
import json
import os
import re
from typing import Any, Protocol


class CognitiveEngine(Protocol):
    def analyze(self, text: str, user_state: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def score_feedback(self, event: dict[str, Any], memory: dict[str, Any] | None = None) -> float: ...
    def detect_direction_shift(self, context: list[str]) -> dict[str, Any]: ...
    def update_relationship(self, state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]: ...


class PythonCognitiveEngine:
    def analyze(self, text: str, user_state: dict[str, Any] | None = None) -> dict[str, Any]:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text or "")
        return {"token_count": len(tokens), "char_count": len(text or ""), "novelty": 1.0 if text else 0.0, "question": "？" in (text or "") or "?" in (text or "")}

    def score_feedback(self, event: dict[str, Any], memory: dict[str, Any] | None = None) -> float:
        return {"confirm": 0.1, "correct": 0.05, "reject": -0.2, "forget": -0.25}.get(event.get("feedback_type", ""), 0.0)

    def detect_direction_shift(self, context: list[str]) -> dict[str, Any]:
        if len(context) < 3:
            return {"detected": False, "confidence": 0.0}
        unique = len(set(context[-3:]))
        return {"detected": unique == 1, "confidence": 0.78 if unique == 1 else 0.0}

    def update_relationship(self, state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        result = dict(state or {})
        result["score"] = max(0, min(100, int(result.get("score", 0)) + int(round(self.score_feedback(event) * 10))))
        return result


class CtypesCognitiveEngine:
    """Minimal ABI probe. The library remains optional until a stable ABI exists."""

    def __init__(self, library_path: str):
        self.library_path = library_path
        self.library = ctypes.CDLL(library_path)
        self.fallback = PythonCognitiveEngine()
        if hasattr(self.library, "rp_analyze_json"):
            self.library.rp_analyze_json.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            self.library.rp_analyze_json.restype = ctypes.c_char_p
        if hasattr(self.library, "rp_score_feedback"):
            self.library.rp_score_feedback.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            self.library.rp_score_feedback.restype = ctypes.c_double

    def analyze(self, text: str, user_state: dict[str, Any] | None = None) -> dict[str, Any]:
        function = getattr(self.library, "rp_analyze_json", None)
        if function is None:
            return self.fallback.analyze(text, user_state)
        raw = function(text.encode("utf-8"), json.dumps(user_state or {}, ensure_ascii=False).encode("utf-8"))
        try:
            return json.loads(raw.decode("utf-8")) if raw else self.fallback.analyze(text, user_state)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self.fallback.analyze(text, user_state)

    def score_feedback(self, event: dict[str, Any], memory: dict[str, Any] | None = None) -> float:
        function = getattr(self.library, "rp_score_feedback", None)
        if function is None:
            return self.fallback.score_feedback(event, memory)
        return float(function(json.dumps(event, ensure_ascii=False).encode("utf-8"), json.dumps(memory or {}, ensure_ascii=False).encode("utf-8")))

    def detect_direction_shift(self, context: list[str]) -> dict[str, Any]:
        return self.fallback.detect_direction_shift(context)

    def update_relationship(self, state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        return self.fallback.update_relationship(state, event)


def load_cognitive_engine() -> CognitiveEngine:
    path = os.getenv("COGNITIVE_ENGINE_LIBRARY", "").strip()
    if path:
        try:
            return CtypesCognitiveEngine(path)
        except OSError:
            pass
    return PythonCognitiveEngine()
