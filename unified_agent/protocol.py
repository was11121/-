"""渠道无关的统一 Agent 输入输出协议。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class InteractionEnvelope:
    user_id: str
    channel: str
    message: str
    conversation_id: str = "default"
    workspace_id: str = "default"
    attachments: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now)
    permissions: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InteractionEnvelope":
        return cls(
            user_id=str(payload.get("user_id") or payload.get("userId") or "default"),
            channel=str(payload.get("channel") or "web"),
            message=str(payload.get("message") or "").strip(),
            conversation_id=str(payload.get("conversation_id") or payload.get("conversationId") or "default"),
            workspace_id=str(payload.get("workspace_id") or payload.get("workspaceId") or "default"),
            attachments=list(payload.get("attachments") or []),
            timestamp=str(payload.get("timestamp") or utc_now()),
            permissions=list(payload.get("permissions") or []),
            context=dict(payload.get("context") or {}),
        )


@dataclass(slots=True)
class MemoryEvent:
    event_type: str
    memory_id: str | None = None
    content: str = ""
    confidence: float = 0.0
    category: str = ""


@dataclass(slots=True)
class Citation:
    document_id: str
    title: str
    source: str
    locator: str = ""
    snippet: str = ""


@dataclass(slots=True)
class Tip:
    tip_id: str
    type: str
    title: str
    message: str
    alternative_angle: str
    confidence: float
    cooldown_seconds: int = 900
    dismissible: bool = True
    related_memory_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResponseEnvelope:
    content: str = ""
    media: list[dict[str, Any]] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    memory_events: list[MemoryEvent] = field(default_factory=list)
    secretary_events: list[dict[str, Any]] = field(default_factory=list)
    tips: list[Tip] = field(default_factory=list)
    requires_confirmation: bool = False
    audit_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
