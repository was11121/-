"""一个对外 Agent，内部编排记忆、图书馆、秘书和 Tip。"""

from __future__ import annotations

import re
import uuid
from typing import Callable

from cognitive_engine import load_cognitive_engine
from library_runtime import LocalLibrary
from memory_runtime import MemoryService
from personality_runtime import PersonalityService
from secretary_runtime import SecretaryService
from tip_engine import TipEngine
from web_runtime import WebSearchService, parse_web_intent

from .llm import create_llm_responder
from .protocol import Citation, InteractionEnvelope, MemoryEvent, ResponseEnvelope, Tip


Responder = Callable[[str, str, str], str]


def _fallback_responder(message: str, user_context: str, library_context: str, web_context: str = "") -> str:
    if web_context:
        return f"以下是实时检索到的联网结果：\n\n{web_context}"
    if library_context:
        return f"我在图书馆里找到这些内容：\n\n{library_context}"
    if user_context:
        return f"我会结合你之前留下的偏好继续处理。\n\n当前请求：{message}"
    return f"我已收到：{message}"


class UnifiedAgent:
    def __init__(self, data_dir: str | None = None, responder: Responder | None = None):
        self.memory = MemoryService(data_dir)
        self.library = LocalLibrary(data_dir)
        self.secretary = SecretaryService(data_dir)
        self.personality = PersonalityService(data_dir)
        self.tips = TipEngine()
        self.cognitive = load_cognitive_engine()
        self.web = WebSearchService(data_dir)
        self.responder = responder or create_llm_responder(fallback_responder=_fallback_responder)

    def handle_interaction(self, interaction: InteractionEnvelope) -> ResponseEnvelope:
        if not interaction.message:
            raise ValueError("message is required")
        user_context = self.memory.build_user_context(interaction.user_id, interaction.message)
        personality_profile = self.personality.observe(interaction.user_id, interaction.message)
        if personality_profile.get("prompt_block"):
            user_context = (user_context + "\n\n" if user_context else "") + personality_profile["prompt_block"]
        library_results = []
        if self._looks_like_library_request(interaction.message):
            library_results = self.library.search_library(interaction.message, limit=5)
        library_context = "\n".join(f"[{item['title']}] {item['snippet']}" for item in library_results)

        # ---- 联网：识别意图 -> 搜索结果 -> 上下文/引用 ----
        web_results: list[dict] = []
        web_intent = parse_web_intent(interaction.message)
        web_context = ""
        if web_intent:
            try:
                if web_intent["intent"] == "fetch" and web_intent.get("url"):
                    page = self.web.fetch_page(web_intent["url"])
                    if page.get("content"):
                        web_context = f"【已读取网页 {web_intent['url']}】\n{page['content'][:1800]}"
                        web_results = [{
                            "title": web_intent["url"],
                            "url": web_intent["url"],
                            "snippet": (page.get("content") or "")[:160],
                            "source": "web",
                        }]
                else:
                    payload = self.web.search(web_intent["query"], limit=5)
                    web_context = self.web.build_context(web_intent["query"], limit=5)
                    web_results = payload.get("results") or []
            except Exception:
                web_context = ""

        secretary_events: list[dict] = []
        requires_confirmation = False
        if self._looks_like_sync(interaction.message):
            draft = self.secretary.draft_sync(interaction.workspace_id, interaction.message, interaction.user_id)
            secretary_events.append({"type": "sync_draft", "data": draft})
            requires_confirmation = True
        elif self._looks_like_task(interaction.message):
            title = re.sub(r"^(?:帮我|请)?(?:创建|新增|添加)?(?:一个)?任务[:：]?", "", interaction.message).strip() or interaction.message
            patch = self.secretary.create_patch(interaction.workspace_id, "task", "new", "create", title, evidence=interaction.message, created_by=interaction.user_id)
            secretary_events.append({"type": "reality_patch", "data": patch})
            requires_confirmation = True

        content = self.responder(interaction.message, user_context, library_context, web_context)
        memory_result = self.memory.record_interaction(interaction.user_id, interaction.message, content, source=interaction.channel)
        memory_events = [MemoryEvent("stored", item.get("id"), item.get("content", ""), float(item.get("confidence", 0)), item.get("category", "")) for item in memory_result.get("stored", [])]
        tip_list = self.tips.evaluate(interaction.user_id, interaction.message, self.memory.recent_interactions(interaction.user_id), risks=[])
        for item in self.personality.coaching_tips(personality_profile):
            tip_list.append(Tip(
                tip_id="tip_coach_" + uuid.uuid4().hex[:8],
                type=item["type"],
                title=item["title"],
                message=item["message"],
                alternative_angle=item.get("alternative_angle") or "",
                confidence=float(item.get("confidence") or 0.7),
                cooldown_seconds=300,
            ))
        citations = [Citation(item["document_id"], item["title"], item["source"], item.get("locator", ""), item.get("snippet", "")) for item in library_results]
        citations.extend(
            Citation("", item["title"], item.get("source") or "web", "", item.get("snippet", ""), item.get("url", ""))
            for item in web_results
            if item.get("url")
        )
        return ResponseEnvelope(
            content=content,
            citations=citations,
            memory_events=memory_events,
            secretary_events=secretary_events,
            tips=tip_list,
            requires_confirmation=requires_confirmation,
            audit_id="A-" + uuid.uuid4().hex[:10],
            metadata={"personality": {
                "scores": personality_profile.get("scores"),
                "work_style": personality_profile.get("work_style"),
                "playbook": {
                    "headline": (personality_profile.get("playbook") or {}).get("headline"),
                    "today_focus": (personality_profile.get("playbook") or {}).get("today_focus"),
                    "gaps": (personality_profile.get("playbook") or {}).get("gaps"),
                    "strengths": (personality_profile.get("playbook") or {}).get("strengths"),
                },
                "model": personality_profile.get("model"),
            }},
        )

    def record_interaction(self, user_id: str, message: str, reply: str, source: str = "chat") -> dict:
        return self.memory.record_interaction(user_id, message, reply, source=source)

    def search_user_memory(self, user_id: str, query: str = "", limit: int = 8) -> list[dict]:
        return self.memory.search_user_memory(user_id, query, limit)

    def get_user_profile_stats(self, user_id: str) -> dict:
        return self.memory.get_user_profile_stats(user_id)

    def get_personality_profile(self, user_id: str) -> dict:
        return self.personality.get_profile(user_id)

    def apply_feedback(self, user_id: str, feedback_type: str, memory_id: str | None = None, content: str = "") -> dict:
        result = self.memory.apply_feedback(user_id, feedback_type, memory_id, content)
        result["cognitive_delta"] = self.cognitive.score_feedback(result)
        return result

    def forget_memory(self, user_id: str, memory_id: str) -> bool:
        return self.memory.forget_memory(user_id, memory_id)

    def ingest_document(self, filename: str, content: bytes | str, source: str = "upload", tags: list[str] | None = None) -> dict:
        return self.library.ingest_document(filename, content, source=source, tags=tags)

    def search_library(self, query: str, limit: int = 5) -> list[dict]:
        return self.library.search_library(query, limit)

    def web_search(self, query: str, limit: int = 5) -> dict:
        return self.web.search(query, limit=limit)

    def web_fetch(self, url: str) -> dict:
        return self.web.fetch_page(url)

    def web_info(self) -> dict:
        return self.web.info()

    def confirm_patch(self, patch_id: str, actor: str) -> dict:
        return self.secretary.confirm_patch(patch_id, actor)

    def rollback_patch(self, patch_id: str, actor: str) -> dict:
        return self.secretary.rollback_patch(patch_id, actor)

    @staticmethod
    def _looks_like_library_request(message: str) -> bool:
        return any(word in message for word in ("文档", "资料", "知识", "图书馆", "来源", "引用", "PDF", "文件"))

    @staticmethod
    def _looks_like_sync(message: str) -> bool:
        return any(word in message for word in ("同步任务", "整理进展", "任务进展", "会议纪要", "项目同步"))

    @staticmethod
    def _looks_like_task(message: str) -> bool:
        return bool(re.search(r"(?:创建|新增|添加).{0,8}任务", message))
