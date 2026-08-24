# Remedy 重命名与登录/管理台重构 设计 Spec

**版本** v1.0 2026-08-25 | **关联 Plan** `docs/superpowers/plans/2026-08-25-remedy-auth-admin-plan.md`

## 1. 背景与目标

- **更名**：`Remedy → Remedy` 全局，含 UI 品牌、文档、镜像、服务名
- **登录**：开放注册即 `user`，彻底移除测试账号 `alice/bob`（`auth_runtime/service.py:69` 与 `data/auth.sqlite3`、`data/users.db` 四表），新增唯一管理员 `remedy_admin`
- **管理台**：`remedy_admin` 可见所有用户 `名字/账号/人格雷达 + 聊天检索/删除/标注`，普通用户零改动

## 2. 范围与非目标

- 范围：`auth_runtime`、`storage/models.py`、`app.py` 3 新增 admin 接口、`static/redesign/admin.*` 新页、`docker-compose/README/docs` 更名、`tools/migrate_remove_test_users.py`
- 非目标：不改 `Big Five` 算法/阈值，不引 OAuth，不重做大模型瘦身（已 `c859993`）

## 3. 详细设计

### 3.1 auth

- `auth_runtime/service.py:76` `_ensure_default_user` 仅保留 `remedy_admin`（`id=u_remedy_admin`，`nickname=Remedy Admin`），`password` 取 `REMEDY_ADMIN_PASSWORD` 或 `Remedy@2025`，`register()` 强制 `role=user`
- 迁移 `tools/migrate_remove_test_users.py` 幂等：`DELETE FROM users WHERE username IN ('alice','bob')`、`tokens` 级联、`users.db` 按 `user_id IN ('alice','bob','u_alice','u_bob')` 清 `memories/interactions/feedback/personalities/observations`
- 启动自检：`AuthService.__init__` 若仍含 `alice/bob` 则 `logger.warning`

### 3.2 新增 Admin API（`require_admin`）

- `GET /v1/admin/users` 已有，扩展返回 `personality.scores` 供雷达
- `GET /v1/admin/users/<id>/interactions?q=&from=&to=&limit=20&offset=0` — 分页检索 `InteractionRow`，`q` 模糊 `message/reply`，时间 `ISO8601`
- `DELETE /v1/admin/interactions/<interaction_id>` — 删 `InteractionRow` 并写 `audit`，返回 `{success:true}`
- `POST /v1/admin/interactions/<interaction_id>/annotate` — `{tag, note}` 写入 `FeedbackRow`（`feedback_type=annotate`）或新表 `interaction_annotations`，返回 `{annotation_id}`

### 3.3 管理台 UI

- 新文件 `static/redesign/admin.html` + `admin.js` + `admin.css`，复用 `design-system` 令牌
- 左表：`nickname/username/注册时间/记忆数/对话数/雷达缩略`，`GET /v1/admin/users`
- 右上：雷达 `Chart.js Radar` 5 轴 `O/C/E/A/N`，`HIGH 0.62` 虚线，`work_style` 标签
- 右下：检索 `输入框+日期+分页` → `GET .../interactions`，每条 `message/reply/time` + `删除/标注` 按钮，标注以色点展示
- 权限：`require_admin` 403 则跳登录；普通用户访问 `/admin` 重定向 `/redesign`

### 3.4 全局更名

- `README.md`、`docs/**`、`docker-compose.yml: image: remedy:latest`、`Dockerfile LABEL`、`app.py: health.service="remedy-agent"`、`static/**/ <title>`、`package.json`、`文件夹` `Remedy → Remedy`（`git mv` 兼容 symlink）

## 4. 数据与兼容

- `init_db` 幂等，`remedy_admin` 缺失自动创建
- 旧库含 `alice/bob` 时迁移后查询为空，属预期

## 5. 验收

- `register` 新用户为 `user`，`login alice` 失败
- `remedy_admin` 登录后 `GET /v1/admin/users` 含所有用户及雷达数据，`GET .../interactions` 分页/关键词/删除/标注 回读正常
- `docker compose up -d --build` 健康，`pytest -q` 绿
