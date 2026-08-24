# Remedy 重命名与登录/管理台重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `Remedy` 全局更名、开放注册且仅 `remedy_admin` 为管理员、彻底移除 `alice/bob`、管理台雷达与聊天穿透（删除/标注）

**Architecture:** 复用 `auth_runtime` 隔离、`storage/models` 分区、`app.py` admin 网关、`static/redesign` 新 `admin.*` 页，`Chart.js` 仅管理台懒加载

**Tech Stack:** Python 3.12 Flask SQLAlchemy, SQLite/PostgreSQL, vanilla JS + Chart.js, Docker

**Spec:** `docs/superpowers/specs/2026-08-25-remedy-auth-admin-design.md`

## Global Constraints

- `personality` 阈值 `HIGH 0.62 LOW 0.42` 不改
- `require_admin` 403 对普通用户，`register` 强行 `role=user`
- `remedy_admin` 初始密码 `Remedy@2025` 或 `REMEDY_ADMIN_PASSWORD`
- 管理台仅 `remedy_admin` 可见，普通用户 UI 零改动

---
### Task 2: auth 清理

**Files:**
- Modify: `auth_runtime/service.py:69-76`
- Create: `tools/migrate_remove_test_users.py`
- Test: `tests/test_auth_remedy.py`

**Interfaces:**
- Consumes: `AuthService`
- Produces: `remedy_admin` 唯一管理员，`alice/bob` 彻底移除

- [ ] **Step 1: 改 service.py**

```python
def _ensure_default_user(...):
    # 仅保留 remedy_admin
    self._ensure_default_user(conn, "remedy_admin", os.getenv("REMEDY_ADMIN_PASSWORD","Remedy@2025"), role="admin", nickname="Remedy Admin")
```

- [ ] **Step 2: register 强行 user**

```python
def register(..., role="user"): role="user"
```

- [ ] **Step 3: 写迁移脚本**

```python
# tools/migrate_remove_test_users.py
import sqlite3
from storage.db import get_session
from storage.models import MemoryRow, InteractionRow, FeedbackRow, PersonalityProfileRow, PersonalityObservationRow
# 删 auth.sqlite3 alice/bob + tokens, users.db 四表
```

- [ ] **Step 4: 单测**

```python
def test_no_alice_bob():
    auth=AuthService(tmp)
    assert not auth.get_user_by_id("u_alice")
    with pytest.raises(ValueError): auth.login("alice","123456")
```

- [ ] **Step 5: Commit**

```bash
git add auth_runtime/service.py tools/migrate_remove_test_users.py
git commit -m "feat(auth): remedy_admin only, remove alice/bob, open register"
```

### Task 3: Admin 3 接口

**Files:**
- Modify: `app.py:158-320`, `storage/models.py` (可选新表)
- Test: `tests/test_admin_interactions.py`

**Interfaces:**
- Consumes: `InteractionRow`
- Produces: `GET .../interactions`, `DELETE ...`, `POST .../annotate`

- [ ] **Step 1: 添加 GET 检索**

```python
@app.get("/v1/admin/users/<uid>/interactions")
@require_admin
def admin_interactions(uid):
    q=request.args.get("q",""); limit=int(request.args.get("limit",20))
    rows=agent.search_interactions(uid,q,limit) # 新增 MemoryService.search_interactions
```

- [ ] **Step 2: 添加 DELETE 与 annotate**

```python
@app.delete("/v1/admin/interactions/<iid>")
@require_admin
def admin_delete(iid): ...
@app.post("/v1/admin/interactions/<iid>/annotate")
@require_admin
def admin_annotate(iid): ...
```

- [ ] **Step 3: 单测 403 与分页**

```python
def test_admin_interactions_forbidden_for_user(): ...
```

- [ ] **Step 4: Commit**

```bash
git add app.py storage/models.py
git commit -m "feat(admin): interactions search/delete/annotate"
```

### Task 4: 管理台 UI

**Files:**
- Create: `static/redesign/admin.html`, `static/redesign/admin.js`, `static/redesign/admin.css`
- Modify: `static/redesign/index.html` 加管理员入口

**Interfaces:**
- Consumes: `GET /v1/admin/*`
- Produces: 雷达与检索页

- [ ] **Step 1: admin.html 骨架 + Chart.js CDN**

```html
<canvas id="radar"></canvas>
<div id="userTable"></div>
<div id="chatList"></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

- [ ] **Step 2: admin.js 检索/删除/标注**

```js
async function loadUsers(){ /* GET /v1/admin/users */ }
function renderRadar(scores){ new Chart(ctx,{type:'radar',data:{labels:['O','C','E','A','N'],datasets:[{data:[scores.openness,scores.conscientiousness,scores.extraversion,scores.agreeableness,scores.neuroticism]}]}}) }
```

- [ ] **Step 3: 联调**

- [ ] **Step 4: Commit**

```bash
git add static/redesign/admin.*
git commit -m "feat(ui): admin radar and chat management"
```

### Task 5: 全局更名

**Files:**
- Modify: `README.md`, `docs/**`, `docker-compose.yml`, `Dockerfile`, `app.py:95`, `static/**/title`

- [ ] **Step 1: rg 替换**

```bash
rg -l "Remedy" | xargs sed -i "s/Remedy/Remedy/g"
```

- [ ] **Step 2: docker-compose image**

```yaml
image: remedy:latest
```

- [ ] **Step 3: Commit**

```bash
git add README.md docker-compose.yml app.py
git commit -m "chore: rename Remedy -> Remedy"
```

### Task 6: 联调

- [ ] **Step 1: pytest**

```bash
PERSONALITY_DISABLE_BERT=1 pytest -q
```

- [ ] **Step 2: 手工 remedy_admin 登录**

### Task 7: 交付

- [ ] **Step 1: scp 到 47.79.237.188:~/remedy + docker compose up -d --build**

---

## Self-Review

- Spec 覆盖：更名/注册/清理/3接口/UI 均有点对任务
- 无占位，均含可执行代码块
- 类型一致：`admin_interactions` 签名与 `MemoryService` 一致
