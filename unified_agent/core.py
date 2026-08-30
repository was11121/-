"""一个对外 Agent，内部编排记忆、图书馆、秘书和 Tip。"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Callable
from datetime import datetime, timezone

import jieba

from cognitive_engine import load_cognitive_engine
from library_runtime import LocalLibrary
from memory_runtime import MemoryService
from memory_runtime.graph import build_memory_graph
try:
    from memory_runtime.mcp_client import MemoryMcpClient  # type: ignore
except Exception:  # pragma: no cover - MCP 可选，未安装时回退本地
    MemoryMcpClient = None  # type: ignore
from personality_runtime import PersonalityService
from secretary_runtime import SecretaryService
from tip_engine import TipEngine
from web_runtime import WebSearchService, parse_web_intent
try:
    from web_runtime.mcp_client import WebMcpClient  # type: ignore
except Exception:  # pragma: no cover
    WebMcpClient = None  # type: ignore
from storage.db import get_session
from storage.models import (
    FeedbackRow,
    InteractionRow,
    MemoryRow,
    PersonalityObservationRow,
    PersonalityProfileRow,
)

from .llm import create_llm_responder
from .protocol import Citation, InteractionEnvelope, MemoryEvent, ResponseEnvelope, Tip


Responder = Callable[[str, str, str], str]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fallback_responder(message: str, user_context: str, library_context: str, web_context: str = "", secretary_context: str = "") -> str:
    if web_context:
        return f"以下是实时检索到的联网结果：\n\n{web_context}"
    if library_context:
        return f"我在图书馆里找到这些内容：\n\n{library_context}"
    if "【长期用户记忆】" in user_context:
        return f"我会结合你之前留下的偏好继续处理。\n\n当前请求：{message}"
    return f"我已收到：{message}"


def _memory_backend() -> str:
    return (os.getenv("MEMORY_BACKEND") or "local").strip().lower()


def _web_backend() -> str:
    return (os.getenv("WEB_BACKEND") or "local").strip().lower()


class UnifiedAgent:
    def __init__(self, data_dir: str | None = None, responder: Responder | None = None):
        self.data_dir = data_dir
        self._init_memory_backend()
        self.library = LocalLibrary(data_dir)
        self.secretary = SecretaryService(data_dir)
        self.tips = TipEngine()
        self.cognitive = load_cognitive_engine()
        self._init_web_backend()
        self.responder = responder or create_llm_responder(fallback_responder=_fallback_responder)

    def _init_memory_backend(self) -> None:
        backend = _memory_backend()
        if backend == "mcp" and MemoryMcpClient is not None:
            try:
                mcp = MemoryMcpClient()
                self.memory = mcp
                self.personality = mcp
                self.memory_backend = "mcp"
                return
            except Exception:
                pass
        # 回退本地（MCP 未安装或初始化失败）
        self.memory = MemoryService(self.data_dir)
        self.personality = PersonalityService(self.data_dir)
        self.memory_backend = "local"

    def _init_web_backend(self) -> None:
        backend = _web_backend()
        if backend == "mcp" and WebMcpClient is not None:
            try:
                self.web = WebMcpClient()
                self.web_backend = "mcp"
                return
            except Exception:
                pass
        self.web = WebSearchService(self.data_dir)
        self.web_backend = "local"

    def apply_runtime_settings(self) -> dict[str, str]:
        """按最新环境变量热切换 memory/web 后端。"""
        self._init_memory_backend()
        self._init_web_backend()
        return {
            "memory_backend": self.memory_backend,
            "web_backend": self.web_backend,
        }

    def handle_interaction(self, interaction: InteractionEnvelope) -> ResponseEnvelope:
        if not interaction.message:
            raise ValueError("message is required")
        # default 工作区不再全局共享：映射为每用户独立工作区（QQ 群等命名工作区不受影响）
        workspace_id = (interaction.workspace_id or "default").strip() or "default"
        if workspace_id == "default":
            workspace_id = self.secretary.default_project_id(interaction.user_id)
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
        status_change_result: dict | None = None
        # 人格驱动的任务脚手架：低C/拖延者自动重写为可开始的第一步
        task_scaffold = (personality_profile.get("playbook") or {}).get("task_scaffold") or {}
        status_intent = self._looks_like_status_change_intent(interaction.message)
        if self._looks_like_sync(interaction.message):
            draft = self.secretary.draft_sync(workspace_id, interaction.message, interaction.user_id)
            secretary_events.append({"type": "sync_draft", "data": draft})
            requires_confirmation = True
        elif status_intent is not None:
            status_change_result = self._apply_status_change_via_chat(
                workspace_id, interaction.message, status_intent, interaction.user_id
            )
            if status_change_result is not None and status_change_result.get("outcome") == "applied":
                secretary_events.append({"type": "reality_patch", "data": status_change_result["patch"]})
        elif self._looks_like_task(interaction.message):
            title = re.sub(r"^(?:帮我|请)?(?:创建|新增|添加)?(?:一个)?任务[:：]?", "", interaction.message).strip() or interaction.message
            # 初版：对拖延倾向或低尽责，追加脚手架提示到 proposed_change
            work = personality_profile.get("work_style") or {}
            bands = work.get("bands") or {}
            if work.get("execution_style") == "procrastinator" or bands.get("conscientiousness") == "low":
                scaffold_hint = "（助手已按你偏好改写为可开始的第一步：新建文档写3行提纲，25分钟计时）"
                if scaffold_hint not in title:
                    title = f"{title} {scaffold_hint}"
                    # 同时把时间盒写入 evidence 便于审计
                    task_scaffold_text = "；".join(task_scaffold.get("steps") or [])
                    if task_scaffold_text:
                        title += f" | 脚手架：{task_scaffold_text[:80]}"
            patch = self.secretary.create_patch(workspace_id, "task", "new", "create", title, evidence=interaction.message, created_by=interaction.user_id)
            secretary_events.append({"type": "reality_patch", "data": patch})
            # 把脚手架也作为秘书事件，便于前端展示
            if task_scaffold.get("steps"):
                secretary_events.append({"type": "task_scaffold", "data": task_scaffold})
            requires_confirmation = True

        if status_change_result is not None:
            content = status_change_result["content"]
        elif self._looks_like_identity_recall(interaction.message):
            # 身份召回问句与教学语句字面重叠很少，关键词检索常常匹配不到；
            # 直接按置信度取该用户的记忆记录，绕开大模型，避免检索落空或生成阶段编造。
            recall_memories = self.memory.search_user_memory(interaction.user_id, "", limit=6)
            content = self._deterministic_recall_reply(recall_memories)
        elif self._looks_like_forget_recent(interaction.message):
            content = self._forget_recent_reply(interaction.user_id)
        elif self._looks_like_update_memory_request(interaction.message):
            content = (
                "好的，请直接告诉我要更新的内容，例如「我的名字应该是XX」或「我以前喜欢喝茶，"
                "现在喜欢喝咖啡」，我会自动更新对应的长期记忆；你也可以到「记忆与画像」面板里直接编辑或删除某一条。"
            )
        else:
            secretary_context = self._build_secretary_context(secretary_events)
            content = self.responder(interaction.message, user_context, library_context, web_context, secretary_context)
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
        playbook = personality_profile.get("playbook") or {}
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
                "traits": personality_profile.get("traits"),
                "work_style": personality_profile.get("work_style"),
                "playbook": {
                    "headline": playbook.get("headline"),
                    "today_focus": playbook.get("today_focus"),
                    "gaps": playbook.get("gaps"),
                    "strengths": playbook.get("strengths"),
                    "tactics": playbook.get("tactics"),
                    "task_scaffold": playbook.get("task_scaffold"),
                    "collaboration": playbook.get("collaboration"),
                },
                "model": personality_profile.get("model"),
                "samples": personality_profile.get("samples"),
            }},
        )

    def record_interaction(self, user_id: str, message: str, reply: str, source: str = "chat") -> dict:
        return self.memory.record_interaction(user_id, message, reply, source=source)

    def search_user_memory(self, user_id: str, query: str = "", limit: int = 8) -> list[dict]:
        return self.memory.search_user_memory(user_id, query, limit)

    def get_user_profile_stats(self, user_id: str) -> dict:
        return self.memory.get_user_profile_stats(user_id)

    def get_memory_graph(self, user_id: str) -> dict:
        memories = self.memory.search_user_memory(user_id, "", limit=300)
        return build_memory_graph(memories)

    def get_personality_profile(self, user_id: str) -> dict:
        return self.personality.get_profile(user_id)

    def search_user_interactions(self, user_id: str, query: str = "", limit: int = 20, offset: int = 0, from_time: str | None = None, to_time: str | None = None) -> dict:
        """管理员检索用户聊天内容，支持关键词、时间窗与分页"""
        # 复用 memory 的底层存储，兼容 local/mcp
        if hasattr(self.memory, "search_interactions"):
            return self.memory.search_interactions(user_id, query, limit, offset, from_time, to_time)  # type: ignore
        # 本地直连
        from storage.db import get_session
        from storage.models import InteractionRow
        from sqlalchemy import select, and_
        import re
        uid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(user_id or "default").strip())[:80] or "default"
        with get_session(self.data_dir) as session:
            q = select(InteractionRow).where(InteractionRow.user_id == uid)
            if from_time:
                q = q.where(InteractionRow.created_at >= from_time)
            if to_time:
                q = q.where(InteractionRow.created_at <= to_time)
            q = q.order_by(InteractionRow.created_at.desc()).offset(max(0, offset)).limit(max(1, min(limit, 100)))
            rows = session.execute(q).scalars().all()
            # 关键词过滤（内存）
            if query:
                ql = query.lower()
                rows = [r for r in rows if ql in (r.message or "").lower() or ql in (r.reply or "").lower()]
            total_q = select(InteractionRow).where(InteractionRow.user_id == uid)
            total = len(session.execute(total_q).scalars().all())
            return {
                "user_id": uid,
                "interactions": [
                    {"id": r.id, "user_id": r.user_id, "message": r.message, "reply": r.reply, "source": r.source, "created_at": r.created_at}
                    for r in rows
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def delete_interaction(self, interaction_id: str) -> bool:
        if hasattr(self.memory, "delete_interaction"):
            return self.memory.delete_interaction(interaction_id)  # type: ignore
        from storage.db import get_session
        from storage.models import InteractionRow
        from sqlalchemy import delete
        with get_session(self.data_dir) as session:
            res = session.execute(delete(InteractionRow).where(InteractionRow.id == interaction_id))
            session.commit()
            return res.rowcount > 0

    def annotate_interaction(self, user_id: str, interaction_id: str, tag: str = "", note: str = "") -> dict:
        # 复用 feedback 表记录标注
        return self.apply_feedback(user_id, "annotate", memory_id=interaction_id, content=json.dumps({"tag": tag, "note": note}, ensure_ascii=False))

    def apply_feedback(self, user_id: str, feedback_type: str, memory_id: str | None = None, content: str = "") -> dict:
        result = self.memory.apply_feedback(user_id, feedback_type, memory_id, content)
        result["cognitive_delta"] = self.cognitive.score_feedback(result)
        return result

    def forget_memory(self, user_id: str, memory_id: str) -> bool:
        return self.memory.forget_memory(user_id, memory_id)

    def update_memory(self, user_id: str, memory_id: str, content: str) -> dict | None:
        updater = getattr(self.memory, "update_memory", None)
        if not callable(updater):
            return None
        return updater(user_id, memory_id, content)

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

    def llm_info(self) -> dict[str, Any]:
        """暴露 LLM 状态供前端 banner 渲染。"""
        from storage import runtime_settings as _rs
        try:
            raw = _rs.load_raw(self.data_dir)
        except Exception:
            raw = {}
        configured = bool(
            (raw.get("MODEL_API_KEY") or os.getenv("MODEL_API_KEY") or "").strip()
        )
        base = (
            (raw.get("BASE_URL") or os.getenv("BASE_URL") or "https://api.deepseek.com").strip().rstrip("/")
        )
        model = (
            (raw.get("CURRENT_MODEL") or os.getenv("CURRENT_MODEL") or "deepseek-v4-flash").strip()
        )
        return {
            "configured": configured,
            "base_url": base,
            "model": model,
            "mode": "llm" if configured else "fallback",
        }

    def confirm_patch(self, patch_id: str, actor: str) -> dict:
        return self.secretary.confirm_patch(patch_id, actor)

    def rollback_patch(self, patch_id: str, actor: str) -> dict:
        return self.secretary.rollback_patch(patch_id, actor)

    # ------------------------------------------------------------------
    # 数据主权：导出 / 删除
    # ------------------------------------------------------------------

    def export_user_data(self, user_id: str) -> dict[str, Any]:
        """导出单个用户的全部数据为 JSON 友好的字典（不含密钥与他人数据）。"""
        uid = user_id
        payload: dict[str, Any] = {
            "exported_at": _utcnow_iso(),
            "user": {"id": uid},
            "memories": [],
            "interactions": [],
            "feedback": [],
            "personality": {},
            "library": [],
            "secretary": {"tasks": [], "patches": [], "sync_sessions": [], "audits": []},
        }
        try:
            with get_session(self.data_dir) as session:
                mems = session.query(MemoryRow).filter(MemoryRow.user_id == uid).all()
                payload["memories"] = [
                    {
                        "id": m.id,
                        "category": m.category,
                        "content": m.content,
                        "confidence": m.confidence,
                        "source": m.source,
                        "evidence": m.evidence,
                        "occurrence_count": m.occurrence_count,
                        "status": m.status,
                        "created_at": m.created_at,
                        "last_seen_at": m.last_seen_at,
                        "updated_at": m.updated_at,
                    }
                    for m in mems
                ]
                inters = session.query(InteractionRow).filter(InteractionRow.user_id == uid).all()
                payload["interactions"] = [
                    {
                        "id": i.id,
                        "message": i.message,
                        "reply": i.reply,
                        "source": i.source,
                        "created_at": i.created_at,
                    }
                    for i in inters
                ]
                fbs = session.query(FeedbackRow).filter(FeedbackRow.user_id == uid).all()
                payload["feedback"] = [
                    {
                        "id": f.id,
                        "memory_id": f.memory_id,
                        "feedback_type": f.feedback_type,
                        "content": f.content,
                        "created_at": f.created_at,
                    }
                    for f in fbs
                ]
                prof = session.query(PersonalityProfileRow).filter(PersonalityProfileRow.user_id == uid).one_or_none()
                if prof:
                    payload["personality"] = {
                        "scores": json.loads(prof.scores_json or "{}"),
                        "samples": prof.samples,
                        "backend": prof.backend,
                        "updated_at": prof.updated_at,
                    }
                obs = session.query(PersonalityObservationRow).filter(PersonalityObservationRow.user_id == uid).all()
                payload["personality"]["observations"] = [
                    {
                        "id": o.id,
                        "text": o.text,
                        "scores": json.loads(o.scores_json or "{}"),
                        "backend": o.backend,
                        "created_at": o.created_at,
                    }
                    for o in obs
                ]
        except Exception:
            pass
        # 知识库：尝试以 username 命名的子目录导出元数据（不影响正文文件）
        try:
            docs = self.library._load_index()  # noqa: SLF001 - 复用内部索引导出
            for doc in docs:
                tags = doc.get("tags") or []
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
                if uid in tags or f"user:{uid}" in tags or doc.get("owner") == uid:
                    payload["library"].append({
                        "id": doc.get("id"),
                        "filename": doc.get("filename"),
                        "title": doc.get("title"),
                        "tags": tags,
                        "ingested_at": doc.get("ingested_at"),
                        "source": doc.get("source"),
                    })
        except Exception:
            pass
        # 秘书数据：秘书库是 SQLite + 单表结构，没有 user_id 字段；
        # 我们以 owner 字段（创建者 / 操作者）来匹配用户
        try:
            dashboard = self.secretary.dashboard("default")
            uid_lower = uid.lower()
            for task in dashboard.get("tasks", []):
                if (task.get("owner") or "").lower() == uid_lower:
                    payload["secretary"]["tasks"].append(task)
            for patch in dashboard.get("patches", []):
                if (patch.get("created_by") or "").lower() == uid_lower or \
                   (patch.get("confirmed_by") or "").lower() == uid_lower:
                    payload["secretary"]["patches"].append(patch)
            for audit in dashboard.get("audits", []):
                if (audit.get("actor") or "").lower() == uid_lower:
                    payload["secretary"]["audits"].append(audit)
        except Exception:
            pass
        return payload

    def delete_user_data(self, user_id: str, extra_ids: list[str] | None = None) -> dict[str, int]:
        """删除指定用户在集中库、秘书库与知识库中的数据（不删 auth 账号本身）。"""
        uids = [user_id] + [x for x in (extra_ids or []) if x and x != user_id]
        counts = {
            "memories": 0,
            "interactions": 0,
            "feedback": 0,
            "personality_profiles": 0,
            "personality_observations": 0,
            "tasks": 0,
            "patches": 0,
            "audits": 0,
            "projects": 0,
            "documents": 0,
        }
        try:
            with get_session(self.data_dir) as session:
                for uid in uids:
                    counts["memories"] += session.query(MemoryRow).filter(MemoryRow.user_id == uid).delete()
                    counts["interactions"] += session.query(InteractionRow).filter(InteractionRow.user_id == uid).delete()
                    counts["feedback"] += session.query(FeedbackRow).filter(FeedbackRow.user_id == uid).delete()
                    counts["personality_profiles"] += session.query(PersonalityProfileRow).filter(PersonalityProfileRow.user_id == uid).delete()
                    counts["personality_observations"] += session.query(PersonalityObservationRow).filter(PersonalityObservationRow.user_id == uid).delete()
                session.commit()
        except Exception:
            pass
        try:
            for uid in uids:
                sec = self.secretary.delete_user_owned_data(uid)
                for key in ("tasks", "patches", "audits", "projects"):
                    counts[key] += int(sec.get(key) or 0)
        except Exception:
            pass
        try:
            for uid in uids:
                counts["documents"] += int(self.library.delete_documents_for_user(uid) or 0)
        except Exception:
            pass
        return counts

    @staticmethod
    def _build_secretary_context(secretary_events: list[dict]) -> str:
        """把本轮真实发生的秘书动作摘要成一行文本，喂给 LLM，防止它凭空声称"已创建补丁/已同步"等未发生的系统行为。"""
        if not secretary_events:
            return ""
        lines: list[str] = []
        for event in secretary_events:
            etype = event.get("type")
            data = event.get("data") or {}
            if etype == "reality_patch":
                op = data.get("operation")
                pid = data.get("id")
                if op == "create":
                    lines.append(f"已生成补丁 {pid}（新建任务，待用户确认）")
                elif op == "update":
                    lines.append(f"已生成补丁 {pid}（任务状态变更为「{data.get('proposed_change')}」，状态：{data.get('status')}）")
            elif etype == "sync_draft":
                lines.append(f"已生成同步草稿 {data.get('session_id')}，待用户确认")
            elif etype == "task_scaffold":
                lines.append("已生成任务脚手架建议")
        return "；".join(lines)

    @staticmethod
    def _looks_like_library_request(message: str) -> bool:
        return any(word in message for word in ("文档", "资料", "知识", "图书馆", "来源", "引用", "PDF", "文件"))

    @staticmethod
    def _looks_like_sync(message: str) -> bool:
        return any(word in message for word in ("同步任务", "整理进展", "任务进展", "会议纪要", "项目同步"))

    @staticmethod
    def _looks_like_task(message: str) -> bool:
        return bool(re.search(r"(?:创建|新增|添加).{0,8}任务", message))

    _STATUS_LABELS = {"todo": "待办", "in_progress": "进行中", "blocked": "受阻", "done": "完成"}

    _STATUS_CHANGE_WORDS: list[tuple[str, tuple[str, ...]]] = [
        ("done", ("做完了", "完成了", "搞定了", "结束了", "改成完成", "标记为完成", "设为完成", "状态改为完成")),
        ("blocked", ("卡住了", "卡壳了", "受阻了", "遇到问题了", "推不动了", "改成受阻", "标记为受阻", "设为受阻", "状态改为受阻")),
        ("in_progress", ("开始做了", "开始弄了", "在推进", "正在做", "启动了", "改成进行中", "标记为进行中", "设为进行中", "状态改为进行中")),
        ("todo", ("改回待办", "退回待办", "还没开始", "先放一放", "改成待办", "标记为待办", "设为待办", "状态改为待办")),
    ]
    # 弱证据触发词：消息里没有直接点出任务标题原文时，还需要这类词才敢做模糊匹配，避免把"我今天很受阻""搞定了"这种无关闲聊当成指令。
    _STATUS_CHANGE_CUE_RE = re.compile(r"(任务|标记|改成|改为|设为|设成|切换|状态)")
    # 任务脚手架会把提示语拼接在标题后面，比对时要先裁掉，否则用户不会把这段自动生成的文字打出来。
    _TASK_TITLE_SUFFIX_MARKERS = ("（助手已按你偏好改写为", " | 脚手架：")

    @classmethod
    def _looks_like_status_change_intent(cls, message: str) -> str | None:
        """识别消息里是否包含状态变更词（"卡住了""做完了""标记为进行中"等），返回目标状态，不判断是否指向具体任务。"""
        text = (message or "").strip()
        for status, words in cls._STATUS_CHANGE_WORDS:
            if any(word in text for word in words):
                return status
        return None

    @classmethod
    def _task_title_core(cls, title: str) -> str:
        text = str(title or "")
        for marker in cls._TASK_TITLE_SUFFIX_MARKERS:
            idx = text.find(marker)
            if idx != -1:
                text = text[:idx]
        return text.strip()

    def _match_task_by_text(self, tasks: list[dict], text: str) -> list[tuple[int, dict]]:
        """用 jieba 分词做词粒度交集打分，在候选任务标题里找出与消息最相关的任务（与记忆检索同一套思路）。"""
        text_lower = text.lower()
        text_tokens = {t.strip() for t in jieba.lcut(text_lower) if t.strip()}
        scored: list[tuple[int, dict]] = []
        for task in tasks:
            title_lower = self._task_title_core(task.get("title")).lower()
            if not title_lower:
                continue
            title_tokens = {t.strip() for t in jieba.lcut(title_lower) if t.strip()}
            score = 2 * len(text_tokens & title_tokens)
            if score > 0:
                scored.append((score, task))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    def _apply_status_change_via_chat(self, workspace_id: str, message: str, status: str, actor: str) -> dict | None:
        """对话触发的状态切换：定位任务、直接生成并自动确认补丁，返回给用户的提示文案。

        证据分两级：消息里直接出现任务标题原文是强证据，无需额外触发词；
        否则要求出现"任务/标记/改为"等触发词，再做模糊匹配。两者都没有就返回 None，交回普通聊天处理。
        """
        label = self._STATUS_LABELS[status]
        tasks = self.secretary.dashboard(workspace_id).get("tasks") or []
        text_upper = message.upper()
        text_lower = message.lower()
        # 任务 ID（消息里直接带 T-xxxxxxxx）是最强证据，常见于用户按歧义提示回复具体 ID 的场景。
        id_hits = [t for t in tasks if str(t.get("id") or "").upper() in text_upper]
        substring_hits = [t for t in tasks if self._task_title_core(t.get("title")).lower() and self._task_title_core(t.get("title")).lower() in text_lower]
        if id_hits:
            candidates: list[tuple[int, dict]] = [(200, t) for t in id_hits]
        elif substring_hits:
            candidates = [(100, t) for t in substring_hits]
        elif self._STATUS_CHANGE_CUE_RE.search(message):
            candidates = self._match_task_by_text(tasks, message)
        else:
            return None
        if not candidates:
            return {
                "outcome": "no_match",
                "content": f"我没找到看起来匹配的任务，没能把状态切换为「{label}」。你可以到「秘书看板」确认任务标题，或者把任务名说得更具体一点再试一次。",
            }
        top_score = candidates[0][0]
        tied = [task for score, task in candidates if score == top_score]
        if len(tied) > 1:
            names = "、".join(f"「{self._task_title_core(t.get('title'))}」({t.get('id')})" for t in tied[:5])
            return {
                "outcome": "ambiguous",
                "content": f"找到多个可能匹配的任务：{names}。我不确定要把哪个切换为「{label}」，麻烦说得更具体一点（比如带上任务 ID）。",
            }
        task = tied[0]
        title = self._task_title_core(task.get("title"))
        if task.get("status") == status:
            return {
                "outcome": "noop",
                "content": f"任务「{title}」已经是「{label}」状态了，不用改。",
            }
        old_label = self._STATUS_LABELS.get(task.get("status"), task.get("status"))
        patch = self.secretary.create_patch(
            workspace_id, "task", task["id"], "update", status,
            evidence=message, created_by=actor,
        )
        applied = self.confirm_patch(patch["id"], actor)
        return {
            "outcome": "applied",
            "patch": applied,
            "content": (
                f"已把任务「{title}」（{task['id']}）的状态从「{old_label}」切换为「{label}」。"
                f"如果切错了，可以在「秘书看板」的补丁审计流水里找到 {applied['id']}，点「回滚」撤销。"
            ),
        }

    _IDENTITY_RECALL_RE = re.compile(r"(叫什么|我是谁|记得我|我的名字)")

    @classmethod
    def _looks_like_identity_recall(cls, message: str) -> bool:
        """识别"你还记得我叫什么/喜欢什么吗"这类身份召回问句，用于绕开大模型直接从记忆库确定性作答，避免编造。"""
        text = (message or "").strip()
        if not text or not cls._IDENTITY_RECALL_RE.search(text):
            return False
        return text.endswith(("？", "?")) or "吗" in text

    @staticmethod
    def _deterministic_recall_reply(memories: list[dict]) -> str:
        identity = ""
        identity_date = ""
        others: list[str] = []
        for item in memories:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if item.get("category") == "identity" and not identity:
                identity = content
                identity_date = str(item.get("last_seen_at") or "")[:10]
            else:
                others.append(content)
        parts = []
        if identity:
            suffix = f"（{identity_date} 你告诉我的）" if identity_date else ""
            parts.append(f"我记得你叫「{identity}」{suffix}。")
        if others:
            parts.append("另外你还提到过：" + "、".join(others[:4]) + "。")
        if not parts:
            return "抱歉，我目前还没有关于你的相关记忆记录，可以再告诉我一次吗？"
        return "".join(parts)

    _FORGET_RECENT_RE = re.compile(r"(?:忘掉|忘记)(?:我)?(?:刚才|刚刚|上一句|上一条|上次)")
    _UPDATE_MEMORY_RE = re.compile(r"更新(?:一下)?(?:我的)?记忆")

    @classmethod
    def _looks_like_forget_recent(cls, message: str) -> bool:
        """识别"忘掉刚才说的"这类显式遗忘指令，让用户能主动纠正被误记的内容。"""
        return bool(cls._FORGET_RECENT_RE.search(message or ""))

    @classmethod
    def _looks_like_update_memory_request(cls, message: str) -> bool:
        """识别"更新一下我的记忆"这类笼统的更新请求，引导用户用可解析的自然语言表达。"""
        return bool(cls._UPDATE_MEMORY_RE.search(message or "")) and not cls._looks_like_forget_recent(message)

    def _forget_recent_reply(self, user_id: str) -> str:
        prev_messages = self.memory.recent_interactions(user_id, limit=1)
        if not prev_messages:
            return "上一条消息里我没有记录任何长期记忆，无需忘记。"
        finder = getattr(self.memory, "memories_for_evidence", None)
        if not callable(finder):
            return "当前记忆后端暂不支持按上一条消息精确遗忘，你可以到「记忆与画像」面板手动删除对应记忆。"
        candidates = finder(user_id, prev_messages[-1])
        forgotten = sum(1 for m in candidates if self.memory.forget_memory(user_id, m["id"]))
        if forgotten:
            return f"好的，已经把你上一条消息里记录的 {forgotten} 条记忆忘掉了。"
        return "上一条消息里我没有记录任何长期记忆，无需忘记。"
