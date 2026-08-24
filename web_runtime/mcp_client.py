"""通过远端 mcp-web 服务做联网搜索的 MCP 客户端（可选）。

与 MemoryMcpClient 对称：当 WEB_BACKEND=mcp 时 UnifiedAgent 会尝试使用此客户端；
缺失或远端不可用时回退到本地 WebSearchService。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class WebMcpError(RuntimeError):
    pass


class WebMcpClient:
    """远端 WebSearchService 同步代理，UnifiedAgent 无需改动即可切换"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: int = 15):
        self.base_url = (base_url or os.getenv("WEB_MCP_URL") or "http://127.0.0.1:8093").rstrip("/")
        self.api_key = api_key or os.getenv("MCP_API_KEY") or ""
        self.timeout = timeout

    def search(self, query: str, limit: int = 5) -> dict:
        return self._call("web_search", {"query": query, "limit": limit})

    def build_context(self, query: str, limit: int = 5) -> str:
        res = self._call("web_build_context", {"query": query, "limit": limit})
        if isinstance(res, dict):
            return res.get("context") or res.get("result") or ""
        return str(res or "")

    def fetch_page(self, url: str) -> dict:
        return self._call("web_fetch", {"url": url})

    def info(self) -> dict:
        return self._call("web_info", {})

    def _call(self, name: str, arguments: dict) -> Any:
        body = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/v1/call", data=body, method="POST", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
                return data if isinstance(data, dict) else {"content": str(data)}
        except urllib.error.HTTPError as exc:
            return {"error": f"web MCP unreachable: {exc}", "channel": "none", "results": []}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"web MCP unreachable: {exc}", "channel": "none", "results": []}

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
