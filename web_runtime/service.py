"""渠道无关的联网服务：搜索、读网页，支持多通道自动故障转移。

通道优先级（谁可用用谁，避免单点失效）：
1. 本地 searxng（默认 http://localhost:8080/search）—— 免费、无额度限制
2. Tavily API（默认读取 ~/.dsh/.credentials.yaml 或环境变量 TAVILY_API_KEY）—— AI 优化
3. 新加坡 SSH 中转（配置 WEB_RELAY_SSH_* 后启用）—— 直连被墙/超时的兜底
网页正文统一走 Jina Reader（https://r.jina.ai/<URL>），也支持经中转读取。

所有通道都失败时返回空结果 + error 说明，绝不抛出未捕获异常影响主回答。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

DEFAULT_SEARXNG_URL = "http://localhost:8080/search"
DEFAULT_JINA_READER = "https://r.jina.ai"


def _now_mark() -> str:
    import datetime

    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def _credentials_key(key_name: str) -> str:
    """从 ~/.dsh/.credentials.yaml 读取 key（兼容 DSH 技能配置）。"""
    try:
        path = Path.home() / ".dsh" / ".credentials.yaml"
        if not path.exists():
            return ""
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*" + re.escape(key_name) + r"\s*:\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


class WebSearchService:
    def __init__(self, data_dir: str | Path | None = None):
        # 独立使用时自动加载项目 .env（app.py 已加载时此处为幂等）
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except Exception:
            pass
        self.data_dir = Path(data_dir or os.getenv("MYAGENT_DATA_DIR", "data"))
        self.searxng_url = os.getenv("SEARXNG_URL", DEFAULT_SEARXNG_URL).rstrip("/")
        self.tavily_key = (
            os.getenv("TAVILY_API_KEY", "").strip()
            or _credentials_key("TAVILY_API_KEY")
        )
        self.relay_host = os.getenv("WEB_RELAY_SSH_HOST", "").strip()
        self.relay_user = os.getenv("WEB_RELAY_SSH_USER", "").strip() or "admin"
        self.relay_key = os.getenv("WEB_RELAY_SSH_KEY", "").strip() or str(
            Path.home() / ".ssh" / "aliyun_dsh"
        )
        self.timeout = float(os.getenv("WEB_SEARCH_TIMEOUT", "20"))

    # ------------------------------------------------------------------
    # 对外核心方法
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """多通道搜索，返回 {channel, results, answer, error}。"""
        query = (query or "").strip()
        if not query:
            return {"channel": "none", "results": [], "answer": "", "error": "query is empty"}
        errors: list[str] = []

        # 1) 本地 searxng
        results = self._search_searxng(query, limit)
        if results:
            return {"channel": "searxng", "results": results, "answer": "", "error": ""}
        errors.append("searxng unavailable")

        # 2) Tavily 直连
        if self.tavily_key:
            tavily = self._search_tavily(query, limit, via_relay=False)
            if tavily and tavily.get("results"):
                return {"channel": "tavily", **tavily}
            errors.append(f"tavily direct: {tavily.get('error', 'empty')}")

        # 3) 新加坡中转（Tavily 或 searxng 远端）
        if self.relay_host:
            relayed = self._search_tavily(query, limit, via_relay=True)
            if relayed and relayed.get("results"):
                return {"channel": "tavily-relay", **relayed}
            errors.append(f"tavily relay: {relayed.get('error', 'empty')}")

        return {"channel": "none", "results": [], "answer": "", "error": " | ".join(errors)}

    def fetch_page(self, url: str, via_relay: bool | None = None) -> dict[str, Any]:
        """读取网页正文（Jina Reader），返回 {content, error, via}。"""
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"content": "", "error": "not a valid http(s) url", "via": "none"}

        if via_relay is None:
            # 先直连，失败再中转
            direct = self._jina_read(url, via_relay=False)
            if not direct.get("error") and direct.get("content", "").strip():
                direct["via"] = "jina-direct"
                return direct
        if via_relay is False:
            result = self._jina_read(url, via_relay=False)
            result["via"] = "jina-direct"
            return result

        if self.relay_host:
            relayed = self._jina_read(url, via_relay=True)
            relayed["via"] = "jina-relay"
            return relayed

        direct = self._jina_read(url, via_relay=False)
        direct["via"] = "jina-direct"
        return direct

    def build_context(self, query: str, limit: int = 5, max_chars: int = 2200) -> str:
        """把搜索结果拼成给 LLM 的上下文文本。"""
        payload = self.search(query, limit=limit)
        results = payload.get("results") or []
        if not results:
            return ""
        lines = [f"【联网检索结果 · {_now_mark()}】（检索词：{query}）"]
        answer = payload.get("answer")
        if answer:
            lines.append(f"综合摘要：{answer}")
        for i, item in enumerate(results, 1):
            title = item.get("title") or ""
            url = item.get("url") or ""
            snippet = (item.get("content") or item.get("snippet") or "").replace("\n", " ")
            lines.append(f"{i}. {title}｜{url}")
            if snippet:
                lines.append(f"   {snippet[:max_chars]}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 内部分通道实现
    # ------------------------------------------------------------------

    def _search_searxng(self, query: str, limit: int) -> list[dict[str, Any]]:
        try:
            url = f"{self.searxng_url}?q={urllib.parse.quote(query)}&format=json&engines=baidu,google,bing"
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            items = data.get("results") or []
            return [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": (item.get("content") or item.get("snippet") or "")[:600],
                    "content": (item.get("content") or item.get("snippet") or "")[:600],
                    "source": item.get("engine", "searxng"),
                    "score": float(item.get("score") or 0),
                }
                for item in items[:limit]
            ]
        except Exception:
            return []

    def _search_tavily(self, query: str, limit: int, via_relay: bool) -> dict[str, Any]:
        if via_relay:
            return self._tavily_relay(query, limit)
        body = {
            "query": query,
            "search_depth": "basic",
            "max_results": limit,
            "include_answer": True,
            "topic": "general",
        }
        try:
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {self.tavily_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items = data.get("results") or []
            return {
                "results": [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": (item.get("content") or "")[:600],
                        "content": (item.get("content") or "")[:600],
                        "source": item.get("source", "tavily"),
                        "score": float(item.get("score") or 0),
                    }
                    for item in items[:limit]
                ],
                "answer": data.get("answer") or "",
                "error": "",
            }
        except Exception as exc:
            return {"results": [], "answer": "", "error": str(exc)[:200]}

    def _tavily_relay(self, query: str, limit: int) -> dict[str, Any]:
        """经新加坡中转调用 Tavily：把 body 写到远端临时文件再 curl。"""
        body = json.dumps(
            {"query": query, "search_depth": "basic", "max_results": limit, "include_answer": True},
            ensure_ascii=False,
        )
        out, err = self._relay_stdin(
            f"cat > /tmp/rp_tavily.json && curl -s -m 25 -X POST 'https://api.tavily.com/search' "
            f"-H 'Authorization: Bearer {self.tavily_key}' "
            f"-H 'Content-Type: application/json; charset=utf-8' --data-binary @/tmp/rp_tavily.json",
            body,
        )
        if err:
            return {"results": [], "answer": "", "error": err.strip()[:200]}
        try:
            data = json.loads(out or "{}")
        except Exception:
            return {"results": [], "answer": "", "error": "relay returned non-json"}
        items = data.get("results") or []
        return {
            "results": [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": (item.get("content") or "")[:600],
                    "content": (item.get("content") or "")[:600],
                    "source": item.get("source", "tavily-relay"),
                    "score": float(item.get("score") or 0),
                }
                for item in items[:limit]
            ],
            "answer": data.get("answer") or "",
            "error": "",
        }

    def _jina_read(self, url: str, via_relay: bool) -> dict[str, Any]:
        target = f"{DEFAULT_JINA_READER}/{url}"
        if via_relay:
            out, err = self._relay_command(
                f"curl -s -m 30 '{target}' | head -c 6000"
            )
            if err:
                return {"content": "", "error": err.strip()[:200]}
            return {"content": out[:6000], "error": ""}
        try:
            req = urllib.request.Request(target, headers={"User-Agent": "MyAgentUnified/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            return {"content": content[:6000], "error": ""}
        except Exception as exc:
            return {"content": "", "error": str(exc)[:200]}

    # ------------------------------------------------------------------
    # SSH 中转底层
    # ------------------------------------------------------------------

    def _relay_args(self) -> list[str]:
        return [
            "ssh",
            "-i", self.relay_key,
            "-o", "ConnectTimeout=15",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            f"{self.relay_user}@{self.relay_host}",
        ]

    def _relay_command(self, remote_cmd: str) -> tuple[str, str]:
        """在远端执行命令，返回 (stdout, stderr)。"""
        if not self.relay_host:
            return "", "relay not configured"
        try:
            proc = subprocess.run(
                self._relay_args() + [remote_cmd],
                capture_output=True,
                text=False,
                timeout=60,
            )
            return (
                proc.stdout.decode("utf-8", errors="replace"),
                proc.stderr.decode("utf-8", errors="replace"),
            )
        except Exception as exc:
            return "", f"relay ssh failed: {exc}"

    def _relay_stdin(self, remote_cmd: str, stdin_data: str) -> tuple[str, str]:
        """在远端执行命令，并把 stdin_data 通过管道写入远端进程。"""
        if not self.relay_host:
            return "", "relay not configured"
        try:
            proc = subprocess.run(
                self._relay_args() + [remote_cmd],
                input=stdin_data.encode("utf-8"),
                capture_output=True,
                text=False,
                timeout=60,
            )
            return (
                proc.stdout.decode("utf-8", errors="replace"),
                proc.stderr.decode("utf-8", errors="replace"),
            )
        except Exception as exc:
            return "", f"relay ssh failed: {exc}"

    def info(self) -> dict[str, Any]:
        return {
            "searxng_url": self.searxng_url,
            "tavily_configured": bool(self.tavily_key),
            "relay_configured": bool(self.relay_host),
            "relay_host": self.relay_host,
        }


# ----------------------------------------------------------------------
# 意图识别工具
# ----------------------------------------------------------------------

WEB_TRIGGER_WORDS = [
    "搜索", "搜一下", "百度一下", "google", "谷歌", "查一下", "查一查", "查查",
    "查资料", "最新", "新闻", "行情", "对比一下", "搜搜", "上网查", "联网",
    "找一下", "帮我查", "网上查", "看看网上怎么说", "有什么消息", "有什么新闻",
]

URL_PATTERN = re.compile(r"https?://[^\s，。；！？]+")


def parse_web_intent(message: str) -> dict[str, Any] | None:
    """判断一条消息是否需要联网。

    返回 {"intent": "search"|"fetch", "query": ..., "url": ...} 或 None。
    显式前缀（/联网、!web、!search）一定触发；包含 URL 则优先读网页；否则看关键词。
    """
    text = (message or "").strip()
    if not text:
        return None
    lowered = text.lower()

    if lowered.startswith(("/lianwang", "/联网", "!web", "!search", "/web", "/search")):
        rest = re.sub(r"^(/lianwang|/联网|!web|!search|/web|/search)\s*", "", text, flags=re.IGNORECASE).strip()
        urls = URL_PATTERN.findall(rest)
        if urls:
            return {"intent": "fetch", "query": rest, "url": urls[0]}
        return {"intent": "search", "query": rest or "综合新闻", "url": ""}

    urls = URL_PATTERN.findall(text)
    if urls:
        return {"intent": "fetch", "query": text, "url": urls[0]}

    if any(word in text for word in WEB_TRIGGER_WORDS):
        return {"intent": "search", "query": text, "url": ""}
    return None


def looks_like_web_request(message: str) -> bool:
    return parse_web_intent(message) is not None
