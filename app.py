"""现实补丁 Agent 的 Web 和 QQ 统一入口，支持多租户认证与数据隔离。"""
from __future__ import annotations
import functools
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, Response, g, jsonify, request
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from auth_runtime import AuthService
from storage.db import get_database_url
from storage import runtime_settings
from unified_agent import InteractionEnvelope, UnifiedAgent
from secretary_runtime import AdminAuditService
from onboarding_runtime import OnboardingService

# 运行时配置优先于启动 env，支持前端热更新
runtime_settings.apply_to_environ()

app = Flask(__name__, static_folder="static", static_url_path="/static")
agent = UnifiedAgent()
auth_service = AuthService()
admin_audit = AdminAuditService()
onboarding = OnboardingService()


def _utc_filename() -> str:
    """生成文件名安全的时间戳（YYYYMMDDTHHMMSSZ）。"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
    return app.send_static_file("redesign/index.html")


@app.get("/classic")
def classic_index():
    return app.send_static_file("index.html")


@app.get("/health")
def health():
    personality_info = {}
    encoder = getattr(agent.personality, "encoder", None)
    if encoder is not None and hasattr(encoder, "info"):
        personality_info = encoder.info()
    llm_info = {}
    try:
        llm_info = agent.llm_info()
    except Exception as exc:  # noqa: BLE001
        llm_info = {"error": str(exc)}
    return jsonify({
        "status": "ok",
        "service": "remedy-agent",
        "memory": "central-users-db",
        "memory_backend": getattr(agent, "memory_backend", "local"),
        "web_backend": getattr(agent, "web_backend", "local"),
        "auth": "active",
        "database": get_database_url(None).split(":")[0].split("+")[0],
        "cognitive_engine": type(agent.cognitive).__name__,
        "personality": personality_info,
        "llm": llm_info,
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
@app.post("/v1/auth/guest")
def auth_guest():
    """访客按设备 ID 免注册登录：同一设备映射同一 guest 账号，数据按设备隔离。"""
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or payload.get("deviceId") or "")
    try:
        res = auth_service.guest_login(device_id)
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


@app.get("/v1/me/export")
@require_auth
def me_export():
    """导出当前登录用户的全部数据（JSON）。"""
    user = g.current_user
    payload = agent.export_user_data(user["username"])
    payload["user"] = {
        "id": user["id"],
        "username": user["username"],
        "nickname": user.get("nickname"),
        "role": user.get("role"),
        "created_at": user.get("created_at"),
    }
    # 仅追加 1 条审计记录，便于用户回溯自己何时导出过
    try:
        admin_audit.record(
            actor=user["username"],
            action="self_export",
            target_user=user["username"],
            detail={"payload_size_kb": round(len(json.dumps(payload, ensure_ascii=False)) / 1024, 1)},
            ip=request.remote_addr or "",
        )
    except Exception:
        pass
    response = jsonify(payload)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="remedy_export_{user["username"]}_{_utc_filename()}.json"'
    )
    return response


# ----------------------------------------------------------------------
# Demo Workspace 路由 (Sprint 1.1 / 1.2)
# ----------------------------------------------------------------------

@app.get("/v1/me/onboarding")
@require_auth
def me_onboarding_status():
    """查看当前用户的引导状态：是否已注入 demo 等。"""
    user = g.current_user
    username = user["username"]
    return jsonify({
        "demo_seeded": onboarding.is_demo_seeded(username),
        "user": {"username": username},
    })


@app.post("/v1/me/onboarding/seed-demo")
@require_auth
def me_onboarding_seed_demo():
    """为当前用户注入 demo 数据。幂等：已注入则直接返回现状。"""
    user = g.current_user
    username = user["username"]
    if onboarding.is_demo_seeded(username):
        return jsonify({"success": True, "already_seeded": True})
    try:
        summary = onboarding.seed_demo(username, agent=agent)
        return jsonify({"success": True, "summary": summary})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("seed_demo failed")
        return jsonify({"error": str(exc)}), 500


@app.post("/v1/me/onboarding/clear-demo")
@require_auth
def me_onboarding_clear_demo():
    """清空当前用户的 demo 数据（双重确认由前端 modal 实现）。"""
    user = g.current_user
    username = user["username"]
    if not onboarding.is_demo_seeded(username):
        return jsonify({"success": True, "already_cleared": True})
    try:
        counts = onboarding.clear_demo(username, agent=agent, auth_service=auth_service)
        return jsonify({"success": True, "counts": counts})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("clear_demo failed")
        return jsonify({"error": str(exc)}), 500


@app.delete("/v1/me")
@require_auth
def me_delete():
    """永久删除当前登录用户及其全部数据（双重确认由前端实现）。"""
    user = g.current_user
    username = user["username"]
    try:
        # 先清理 demo 与全部数据
        try:
            onboarding.clear_demo(username, agent=agent, auth_service=auth_service)
        except Exception:
            pass
        counts = agent.delete_user_data(username, extra_ids=[user.get("id")])
        deleted = auth_service.delete_user(user["id"])
    except ValueError as exc:
        return jsonify({"error": str(exc), "code": "FORBIDDEN"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if not deleted:
        return jsonify({"error": "账号不存在或已删除"}), 404
    return jsonify({"success": True, "username": username, "data_counts": counts})
# ----------------------------------------------------------------------
# 管理员专属接口 (Admin Routes - 个人画像穿透与统计)
# ----------------------------------------------------------------------
@app.get("/v1/admin/users")
@require_admin
def admin_list_users():
    """获取所有已注册用户列表及其个人画像统计概览（含人格雷达）"""
    users = auth_service.list_all_users()
    enriched = []
    for u in users:
        stats = agent.get_user_profile_stats(u["username"])
        stats_by_id = agent.get_user_profile_stats(u["id"])
        # 合并统计
        total_m = stats["total_memories"] + stats_by_id["total_memories"]
        total_i = stats["total_interactions"] + stats_by_id["total_interactions"]
        merged_cats = {**stats.get("categories", {}), **stats_by_id.get("categories", {})}
        # 人格雷达（供管理台直接渲染）
        try:
            prof = agent.get_personality_profile(u["username"])
            scores = prof.get("scores") or {}
            work = prof.get("work_style") or {}
        except Exception:
            scores, work = {}, {}
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
            },
            "personality": {
                "scores": scores,
                "work_style": work,
                "samples": prof.get("samples", 0) if 'prof' in locals() else 0,
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
    admin_audit.record(
        actor=g.current_user["username"],
        action="view_profile",
        target_user=target_user,
        target_id=target_user,
        detail={"memories_count": len(memories)},
        ip=request.remote_addr or "",
    )
    return jsonify({
        "target_user": target_user,
        "user_info": user_info,
        "stats": stats,
        "memories": memories,
        "personality": agent.get_personality_profile(target_user),
    })


@app.get("/v1/admin/settings")
@require_auth
def admin_get_settings():
    """读取当前生效的服务配置（密钥脱敏）。"""
    settings = runtime_settings.effective()
    web_info = {}
    try:
        web_info = agent.web_info()
    except Exception as exc:  # noqa: BLE001
        web_info = {"error": str(exc)}
    return jsonify({
        "settings": settings,
        "runtime": {
            "memory_backend": getattr(agent, "memory_backend", "local"),
            "web_backend": getattr(agent, "web_backend", "local"),
            "web_info": web_info,
        },
    })


@app.put("/v1/admin/settings")
@require_auth
def admin_put_settings():
    """保存服务配置并立即热更新生效。"""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "body must be an object"}), 400
    runtime_settings.save_raw(payload)
    runtime_settings.apply_to_environ()
    applied = agent.apply_runtime_settings()
    return jsonify({
        "success": True,
        "applied": applied,
        "settings": runtime_settings.effective(),
    })


@app.post("/v1/admin/settings/test")
@require_auth
def admin_test_settings():
    """测试指定服务连通性（不强制持久化）。"""
    import urllib.error
    import urllib.request

    payload = request.get_json(silent=True) or {}
    target = str(payload.get("target") or "").strip().lower()
    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}

    def _val(key: str, default: str = "") -> str:
        if key in overrides and str(overrides.get(key) or "").strip() != "":
            return str(overrides.get(key)).strip()
        raw = runtime_settings.load_raw()
        if key in raw and str(raw.get(key) or "").strip() != "":
            return str(raw.get(key)).strip()
        return os.getenv(key, default).strip()

    try:
        if target == "llm":
            base = _val("BASE_URL", "https://api.deepseek.com").rstrip("/")
            key = _val("MODEL_API_KEY")
            model = _val("CURRENT_MODEL", "deepseek-v4-flash")
            if not key:
                return jsonify({"ok": False, "target": target, "error": "MODEL_API_KEY 未配置"}), 400
            endpoint = f"{base}/v1/chat/completions" if not base.endswith("/v1") else f"{base}/chat/completions"
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
            }).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return jsonify({"ok": True, "target": target, "status": resp.status})

        if target == "memory_mcp":
            url = _val("MEMORY_MCP_URL", "http://127.0.0.1:8092").rstrip("/") + "/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return jsonify({"ok": True, "target": target, "result": data})

        if target == "web_mcp":
            url = _val("WEB_MCP_URL", "http://127.0.0.1:8093").rstrip("/") + "/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return jsonify({"ok": True, "target": target, "result": data})

        if target == "searxng":
            searx = _val("SEARXNG_URL", "http://localhost:8080/search")
            sep = "&" if "?" in searx else "?"
            url = f"{searx}{sep}q=ping&format=json"
            req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return jsonify({"ok": True, "target": target, "status": resp.status})

        if target == "tavily":
            key = _val("TAVILY_API_KEY")
            if not key:
                return jsonify({"ok": False, "target": target, "error": "TAVILY_API_KEY 未配置"}), 400
            body = json.dumps({"api_key": key, "query": "ping", "max_results": 1}).encode("utf-8")
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return jsonify({"ok": True, "target": target, "status": resp.status})

        if target == "jina":
            base = _val("JINA_READER_URL", "https://r.jina.ai").rstrip("/")
            url = f"{base}/https://example.com"
            req = urllib.request.Request(url, method="GET", headers={"Accept": "text/plain"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", errors="replace")[:200]
                return jsonify({"ok": True, "target": target, "status": resp.status, "preview": text})

        return jsonify({"ok": False, "error": f"unsupported target: {target}"}), 400
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return jsonify({"ok": False, "target": target, "status": exc.code, "error": detail}), 200
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "target": target, "error": str(exc)}), 200


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
@require_auth
def user_memory(user_id: str):
    """查询指定用户记忆。普通用户只能查询自己；管理员可查询任意用户。"""
    user = g.current_user
    if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
        return jsonify({"error": "无权查看其他用户的记忆画像", "code": "FORBIDDEN"}), 403
    return jsonify({"user_id": user_id, "memories": agent.search_user_memory(user_id, request.args.get("q", ""), int(request.args.get("limit", 20)))})


@app.get("/v1/users/<user_id>/personality")
@require_auth
def user_personality(user_id: str):
    """查询用户大五人格督促档案。普通用户只能查自己；管理员可查任意用户。"""
    user = g.current_user
    if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
        return jsonify({"error": "无权查看其他用户的人格档案", "code": "FORBIDDEN"}), 403
    return jsonify(agent.get_personality_profile(user_id))


@app.post("/v1/users/<user_id>/memory/<memory_id>/forget")
@require_auth
def forget_memory(user_id: str, memory_id: str):
    user = g.current_user
    if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
        return jsonify({"error": "无权操作其他用户的记忆", "code": "FORBIDDEN"}), 403
    return jsonify({"success": agent.forget_memory(user_id, memory_id)})


@app.patch("/v1/users/<user_id>/memory/<memory_id>")
@require_auth
def edit_memory(user_id: str, memory_id: str):
    """允许用户在「记忆与画像」面板直接编辑/纠正一条记忆内容。"""
    user = g.current_user
    if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
        return jsonify({"error": "无权操作其他用户的记忆", "code": "FORBIDDEN"}), 403
    body = request.get_json(silent=True) or {}
    content = str(body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content 不能为空", "code": "INVALID_INPUT"}), 400
    updated = agent.update_memory(user_id, memory_id, content)
    if not updated:
        return jsonify({"error": "记忆不存在或已被遗忘", "code": "NOT_FOUND"}), 404
    return jsonify({"memory": updated})


@app.get("/v1/users/<user_id>/memory/graph")
@require_auth
def user_memory_graph(user_id: str):
    """返回当前用户记忆的图结构（节点=记忆，边=共享证据链/同类目），供 3D 记忆图谱渲染。"""
    user = g.current_user
    if user["role"] != "admin" and user["username"] != user_id and user["id"] != user_id:
        return jsonify({"error": "无权查看其他用户的记忆图谱", "code": "FORBIDDEN"}), 403
    return jsonify({"user_id": user_id, **agent.get_memory_graph(user_id)})


@app.get("/v1/admin/users/<user_id>/interactions")
@require_admin
def admin_user_interactions(user_id: str):
    """管理员查询指定用户聊天内容，支持关键词、时间窗与分页，可删除/标注"""
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))
    from_time = request.args.get("from")
    to_time = request.args.get("to")
    try:
        result = agent.search_user_interactions(user_id, query=q, limit=limit, offset=offset, from_time=from_time, to_time=to_time)
        admin_audit.record(
            actor=g.current_user["username"],
            action="search_interactions",
            target_user=user_id,
            detail={"q": q, "limit": limit, "offset": offset, "from": from_time, "to": to_time, "total": result.get("total", 0)},
            ip=request.remote_addr or "",
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.delete("/v1/admin/interactions/<interaction_id>")
@require_admin
def admin_delete_interaction(interaction_id: str):
    try:
        ok = agent.delete_interaction(interaction_id)
        admin_audit.record(
            actor=g.current_user["username"],
            action="delete_interaction",
            target_user="",
            target_id=interaction_id,
            detail={"ok": ok},
            ip=request.remote_addr or "",
        )
        return jsonify({"success": ok})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/v1/admin/interactions/<interaction_id>/annotate")
@require_admin
def admin_annotate_interaction(interaction_id: str):
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    # 标注需关联用户，优先取 payload 中的 user_id，否则取当前 admin 自身
    target_user = str(payload.get("user_id") or payload.get("target_user") or g.current_user.get("username") or "admin")
    tag = str(payload.get("tag") or "")
    note = str(payload.get("note") or payload.get("content") or "")
    try:
        res = agent.annotate_interaction(target_user, interaction_id, tag=tag, note=note)
        admin_audit.record(
            actor=g.current_user["username"],
            action="annotate_interaction",
            target_user=target_user,
            target_id=interaction_id,
            detail={"tag": tag, "note_len": len(note)},
            ip=request.remote_addr or "",
        )
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/v1/admin/audit")
@require_admin
def admin_audit_list():
    """查询管理员审计日志（仅管理员可读）。"""
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    actor = request.args.get("actor", "")
    action = request.args.get("action", "")
    target_user = request.args.get("target_user", "")
    return jsonify(admin_audit.list_events(
        limit=min(limit, 200),
        offset=max(offset, 0),
        actor=actor,
        action=action,
        target_user=target_user,
    ))
# ----------------------------------------------------------------------
# 知识库与项目秘书相关接口
# ----------------------------------------------------------------------
@app.post("/v1/library/documents")
def library_documents():
    upload = request.files.get("file")
    current = get_current_user()
    owner_tag = f"user:{current['username']}" if current else None
    if upload:
        try:
            tags = [owner_tag] if owner_tag else None
            return jsonify(agent.ingest_document(upload.filename or "uploaded_file", upload.read(), source=request.form.get("source", "upload"), tags=tags))
        except (ValueError, RuntimeError, Exception) as exc:
            return jsonify({"error": str(exc)}), 400
    payload = request.get_json(silent=True) or {}
    try:
        content = payload.get("content", "")
        tags = list(payload.get("tags") or [])
        if owner_tag and owner_tag not in tags:
            tags.append(owner_tag)
        return jsonify(agent.ingest_document(str(payload.get("filename") or "document.txt"), content, source=str(payload.get("source") or "api"), tags=tags or None))
    except (ValueError, RuntimeError, Exception) as exc:
        return jsonify({"error": str(exc)}), 400
@app.get("/v1/library/documents")
def library_list():
    current = get_current_user()
    if current and current.get("role") != "admin":
        records = agent.library.documents_for_user(current["username"], include_untagged=False)
        extra = agent.library.documents_for_user(current.get("id") or "", include_untagged=False)
        seen = {r.get("document_id") for r in records}
        for item in extra:
            if item.get("document_id") not in seen:
                records.append(item)
    else:
        records = agent.library._load_index()
    return jsonify({"documents": records})
@app.get("/v1/library/search")
def library_search():
    return jsonify({"results": agent.search_library(request.args.get("q", ""), int(request.args.get("limit", 10)))})


# ----------------------------------------------------------------------
# 联网搜索与网页读取接口
# ----------------------------------------------------------------------

@app.get("/v1/web/info")
@require_admin
def web_info():
    """联网通道状态（仅管理员；返回脱敏信息，不含上游地址）。"""
    return jsonify(agent.web_info())


# 对外隐藏上游通道名：把 searxng/tavily/jina 等具体服务名映射为中性标签，
# 用户通过任何接口都看不到服务器使用的具体上游服务。
_CHANNEL_LABELS = {
    "searxng": "本地引擎",
    "tavily": "在线引擎",
    "tavily-relay": "中转引擎",
    "none": "none",
}
_VIA_LABELS = {
    "jina-direct": "网页解析",
    "jina-relay": "网页解析(中转)",
    "none": "none",
}


def _sanitize_web_payload(payload: dict) -> dict:
    """把搜索/读页响应里的通道标识中性化，防止暴露上游服务名。"""
    out = dict(payload or {})
    if "channel" in out:
        raw = str(out["channel"] or "").strip()
        out["channel"] = _CHANNEL_LABELS.get(raw, raw)
    if "via" in out:
        raw = str(out["via"] or "").strip()
        out["via"] = _VIA_LABELS.get(raw, raw or "网页解析")
    return out


@app.post("/v1/web/search")
def web_search_endpoint():
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query") or "")
    if not query:
        return jsonify({"error": "query is required"}), 400
    limit = int(payload.get("limit") or 5)
    try:
        result = agent.web_search(query, limit=limit)
        return jsonify(_sanitize_web_payload(result))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/v1/web/fetch")
def web_fetch_endpoint():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url") or "")
    if not url:
        return jsonify({"error": "url is required"}), 400
    try:
        result = agent.web_fetch(url)
        return jsonify(_sanitize_web_payload(result))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _can_access_workspace(workspace_id: str, username: str, role: str) -> bool:
    """工作区访问判定：管理员放行（便于穿透审计），其余按 owner 规则。"""
    if role == "admin":
        return True
    return agent.secretary.can_access_project(workspace_id, username)


def _resolve_user_workspace(workspace_id: str) -> str:
    """把前端传入的 default 解析为当前用户的独立工作区（default::<username>）。"""
    username = g.current_user["username"]
    ws = (workspace_id or "default").strip() or "default"
    if ws == "default":
        ws = agent.secretary.default_project_id(username)
    agent.secretary.ensure_project(ws, name="我的工作区", owner_user_id=username)
    return ws


@app.post("/v1/sync/<session_id>/confirm")
@require_auth
def sync_confirm(session_id: str):
    username = g.current_user["username"]
    role = g.current_user.get("role", "user")
    project_id = agent.secretary.get_sync_session_project(session_id)
    if project_id is not None and not _can_access_workspace(project_id, username, role):
        return jsonify({"error": "无权确认该同步草稿", "code": "FORBIDDEN"}), 403
    try:
        return jsonify(agent.secretary.confirm_sync(session_id, username))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
@app.post("/v1/workspaces/<workspace_id>/sync")
@require_auth
def workspace_sync(workspace_id: str):
    username = g.current_user["username"]
    role = g.current_user.get("role", "user")
    ws = _resolve_user_workspace(workspace_id)
    if not _can_access_workspace(ws, username, role):
        return jsonify({"error": "无权访问该工作区", "code": "FORBIDDEN"}), 403
    payload = request.get_json(silent=True) or {}
    draft = agent.secretary.draft_sync(ws, str(payload.get("text") or ""), username)
    return jsonify(draft)
@app.get("/v1/workspaces/<workspace_id>/dashboard")
@require_auth
def workspace_dashboard(workspace_id: str):
    username = g.current_user["username"]
    role = g.current_user.get("role", "user")
    ws = _resolve_user_workspace(workspace_id)
    if not _can_access_workspace(ws, username, role):
        return jsonify({"error": "无权访问该工作区", "code": "FORBIDDEN"}), 403
    return jsonify(agent.secretary.dashboard(ws))


# --- Sprint 2.5: 多工作区列表 / 创建 ---
@app.get("/v1/workspaces")
@require_auth
def workspaces_list():
    """列出当前用户可见的工作区（本人拥有的 + 遗留无主命名工作区）。首次访问时会惰性创建本人 default。"""
    username = g.current_user["username"]
    agent.secretary.ensure_project(
        agent.secretary.default_project_id(username), name="我的工作区", owner_user_id=username
    )
    return jsonify({"workspaces": agent.secretary.list_projects_for_user(username)})


@app.post("/v1/workspaces")
@require_auth
def workspaces_create():
    """新建工作区，自动绑定到当前用户。"""
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) > 80:
        return jsonify({"error": "name too long (max 80 chars)"}), 400
    try:
        ws = agent.secretary.create_project(name, g.current_user["username"])
        return jsonify({"success": True, "workspace": ws})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
def _can_touch_patch(patch: dict | None, username: str, role: str) -> tuple[bool, str]:
    """补丁操作归属校验：创建者本人或管理员可操作；工作区访问规则同时生效。"""
    if patch is None:
        return True, ""
    if role == "admin":
        return True, ""
    if str(patch.get("created_by") or "").strip().lower() != username.strip().lower():
        return False, "只能操作自己创建的补丁"
    if not _can_access_workspace(str(patch.get("project_id") or ""), username, role):
        return False, "无权操作该补丁"
    return True, ""

@app.post("/v1/workspaces/<workspace_id>/tasks/<task_id>/status")
@require_auth
def task_update_status(workspace_id: str, task_id: str):
    """看板手动切换任务状态：走 RealityPatch 状态机，创建后立即自动确认，保留可回滚的审计记录。"""
    username = g.current_user["username"]
    role = g.current_user.get("role", "user")
    ws = _resolve_user_workspace(workspace_id)
    if not _can_access_workspace(ws, username, role):
        return jsonify({"error": "无权访问该工作区", "code": "FORBIDDEN"}), 403
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip()
    if status not in ("todo", "in_progress", "blocked", "done"):
        return jsonify({"error": "status must be one of todo/in_progress/blocked/done"}), 400
    patch = agent.secretary.create_patch(
        ws, "task", task_id, "update", status, evidence="看板手动切换状态", created_by=username
    )
    try:
        return jsonify(agent.confirm_patch(patch["id"], username))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409


@app.post("/v1/patches/<patch_id>/confirm")
@require_auth
def patch_confirm(patch_id: str):
    username = g.current_user["username"]
    role = g.current_user.get("role", "user")
    ok, reason = _can_touch_patch(agent.secretary.get_patch(patch_id), username, role)
    if not ok:
        return jsonify({"error": reason, "code": "FORBIDDEN"}), 403
    try:
        return jsonify(agent.confirm_patch(patch_id, username))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
@app.post("/v1/patches/<patch_id>/rollback")
@require_auth
def patch_rollback(patch_id: str):
    username = g.current_user["username"]
    role = g.current_user.get("role", "user")
    ok, reason = _can_touch_patch(agent.secretary.get_patch(patch_id), username, role)
    if not ok:
        return jsonify({"error": reason, "code": "FORBIDDEN"}), 403
    try:
        return jsonify(agent.rollback_patch(patch_id, username))
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

@app.get("/redesign")
def redesign_index():
    return app.send_static_file("redesign/index.html")


@app.get("/admin")
def admin_console():
    # 前端自行通过 /v1/auth/me 校验 remedy_admin，否则跳登录；直接返回静态页
    return app.send_static_file("redesign/admin.html")

if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8091")), debug=False)
