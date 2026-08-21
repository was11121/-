"""现实补丁 Agent 的 Web 和 QQ 统一入口，支持多租户认证与数据隔离。"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path

from flask import Flask, Response, g, jsonify, request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from auth_runtime import AuthService
from unified_agent import InteractionEnvelope, UnifiedAgent

app = Flask(__name__, static_folder="static", static_url_path="/static")
agent = UnifiedAgent()
auth_service = AuthService()


def get_current_user() -> dict | None:
    """从请求头 Authorization: Bearer <token> 或 query 中解析当前登录用户。"""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "token" in request.args:
        token = request.args.get("token", "").strip()
    if not token:
        return None
    return auth_service.verify_token(token)


def require_auth(f):
    """验证用户已登录。"""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "未登录或登录已过期，请重新登录", "code": "UNAUTHORIZED"}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    """验证当前用户具有管理员权限。"""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "未登录或登录已过期，请重新登录", "code": "UNAUTHORIZED"}), 401
        if user.get("role") != "admin":
            return jsonify({"error": "权限不足，仅管理员可访问此功能", "code": "FORBIDDEN"}), 403
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


# ----------------------------------------------------------------------
# 静态资源与系统接口
# ----------------------------------------------------------------------

@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "reality-patch-agent",
        "memory": "local-isolated",
        "auth": "active",
        "cognitive_engine": type(agent.cognitive).__name__,
        "personality": agent.personality.encoder.info(),
    })


# ----------------------------------------------------------------------
# 认证与用户接口 (Auth Routes)
# ----------------------------------------------------------------------

@app.post("/v1/auth/register")
def auth_register():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    nickname = str(payload.get("nickname") or "")
    try:
        user = auth_service.register(username, password, role="user", nickname=nickname)
        return jsonify({"success": True, "user": user})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/v1/auth/login")
def auth_login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    try:
        res = auth_service.login(username, password)
        return jsonify(res)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/v1/auth/me")
@require_auth
def auth_me():
    return jsonify({"user": g.current_user})


@app.post("/v1/auth/logout")
def auth_logout():
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if token:
        auth_service.logout(token)
    return jsonify({"success": True})


# ----------------------------------------------------------------------
# 管理员专属接口 (Admin Routes - 个人画像穿透与统计)
# ----------------------------------------------------------------------

@app.get("/v1/admin/users")
@require_admin
def admin_list_users():
    """获取所有已注册用户列表及其个人画像统计概览。"""
    users = auth_service.list_all_users()
    enriched = []
    for u in users:
        stats = agent.get_user_profile_stats(u["username"])
        stats_by_id = agent.get_user_profile_stats(u["id"])
        # 合并统计
        total_m = stats["total_memories"] + stats_by_id["total_memories"]
        total_i = stats["total_interactions"] + stats_by_id["total_interactions"]
        merged_cats = {**stats.get("categories", {}), **stats_by_id.get("categories", {})}
        enriched.append({
            "id": u["id"],
            "username": u["username"],
            "nickname": u["nickname"],
            "role": u["role"],
            "created_at": u["created_at"],
            "stats": {
                "total_memories": total_m,
                "total_interactions": total_i,
                "categories": merged_cats,
            }
        })
    return jsonify({"users": enriched})


@app.get("/v1/admin/users/<target_user>/profile")
@require_admin
def admin_user_profile(target_user: str):
    """管理员查看指定用户的完整长期记忆与画像详情。"""
    memories = agent.search_user_memory(target_user, query="", limit=100)
    stats = agent.get_user_profile_stats(target_user)
    user_info = auth_service.get_user_by_id(target_user)
    if not user_info:
        # 如果传入的是 username，尝试从全量中查找
        for u in auth_service.list_all_users():
            if u["username"] == target_user:
                user_info = u
                break
    return jsonify({
        "target_user": target_user,
        "user_info": user_info,
        "stats": stats,
        "memories": memories,
        "personality": agent.get_personality_profile(target_user),
    })


# ----------------------------------------------------------------------
# 智能交互与记忆操作 (支持用户身份严格绑定与普通用户隔离)
# ----------------------------------------------------------------------

@app.post("/v1/interactions")
def interactions():
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    envelope = InteractionEnvelope.from_dict(payload)
    # 如果已登录，强制将 user_id 锁定为当前登录用户的真实 username / id，防止越权篡改他人记忆
    if user:
        envelope.user_id = user["username"]
    try:
        result = agent.handle_interaction(envelope)
        return jsonify(result.to_dict())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("interaction failed")
        return jsonify({"error": str(exc)}), 500


@app.post("/v1/interactions/stream")
def interactions_stream():
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    envelope = InteractionEnvelope.from_dict(payload)
    if user:
        envelope.user_id = user["username"]

    def generate():
        try:
            result = agent.handle_interaction(envelope)
            yield "data: " + json.dumps({"type": "response", "data": result.to_dict()}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"type": "done"}, ensure_ascii=False) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "data": str(exc)}, ensure_ascii=False) + "\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.post("/v1/feedback")
def feedback():
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    user_id = user["username"] if user else str(payload.get("user_id") or "default")
    try:
        return jsonify(agent.apply_feedback(user_id, str(payload.get("feedback_type") or ""), payload.get("memory_id"), str(payload.get("content") or "")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/v1/users/<user_id>/memory")
def user_memory(user_id: str):
    """查询指定用户记忆。普通用户只能查询自己；管理员可查询任意用户。"""
    user = get_current_user()
    if user:
        # 普通用户越权访问他人记忆拦截
        if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
            return jsonify({"error": "无权查看其他用户的记忆画像", "code": "FORBIDDEN"}), 403
    return jsonify({"user_id": user_id, "memories": agent.search_user_memory(user_id, request.args.get("q", ""), int(request.args.get("limit", 20)))})


@app.get("/v1/users/<user_id>/personality")
def user_personality(user_id: str):
    """查询用户大五人格督促档案。普通用户只能查自己；管理员可查任意用户。"""
    user = get_current_user()
    if user:
        if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
            return jsonify({"error": "无权查看其他用户的人格档案", "code": "FORBIDDEN"}), 403
    return jsonify(agent.get_personality_profile(user_id))


@app.post("/v1/users/<user_id>/memory/<memory_id>/forget")
def forget_memory(user_id: str, memory_id: str):
    user = get_current_user()
    if user:
        if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
            return jsonify({"error": "无权操作其他用户的记忆", "code": "FORBIDDEN"}), 403
    return jsonify({"success": agent.forget_memory(user_id, memory_id)})


# ----------------------------------------------------------------------
# 知识库与项目秘书相关接口
# ----------------------------------------------------------------------

@app.post("/v1/library/documents")
def library_documents():
    upload = request.files.get("file")
    if upload:
        try:
            return jsonify(agent.ingest_document(upload.filename or "uploaded_file", upload.read(), source=request.form.get("source", "upload")))
        except (ValueError, RuntimeError, Exception) as exc:
            return jsonify({"error": str(exc)}), 400
    payload = request.get_json(silent=True) or {}
    try:
        content = payload.get("content", "")
        return jsonify(agent.ingest_document(str(payload.get("filename") or "document.txt"), content, source=str(payload.get("source") or "api"), tags=payload.get("tags")))
    except (ValueError, RuntimeError, Exception) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/v1/library/documents")
def library_list():
    records = agent.library._load_index()
    return jsonify({"documents": records})


@app.get("/v1/library/search")
def library_search():
    return jsonify({"results": agent.search_library(request.args.get("q", ""), int(request.args.get("limit", 10)))})


@app.post("/v1/sync/<session_id>/confirm")
def sync_confirm(session_id: str):
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    actor = user["username"] if user else str(payload.get("actor") or "default")
    try:
        return jsonify(agent.secretary.confirm_sync(session_id, actor))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409


@app.post("/v1/workspaces/<workspace_id>/sync")
def workspace_sync(workspace_id: str):
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    actor = user["username"] if user else str(payload.get("actor") or "agent")
    draft = agent.secretary.draft_sync(workspace_id, str(payload.get("text") or ""), actor)
    return jsonify(draft)


@app.get("/v1/workspaces/<workspace_id>/dashboard")
def workspace_dashboard(workspace_id: str):
    return jsonify(agent.secretary.dashboard(workspace_id))


@app.post("/v1/patches/<patch_id>/confirm")
def patch_confirm(patch_id: str):
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    actor = user["username"] if user else str(payload.get("actor") or "default")
    try:
        return jsonify(agent.confirm_patch(patch_id, actor))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409


@app.post("/v1/patches/<patch_id>/rollback")
def patch_rollback(patch_id: str):
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    actor = user["username"] if user else str(payload.get("actor") or "default")
    try:
        return jsonify(agent.rollback_patch(patch_id, actor))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409


@app.post("/qq")
def qq_webhook():
    payload = request.get_json(silent=True) or {}
    if payload.get("post_type") != "message":
        return jsonify({"status": "ignored"})
    user_id = str(payload.get("user_id") or "default")
    group_id = str(payload.get("group_id") or "private")
    message = str(payload.get("raw_message") or payload.get("message") or "")
    result = agent.handle_interaction(InteractionEnvelope(user_id=user_id, channel="qq", conversation_id=group_id, workspace_id=group_id, message=message))
    return jsonify({"status": "ok", "reply": result.to_dict()})


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8091")), debug=False)
