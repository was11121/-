"""通过远端 mcp-db 服务做记忆/人格的 MCP 客户端（可选）。

当 MEMORY_BACKEND=mcp 时 UnifiedAgent 会尝试使用此客户端；
若远端不可用或本文件缺失，会自动回退到本地 MemoryService / PersonalityService。
保留此 stub 以避免 import 失败；真实逻辑与历史实现一致，调用远端 /v1/call。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class MemoryMcpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class MemoryMcpClient:
    """远端 `/v1/call` 包装的 MemoryService / PersonalityService 同步代理"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: int = 10):
        self.base_url = (base_url or os.getenv("MEMORY_MCP_URL") or "http://127.0.0.1:8092").rstrip("/")
        self.api_key = api_key or os.getenv("MCP_API_KEY") or ""
        self.timeout = timeout

    # --- MemoryService 兼容 ---
    def search_user_memory(self, user_id: str, query: str = "", limit: int = 8) -> list[dict]:
        return self.call("search_memories", {"user_id": user_id, "query": query, "limit": limit}) or []

    def build_user_context(self, user_id: str, query: str = "") -> str:
        payload = self.call("build_user_context", {"user_id": user_id, "query": query})
        if isinstance(payload, dict):
            return payload.get("context") or payload.get("result") or ""
        return str(payload or "")

    def recent_interactions(self, user_id: str, limit: int = 6) -> list[str]:
        result = self.call("recent_interactions", {"user_id": user_id, "limit": limit})
        return result or [] if isinstance(result, list) else []

    def get_user_profile_stats(self, user_id: str) -> dict:
        return self.call("memory_stats", {"user_id": user_id}) or {}

    def record_interaction(self, user_id: str, message: str, reply: str, source: str = "chat") -> dict:
        return self.call("record_interaction", {"user_id": user_id, "message": message, "reply": reply, "source": source}) or {}

    def apply_feedback(self, user_id: str, feedback_type: str, memory_id: str | None = None, content: str = "") -> dict:
        return self.call("apply_feedback", {"user_id": user_id, "feedback_type": feedback_type, "memory_id": memory_id, "content": content}) or {}

    def forget_memory(self, user_id: str, memory_id: str) -> bool:
        result = self.call("forget_memory", {"user_id": user_id, "memory_id": memory_id})
        if isinstance(result, dict):
            return bool(result.get("success") or result.get("ok"))
        return bool(result)

    # --- PersonalityService 兼容 ---
    def get_profile(self, user_id: str) -> dict:
        return self.call("get_personality_profile", {"user_id": user_id}) or {}

    def observe(self, user_id: str, text: str) -> dict:
        return self.call("observe_personality", {"user_id": user_id, "text": text}) or {}

    def coaching_tips(self, profile: dict) -> list[dict]:
        from personality_runtime.service import PersonalityService  # local fallback for tips generation

        svc = PersonalityService()
        return svc.coaching_tips(profile)

    # --- 底层 ---
    def call(self, name: str, arguments: dict) -> Any:
        body = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/v1/call", data=body, method="POST", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
                return data
        except urllib.error.HTTPError as exc:
            raise MemoryMcpError(f"memory MCP unreachable: {exc}", status=exc.code) from exc
        except Exception as exc:  # noqa: BLE001
            raise MemoryMcpError(f"memory MCP unreachable: {exc}") from exc

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
