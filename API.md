# Remedy API 接口规范文档

本文档定义了 **Remedy（现实补丁智能体）** 的统一交互协议、REST API、SSE 流式接口及 Webhook 规范。

---

## 目录
1. [系统总览与架构理念](#1-系统总览与架构理念)
2. [统一数据协议 (Envelope & Objects)](#2-统一数据协议-envelope--objects)
3. [核心接口列表](#3-核心接口列表)
   - [3.1 系统健康检查 `/health`](#31-系统健康检查-health)
   - [3.2 统一智能交互 (同步) `/v1/interactions`](#32-统一智能交互-同步-v1interactions)
   - [3.3 统一智能交互 (SSE流式) `/v1/interactions/stream`](#33-统一智能交互-sse流式-v1interactionsstream)
   - [3.4 用户记忆查询 `/v1/users/{user_id}/memory`](#34-用户记忆查询-v1usersuser_idmemory)
   - [3.5 记忆反馈与认知打分 `/v1/feedback`](#35-记忆反馈与认知打分-v1feedback)
   - [3.6 彻底遗忘记忆 `/v1/users/{user_id}/memory/{memory_id}/forget`](#36-彻底遗忘记忆-v1usersuser_idmemorymemory_idforget)
   - [3.7 知识库文档录入 `/v1/library/documents`](#37-知识库文档录入-v1librarydocuments)
   - [3.8 知识库列表查询 `/v1/library/documents`](#38-知识库列表查询-v1librarydocuments)
   - [3.9 权威知识库检索 `/v1/library/search`](#39-权威知识库检索-v1librarysearch)
   - [3.10 工作区进展同步草稿 `/v1/workspaces/{workspace_id}/sync`](#310-工作区进展同步草稿-v1workspacesworkspace_idsync)
   - [3.11 确认同步草稿 `/v1/sync/{session_id}/confirm`](#311-确认同步草稿-v1syncsession_idconfirm)
   - [3.12 工作区看板数据 `/v1/workspaces/{workspace_id}/dashboard`](#312-工作区看板数据-v1workspacesworkspace_iddashboard)
   - [3.13 现实补丁确认与应用 `/v1/patches/{patch_id}/confirm`](#313-现实补丁确认与应用-v1patchespatch_idconfirm)
   - [3.14 现实补丁回滚 `/v1/patches/{patch_id}/rollback`](#314-现实补丁回滚-v1patchespatch_idrollback)
   - [3.15 QQ OneBot Webhook `/qq`](#315-qq-onebot-webhook-qq)
   - [3.16 认证与权限接口](#316-认证与权限接口)
   - [3.17 管理员专属画像分析接口](#317-管理员专属画像分析接口)
4. [错误码与异常处理规范](#4-错误码与异常处理规范)
5. [权限模型](#5-权限模型)

---

## 1. 系统总览与架构理念

Remedy 采用多子系统协同的架构设计：
- **Auth Runtime**：独立 `data/auth.sqlite3` 账户与令牌库；角色分为 `admin` / `user`。
- **Memory Runtime**：用户级 SQLite 物理隔离记忆库（`data/users/<user_id>/memory.sqlite3`），自动提取偏好、身份、指令并维护置信度。普通用户只能读写自身分区，管理员可穿透查看全部画像。
- **Library Runtime**：本地文档知识库，支持多格式清洗、SHA-256 去重与检索。
- **Secretary Runtime & RealityPatch**：项目秘书与现实补丁状态机，所有状态变更必须经历「Draft (草稿) &rarr; Applied (确认应用) &rarr; Rolled Back (回滚)」的原子流程。
- **Tip Engine**：启发式提示引擎，主动检测循环交互与未确认风险。
- **Cognitive Engine**：可插拔认知引擎（Python / C++ 动态链接库），计算认知反馈增益 Delta。
- **Unified LLM Layer**：接入 OpenAI 兼容的统一推理层（支持 DeepSeek 等模型），具备上下文注入与优雅降级。

---

## 2. 统一数据协议 (Envelope & Objects)

### 2.1 交互请求信封 (`InteractionEnvelope`)
```json
{
  "user_id": "alice",
  "channel": "web",
  "message": "帮我创建一个任务：完成架构文档编写",
  "conversation_id": "default",
  "workspace_id": "default",
  "attachments": [],
  "timestamp": "2026-08-20T12:00:00+00:00",
  "permissions": [],
  "context": {}
}
```

### 2.2 响应信封 (`ResponseEnvelope`)
```json
{
  "content": "已为您生成新建任务补丁，请确认应用。",
  "media": [],
  "citations": [
    {
      "document_id": "doc_xxxx",
      "title": "项目规范.md",
      "source": "manual",
      "locator": "全文",
      "snippet": "任务创建需遵循现实补丁机制..."
    }
  ],
  "memory_events": [
    {
      "event_type": "stored",
      "memory_id": "mem_xxxx",
      "content": "偏好内容",
      "confidence": 0.86,
      "category": "preference_like"
    }
  ],
  "secretary_events": [
    {
      "type": "reality_patch",
      "data": {
        "id": "P-XXXX",
        "project_id": "default",
        "target_type": "task",
        "target_id": "new",
        "operation": "create",
        "proposed_change": "完成架构文档编写",
        "status": "draft"
      }
    }
  ],
  "tips": [
    {
      "tip_id": "tip_direction_shift",
      "type": "heuristic",
      "title": "话题方向快速切换",
      "message": "检测到您切换了关注重点...",
      "alternative_angle": "是否需要保存当前进展？",
      "confidence": 0.65,
      "cooldown_seconds": 900,
      "dismissible": true
    }
  ],
  "requires_confirmation": true,
  "audit_id": "A-XXXX",
  "metadata": {}
}
```

---

## 3. 核心接口列表

### 3.1 系统健康检查 `/health`
- **Method**: `GET`
- **URL**: `/health`
- **权限**: Public
- **响应示例** (`200 OK`):
```json
{
  "status": "ok",
  "service": "remedy-agent",
  "memory": "local-isolated",
  "auth": "active",
  "cognitive_engine": "PythonCognitiveEngine"
}
```

---

### 3.2 统一智能交互 (同步) `/v1/interactions`
- **Method**: `POST`
- **URL**: `/v1/interactions`
- **权限**: Public（未登录时使用请求体中的 `user_id`）；Authenticated 时强制将 `user_id` 锁定为当前登录用户，防止伪造
- **Content-Type**: `application/json`
- **请求体**: 见 `InteractionEnvelope`
- **响应示例** (`200 OK`): 见 `ResponseEnvelope`
- **cURL 示例**:
```bash
curl -X POST http://127.0.0.1:8091/v1/interactions \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","message":"我喜欢喝美式咖啡"}'
```

---

### 3.3 统一智能交互 (SSE流式) `/v1/interactions/stream`
- **Method**: `POST`
- **URL**: `/v1/interactions/stream`
- **Content-Type**: `application/json`
- **响应格式**: `text/event-stream`
- **事件结构**:
  - `data: {"type": "response", "data": {...ResponseEnvelope...}}\n\n`
  - `data: {"type": "done"}\n\n`

---

### 3.4 用户记忆查询 `/v1/users/{user_id}/memory`
- **Method**: `GET`
- **URL**: `/v1/users/<user_id>/memory?q={keyword}&limit={limit}`
- **权限**: Authenticated 后普通用户只能查询自身 `username` / `id`；管理员可查询任意用户。越权返回 `403 FORBIDDEN`
- **Query 参数**:
  - `q`: 搜索关键字（可选，支持精准相关性过滤）
  - `limit`: 返回条数限制（默认 20）
- **响应示例** (`200 OK`):
```json
{
  "user_id": "alice",
  "memories": [
    {
      "id": "mem_0c9b0e2b4da3",
      "category": "preference_like",
      "content": "美式咖啡",
      "confidence": 0.86,
      "occurrence_count": 1,
      "source": "web",
      "evidence": "我喜欢喝美式咖啡",
      "status": "active",
      "created_at": "2026-08-20T12:00:00+00:00",
      "last_seen_at": "2026-08-20T12:00:00+00:00",
      "updated_at": "2026-08-20T12:00:00+00:00"
    }
  ]
}
```

---

### 3.5 记忆反馈与认知打分 `/v1/feedback`
- **Method**: `POST`
- **URL**: `/v1/feedback`
- **权限**: Authenticated 时反馈写入当前登录用户的记忆分区
- **Content-Type**: `application/json`
- **请求体**:
```json
{
  "user_id": "alice",
  "feedback_type": "confirm", // 支持: confirm | reject | correct | forget
  "memory_id": "mem_0c9b0e2b4da3",
  "content": ""
}
```
- **响应示例** (`200 OK`):
```json
{
  "feedback_id": "fb_669f91a5",
  "memory_id": "mem_0c9b0e2b4da3",
  "feedback_type": "confirm",
  "cognitive_delta": 0.1
}
```

---

### 3.6 大五人格秘书督促档案 `/v1/users/{user_id}/personality`
- **Method**: `GET`
- **URL**: `/v1/users/<user_id>/personality`
- **权限**: Authenticated；普通用户只能查看自身档案，管理员可查看任意用户
- **作用**: 返回大五人格估计、理性/感性与执行/拖延倾向，以及秘书督促策略。人格用于督促工作学习，不会改变 Agent 口吻。
- **模型**: 优先 `Minej/bert-base-personality`（BERT 文本分类，五大连续分）。未安装 torch/transformers 或中文文本时，与本地启发式混合。
- **五大维度**: Openness 开放性、Conscientiousness 尽责性、Extraversion 外向性、Agreeableness 宜人性、Neuroticism 神经质
- **响应关键字段**: `scores`、`work_style.thinking_label`、`work_style.execution_label`、`playbook.strengths`、`playbook.gaps`、`playbook.today_focus`

---

### 3.6.1 彻底遗忘记忆 `/v1/users/{user_id}/memory/{memory_id}/forget`
- **Method**: `POST`
- **URL**: `/v1/users/<user_id>/memory/<memory_id>/forget`
- **权限**: Authenticated；普通用户只能遗忘自身记忆，管理员可操作任意用户
- **作用**: 彻底将该记忆及整个原始证据链（evidence）置为 `forgotten` 状态。
- **响应示例** (`200 OK`):
```json
{
  "success": true
}
```

---

### 3.7 知识库文档录入 `/v1/library/documents`
- **Method**: `POST`
- **URL**: `/v1/library/documents`
- **支持方式**:
  1. **Multipart 文件上传**:
     - `file`: 二进制文件（支持 `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`, `.csv`, `.json`）
     - `source`: 上传来源标识（可选，默认 `upload`）
  2. **JSON 文本直接录入**:
     - `filename`: 文档标题（如 `note.md`）
     - `content`: 纯文本内容
     - `source`: 来源标识（如 `manual`）
     - `tags`: 标签数组
- **响应示例** (`200 OK`):
```json
{
  "document_id": "doc_9f43b677a28e",
  "title": "note.md",
  "status": "indexed", // 若内容哈希已存在则返回 "duplicate"
  "content_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
  "char_count": 128
}
```
- **异常响应** (`400 Bad Request`): 扩展名不支持或解析失败。

---

### 3.8 知识库列表查询 `/v1/library/documents`
- **Method**: `GET`
- **URL**: `/v1/library/documents`
- **响应示例** (`200 OK`):
```json
{
  "documents": [
    {
      "document_id": "doc_9f43b677a28e",
      "title": "note.md",
      "source": "manual",
      "content_hash": "a591a6d40bf4...",
      "char_count": 128,
      "status": "active",
      "created_at": "2026-08-20T12:00:00+00:00"
    }
  ]
}
```

---

### 3.9 权威知识库检索 `/v1/library/search`
- **Method**: `GET`
- **URL**: `/v1/library/search?q={query}&limit={limit}`
- **响应示例** (`200 OK`):
```json
{
  "results": [
    {
      "document_id": "doc_9f43b677a28e",
      "title": "note.md",
      "source": "manual",
      "score": 3,
      "locator": "全文",
      "snippet": "匹配到的相关文本片段..."
    }
  ]
}
```

---

### 3.10 工作区进展同步草稿 `/v1/workspaces/{workspace_id}/sync`
- **Method**: `POST`
- **URL**: `/v1/workspaces/<workspace_id>/sync`
- **Content-Type**: `application/json`
- **请求体**:
```json
{
  "text": "1. 完成接口文档编写；2. 前后端联调通过；3. 部署上线",
  "actor": "alice"
}
```
- **响应示例** (`200 OK`):
```json
{
  "session_id": "S-9A8C1B7D",
  "status": "ready",
  "draft": {
    "summary": "1. 完成接口文档编写；2. 前后端联调通过；3. 部署上线",
    "tasks": [
      { "title": "完成接口文档编写", "owner": "", "status": "todo" },
      { "title": "前后端联调通过", "owner": "", "status": "todo" },
      { "title": "部署上线", "owner": "", "status": "todo" }
    ],
    "decisions": [],
    "risks": []
  }
}
```

---

### 3.11 确认同步草稿 `/v1/sync/{session_id}/confirm`
- **Method**: `POST`
- **URL**: `/v1/sync/<session_id>/confirm`
- **请求体**:
```json
{
  "actor": "alice"
}
```
- **响应示例** (`200 OK`):
```json
{
  "session_id": "S-9A8C1B7D",
  "status": "confirmed",
  "tasks": [
    { "id": "T-4F2A1E90", "title": "完成接口文档编写" },
    { "id": "T-8B1C3D4E", "title": "前后端联调通过" },
    { "id": "T-2C7E5F6A", "title": "部署上线" }
  ]
}
```

---

### 3.12 工作区看板数据 `/v1/workspaces/{workspace_id}/dashboard`
- **Method**: `GET`
- **URL**: `/v1/workspaces/<workspace_id>/dashboard`
- **响应示例** (`200 OK`):
```json
{
  "project_id": "default",
  "counts": {
    "todo": 3,
    "in_progress": 0,
    "blocked": 0,
    "done": 0
  },
  "tasks": [
    {
      "id": "T-4F2A1E90",
      "project_id": "default",
      "title": "完成接口文档编写",
      "status": "todo",
      "owner": "",
      "due_at": "",
      "created_at": "2026-08-20T12:00:00+00:00",
      "updated_at": "2026-08-20T12:00:00+00:00"
    }
  ],
  "patches": [
    {
      "id": "P-38A7E20B",
      "project_id": "default",
      "target_type": "task",
      "target_id": "new",
      "operation": "create",
      "proposed_change": "完成接口文档编写",
      "status": "applied",
      "created_by": "alice",
      "confirmed_by": "alice"
    }
  ],
  "audits": []
}
```

---

### 3.13 现实补丁确认与应用 `/v1/patches/{patch_id}/confirm`
- **Method**: `POST`
- **URL**: `/v1/patches/<patch_id>/confirm`
- **功能**: 原子应用现实补丁，修改实体数据库表，并记录回滚现场。
- **请求体**:
```json
{
  "actor": "alice"
}
```
- **响应示例** (`200 OK`):
```json
{
  "id": "P-38A7E20B",
  "status": "applied",
  "confirmed_by": "alice",
  "updated_at": "2026-08-20T12:00:00+00:00"
}
```
- **异常响应** (`409 Conflict`): 补丁不存在或非草稿状态。

---

### 3.14 现实补丁回滚 `/v1/patches/{patch_id}/rollback`
- **Method**: `POST`
- **URL**: `/v1/patches/<patch_id>/rollback`
- **功能**: 根据补丁的 `rollback_data` 恢复修改前状态，将补丁置为 `rolled_back`。
- **请求体**:
```json
{
  "actor": "alice"
}
```
- **响应示例** (`200 OK`):
```json
{
  "id": "P-38A7E20B",
  "status": "rolled_back",
  "updated_at": "2026-08-20T12:05:00+00:00"
}
```

---

### 3.15 QQ OneBot Webhook `/qq`
- **Method**: `POST`
- **URL**: `/qq`
- **权限**: Public（渠道自身签名 / 部署隔离）
- **作用**: 兼容 OneBot / NapCat 协议的 QQ 机器人消息接收网关。
- **请求体**:
```json
{
  "post_type": "message",
  "user_id": 12345678,
  "group_id": 87654321,
  "raw_message": "帮我查一下知识库"
}
```
- **响应示例** (`200 OK`):
```json
{
  "status": "ok",
  "reply": {
    "content": "检索结果...",
    "citations": []
  }
}
```

---

### 3.16 认证与权限接口

鉴权方式：`Authorization: Bearer <token>`，也可使用查询参数 `?token=`。

默认内置账号（首次启动自动写入 `data/auth.sqlite3`，Remedy 品牌）：
- 唯一管理员：`remedy_admin` / `Remedy@2025`（或环境变量 `REMEDY_ADMIN_PASSWORD`，`role=admin`）
- 普通用户：通过 `POST /v1/auth/register` 开放注册，强制 `role=user`；旧测试账号 `alice`/`bob` 已移除，`tools/migrate_remove_test_users.py` 幂等清理

#### 3.16.1 注册 `POST /v1/auth/register`
- **权限**: Public（注册角色固定为 `user`）
```json
{
  "username": "carol",
  "password": "secret1",
  "nickname": "Carol"
}
```
- **响应** (`200 OK`): `{ "success": true, "user": { "id", "username", "role", "nickname", "created_at" } }`

#### 3.16.2 登录 `POST /v1/auth/login`
```json
{ "username": "remedy_admin", "password": "Remedy@2025" }
```
- **响应** (`200 OK`):
```json
{
  "token": "tok_...",
  "expires_at": "2026-08-23T12:00:00+00:00",
  "user": {
    "id": "u_remedy_admin",
    "username": "remedy_admin",
    "role": "admin",
    "nickname": "Remedy Admin"
  }
}
```

#### 3.16.3 当前用户 `GET /v1/auth/me`
- **权限**: Authenticated
- **响应**: `{ "user": { "id", "username", "role", "nickname", "created_at" } }`

#### 3.16.4 注销 `POST /v1/auth/logout`
- **权限**: 携带当前 Token 即可
- **响应**: `{ "success": true }`

---

### 3.17 管理员专属画像分析接口

#### 3.17.1 全量用户列表 `GET /v1/admin/users`
- **权限**: Admin Only（`require_admin`，普通用户 `403`）
- **响应示例**（含人格雷达供 `admin.html` 直接渲染）:
```json
{
  "users": [
    {
      "id": "u_remedy_admin",
      "username": "remedy_admin",
      "nickname": "Remedy Admin",
      "role": "admin",
      "created_at": "2026-08-20T12:00:00+00:00",
      "stats": {
        "total_memories": 3,
        "total_interactions": 8,
        "categories": { "preference_like": 2 }
      },
      "personality": {
        "scores": { "openness": 0.52, "conscientiousness": 0.61, "extraversion": 0.48, "agreeableness": 0.55, "neuroticism": 0.43 },
        "work_style": { "thinking_label": "理性", "execution_label": "执行型" },
        "samples": 12
      }
    }
  ]
}
```

#### 3.17.2 指定用户完整画像 `GET /v1/admin/users/{target_user}/profile`
- **权限**: Admin Only
- **路径参数**: `target_user` 可为 `username` 或用户 `id`
- **响应**: `{ "target_user", "user_info", "stats", "memories": [...], "personality": {...} }`

#### 3.17.3 管理台聊天穿透（新增）
- `GET /v1/admin/users/<user_id>/interactions?q=&from=&to=&limit=20&offset=0` — 分页检索 `InteractionRow`，`q` 模糊 `message/reply`，时间 `ISO8601`，需 `require_admin`
- `DELETE /v1/admin/interactions/<interaction_id>` — 删除单条聊天，返回 `{success:true}`
- `POST /v1/admin/interactions/<interaction_id>/annotate` — `{tag, note, user_id}` 写入 `FeedbackRow(feedback_type=annotate)`，返回 `{feedback_id}`

---

### 3.18 联网搜索与网页读取接口（Web Runtime）

对话中也可直接触发：`!search 关键词`、`/联网 关键词`、粘贴 `http(s)://` 链接，Agent 会自动联网并将结果注入回答与引用。

#### 3.18.1 联网引擎信息 `GET /v1/web/info`
- **权限**: Public
- **响应示例**:
```json
{
  "searxng_url": "http://localhost:8080/search",
  "tavily_configured": true,
  "relay_configured": true,
  "relay_host": "47.79.237.188"
}
```

#### 3.18.2 多通道联网搜索 `POST /v1/web/search`
- **权限**: Public
- **请求体**: `{ "query": "DeepSeek 最新消息", "limit": 5 }`
- **通道优先级**: searxng → Tavily 直连 → SSH 中转自动故障转移
- **响应示例**:
```json
{
  "channel": "tavily",
  "results": [
    { "title": "...", "url": "https://...", "snippet": "...", "source": "tavily", "score": 0.9 }
  ],
  "answer": "AI 综合摘要（Tavily include_answer）",
  "error": ""
}
```
- 所有通道不可用时返回 `"channel": "none"` 与 `"error"` 说明，不抛异常

#### 3.18.3 读取网页正文 `POST /v1/web/fetch`
- **权限**: Public
- **请求体**: `{ "url": "https://example.com/page" }`
- **通道**: Jina Reader 直连优先，失败自动转 SSH 中转
- **响应**:
```json
{
  "content": "网页正文 Markdown（最多 6000 字符）",
  "error": "",
  "via": "jina-direct"
}
```
- 无效 URL 返回 `{ "error": "not a valid http(s) url", "via": "none" }`

---

## 4. 错误码与异常处理规范

| HTTP 状态码 | 含义 | 场景说明 |
|:---|:---|:---|
| `200 OK` | 成功 | 请求成功处理并返回数据 |
| `400 Bad Request` | 客户端参数错误 | 缺少 message、用户名冲突、密码过短、未知 feedback_type 等 |
| `401 Unauthorized` | 未登录 | 缺少或过期的 Bearer Token |
| `403 Forbidden` | 权限不足 | 普通用户访问管理员接口或跨用户记忆 |
| `404 Not Found` | 资源未找到 | 访问不存在的静态资源或路由 |
| `409 Conflict` | 状态机冲突 | 补丁已应用/不存在，或同步草稿重复确认 |
| `500 Internal Server Error` | 服务端未知异常 | 记录完整 Logger 异常调用栈 |

---

## 5. 权限模型

| 能力 | Public | 普通用户 (`user`) | 管理员 (`admin`) |
|:---|:---:|:---:|:---:|
| 注册 / 登录 | ✓ | ✓ | ✓ |
| 智能对话、知识库、看板 | ✓ | ✓（记忆写入自身分区） | ✓ |
| 查看 / 遗忘自身记忆 | — | ✓ | ✓ |
| 查看其他用户记忆画像 | — | ✗ `403` | ✓ |
| `/v1/admin/users` 与画像穿透 | — | ✗ `403` | ✓ |

密码使用 `pbkdf2_hmac(SHA-256, 100000 rounds)` 加盐存储；登录令牌默认 72 小时有效。
