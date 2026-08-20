"""可选旧项目兼容适配器。

新项目不修改旧源码。设置 LEGACY_AGENT_ROOT 后，适配器才会尝试加载旧
`my_agent.run_agent_simple`；未设置或加载失败时由 UnifiedAgent fallback responder 接管。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


class LegacyAgentAdapter:
    def __init__(self, source_root: str | None = None):
        self.source_root = Path(source_root or os.getenv("LEGACY_AGENT_ROOT", "")).expanduser()

    def available(self) -> bool:
        return bool(self.source_root and (self.source_root / "my_agent.py").exists())

    def reply(self, message: str, user_id: str, recent_history: str = "", summary: str = "") -> str | None:
        if not self.available():
            return None
        root = str(self.source_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            module = importlib.import_module("my_agent")
            return module.run_agent_simple(message, recent_history=recent_history, chat_summary=summary, user_id=user_id)
        except Exception:
            return None
