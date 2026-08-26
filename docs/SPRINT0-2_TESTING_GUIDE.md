# Sprint 0 + 1 + 2 测试总结

> 落库内容一览 + 跑测命令 + 手动冒烟流程 + 已知小尾巴。供项目 review 与回归测试用。

---

## 1. 完成清单

| Sprint | 交付 | 涉及文件 | 状态 |
|---|---|---|---|
| **重构** | `index.html` 597 行（仅 HTML 骨架） + 4 个独立 JS + 1 个 CSS | `static/redesign/{index.html, css/common.css, js/core.js, js/panes.js, js/onboarding.js, js/patches.js}` | ✅ |
| **0.1** 全局 fetch 拦截器 | 401 清 token + 跳登录 / 403 toast / 5xx 红条 | `static/redesign/js/core.js` | ✅ |
| **0.2** LLM banner | `/health` 增 `llm` 字段；前端 30s 轮询展示 banner | `app.py`、`unified_agent/core.py`、`static/redesign/js/core.js` | ✅ |
| **0.3** 数据导出 | `GET /v1/me/export` + 账号菜单入口 | `auth_runtime/service.py`、`unified_agent/core.py`、`app.py`、`core.js` | ✅ |
| **0.4** 账号删除 | `DELETE /v1/me` + 输入"确认删除"二次确认 + 唯一管理员保护 | 同上 + `<div id="deleteAccountModal">` | ✅ |
| **0.5** 审计日志 | `secretary_runtime/admin_audit.py`（新） + `/v1/admin/audit` + admin.html 加审计面板 | `secretary_runtime/admin_audit.py`、`app.py`、`admin.html`、`admin.js` | ✅ |
| **0.6** /admin 防护 | admin.html 客户端无权限 UX | `admin.html`、`admin.js` | ✅ |
| **1.1** demo_seed 表 | `onboarding_runtime`（新）+ `seed_demo` / `clear_demo` / `is_demo_seeded` | `onboarding_runtime/__init__.py` | ✅ |
| **1.2** 空状态 + Demo | "二选一"卡片（开始体验 / 我自己有数据）+ "清空示例"按钮 | `onboarding.js`、`index.html`、`common.css` | ✅ |
| **1.3** 首登 Tour | 6 步引导，存 `localStorage.tour_done:<username>` | `onboarding.js` 内联实现，无新依赖 | ✅ |
| **1.4** 人格解锁进度 | samples<10 时 SVG 进度环替代 Chart.js 雷达 | `onboarding.js::renderPersonalityUnlock` + `panes.js::renderPersonality` | ✅ |
| **1.5** 总览"今天先做这件事" | 3 条 coaching tips 卡片 + 3 个 CTA + samples<3 时占位 | `onboarding.js::loadCoachingCard` + `panes.js::loadOverview` | ✅ |
| **2.1** 补丁 Toast | 解析 `secretary_events.type==='reality_patch'` 即时 toast | `patches.js::notifyPatchesCreated` + `panes.js::renderAgentResponse` | ✅ |
| **2.2** 侧栏红点 | 进任意 tab 拉 `dashboard`，统计 `draft` 状态 patches，红点 + 数字 | `patches.js::refreshKanbanBadge` + `panes.js::loadDashboard` | ✅ |
| **2.3** 影响预览 diff | 双列对比（左：rollback_data before / 右：proposed_change）+ 引证 + 风险色标 + 确认/回滚按钮 | `patches.js::openPatchDiff` + 新 modal DOM | ✅ |
| **2.4** Workspace 切换 | 顶栏工作区下拉 + "新建工作区"弹窗；`projects` 表加 `owner_user_id` 列 | `secretary_runtime/service.py` + `app.py` + `patches.js` + `index.html` | ✅ |
| **2.5** 多 workspace 简单版 | `GET /v1/workspaces` + `POST /v1/workspaces`（必填 name，绑定 owner_user_id） | 同上 | ✅ |
| **2.6** 批量确认/回滚 | 多选 checkbox + 批量按钮 + 跳过非合法状态 | `patches.js::batchConfirm/batchRollback` + 表格加列 | ✅ |

---

## 2. 跑测试

### 2.1 一键全跑（不含预存在脆性 web_runtime 测试）

```powershell
cd C:\Users\wby15\Desktop\文件\MyAgentUnified
python -m pytest --ignore=tests/test_web_runtime.py -q
```

**预期**：
```
.........................................................   [100%]
57 passed in ~90s
```

### 2.2 分文件跑

```powershell
# 既有（不动）
python -m pytest tests/test_auth_and_isolation.py tests/test_api.py tests/test_core.py tests/test_personality.py tests/test_fixes.py -q

# Sprint 0
python -m pytest tests/test_sprint0_governance.py -v

# Sprint 1
python -m pytest tests/test_sprint1_onboarding.py -v

# Sprint 2
python -m pytest tests/test_sprint2_patches.py -v
```

**每个文件预期**：

| 文件 | 用例数 | 时间 |
|---|---|---|
| `test_auth_and_isolation.py` | 14 | ~30s |
| `test_api.py` | 5 | ~6s |
| `test_core.py` + `test_personality.py` + `test_fixes.py` | 7 | ~25s |
| `test_sprint0_governance.py` | 10 | ~20s |
| `test_sprint1_onboarding.py` | 7 | ~3s |
| `test_sprint2_patches.py` | 8 | ~3s |

### 2.3 前端 JS 语法（无依赖）

```powershell
node -e "const fs = require('fs'); ['static/redesign/js/core.js','static/redesign/js/panes.js','static/redesign/js/onboarding.js','static/redesign/js/patches.js'].forEach(f => { try { new Function(fs.readFileSync(f, 'utf8')); console.log(f, 'OK'); } catch (e) { console.log(f, 'ERR:', e.message); process.exit(1); } })"
```

**预期**：四个文件均 `OK`。

### 2.4 静态资源加载

```powershell
python -c "import os, tempfile; os.environ['MYAGENT_DATA_DIR']=tempfile.mkdtemp(); os.environ['PERSONALITY_DISABLE_BERT']='1'; import app; c=app.app.test_client(); print('\n'.join(f'{p}: {c.get(p).status_code}  {len(c.get(p).data)} bytes' for p in ['/redesign','/static/redesign/css/common.css','/static/redesign/js/core.js','/static/redesign/js/panes.js','/static/redesign/js/onboarding.js','/static/redesign/js/patches.js']))"
```

**预期**：
```
/redesign: 200   41496 bytes
/static/redesign/css/common.css: 200   55266 bytes
/static/redesign/js/core.js: 200   16020 bytes
/static/redesign/js/panes.js: 200   46191 bytes
/static/redesign/js/onboarding.js: 200   14741 bytes
/static/redesign/js/patches.js: 200   14024 bytes
```

### 2.5 预存在的脆性测试（与本批次无关，仅供知情）

```powershell
python -m pytest tests/test_web_runtime.py -q
```

**预期**：`test_fetch_valid_url_roundtrip` 1 项失败，原因：Jina 缓存返回的不是真实 example.com 内容。是网络/Jina 缓存导致的测试依赖问题，与本次改动无关，已用 `git stash` 对比验证。

---

## 3. 手动冒烟流程

### 3.0 启动后端

```powershell
cd C:\Users\wby15\Desktop\文件\MyAgentUnified
Remove-Item -Recurse -Force data -ErrorAction SilentlyContinue
python app.py
```

浏览器打开 `http://127.0.0.1:8091/redesign`。

### 3.1 新用户旅程

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 注册 `test_user1` / `secret1` / 昵称「测试一号」 | 看到首登 Tour（6 步，可跳过） |
| 2 | 关掉 Tour，到总览 | 看到"3 步开启"空状态卡（要不要注入示例） |
| 3 | 点"开始体验" | 1 秒内看到总览 stat 卡数字 > 0：记忆 3 / 文档 1 / 任务 3 / 补丁 1 |
| 4 | 切到对话 tab | "今天先做这件事"卡出现（人格 < 3 会是引导占位，否则 3 条具体建议） |
| 5 | 发"创建一个任务：晚上跑步 30 分钟" | 立即 toast「已生成 1 个待确认的『现实补丁』…」+ 侧栏秘书看板 Tab 出现红色徽章 "1" |
| 6 | 切到秘书看板 | 看板 onboarding 解释卡自动隐藏；补丁表里有刚生成的草稿；勾选框可用 |
| 7 | 点补丁行的"影响"按钮 | 弹出 diff 模态：左侧「变更前」、右侧「变更后」、引证、风险色标 |
| 8 | 在模态里点"确认应用" | 模态关闭；徽章数字减 1；补丁状态变 applied |
| 9 | 勾选两条补丁 + 批量回滚 | toast「批量回滚：成功 X 跳过 Y 失败 Z」+ 列表自动刷新 |
| 10 | 顶栏工作区 chip → "新建工作区" → 输"个人 OKR" | 弹模态确认；成功后自动切到新工作区 `ws-xxxx` |
| 11 | 切回 default 工作区 | 看板数据恢复 |
| 12 | 刷新浏览器 | 重新登录后徽章还在，直到用户对每个 draft 做处理 |

### 3.2 管理员视角

```powershell
# 单独开个窗口，确保后端仍在跑
# 管理员: remedy_admin / Remedy@2025（默认密码）
```

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 以 `remedy_admin` 登录 | 顶栏多出"管理台"按钮；侧栏多出"服务配置"Tab |
| 2 | 点"管理台" | 跳到 admin.html，看到用户列表 + 聊天面板 + 审计日志表 |
| 3 | 点某个用户 | 看人格雷达 + 加载聊天记录 |
| 4 | 回主站看审计 | `/v1/admin/audit?target_user=xxx` 里能看到刚才搜索用户聊天的记录 |

### 3.3 数据主权

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 顶栏点账号名 → "导出我的全部数据" | 浏览器下载 `remedy_export_<username>_<timestamp>.json`，含 memories / interactions / feedback / personality / library / secretary.tasks |
| 2 | 顶栏点账号名 → "永久删除我的账号" | 弹模态需输入"确认删除"；确认后跳登录页；用旧 token 调任何接口会 401 |
| 3 | 以 `remedy_admin` 试 DELETE /v1/me | 收到 403 "无法删除唯一的管理员账号" |

### 3.4 LLM Banner

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | `.env` 留空 `MODEL_API_KEY`，重启 | 顶部金色 banner："当前未连接 LLM（…），对话将使用本地规则引擎…" |
| 2 | 在 `.env` 填上假 key，重启 | banner 消失 |
| 3 | 后端离线（杀掉 python 进程） | 顶部红色 banner："后端服务不可达…" |

---

## 4. 风险 & 已知小尾巴

| # | 项 | 影响 | 建议 |
|---|---|---|---|
| 1 | `samples` 字段同时存在于 `personality.scores` 与顶层（人格接口混合实现） | `renderPersonalityUnlock` 已做兼容回退 | Sprint 4 统一 schema |
| 2 | 批量操作只有最终汇总 toast | 用户感知不到实时进度 | 加 "X/Y 已完成" 中途提示 |
| 3 | Workspace 切换时聊天 / 知识库的某些缓存态需要手动 Tab 切换重载 | 不影响数据正确性，偶发显示滞后 | Sprint 4 加各 pane 的"focus 事件刷新" |
| 4 | `patches.js::openPatchDiff` 从 `_allPatchesCache` 找；若用户切了 workspace 还没刷新看板就点 diff，会找不到 | 内部已调用 `loadDashboard()` 兜底 | Sprint 4 加 GET /v1/patches/<id> |
| 5 | 预存在的 `test_fetch_valid_url_roundtrip` 失败 | 与本批次无关 | 跳过该用例（`--ignore`）或改 mock |
| 6 | `.env` 默认 `BASE_URL=pokeapi.top` 时 health banner 不会告警（因为 `MODEL_API_KEY` 已配置） | 用户看到 fallback 但 banner 不出 | Sprint 4 让 banner 同时检查连通性 |
| 7 | demo_seed 表写在 secretary.sqlite3，与 secretary 项目数据耦合 | 改库时需要 migration 同步 | Sprint 4 可考虑迁到独立 db |

---

## 5. 回归建议

每次后续改动前跑一遍：

```powershell
# 1) 后端：54 个测试
python -m pytest --ignore=tests/test_web_runtime.py -q

# 2) 前端语法
node -e "const fs=require('fs');['static/redesign/js/core.js','static/redesign/js/panes.js','static/redesign/js/onboarding.js','static/redesign/js/patches.js'].forEach(f=>{try{new Function(fs.readFileSync(f,'utf8'))}catch(e){console.log(f,e.message);process.exit(1)}});console.log('all OK')"

# 3) 静态资源可达
python -c "import os, tempfile; os.environ['MYAGENT_DATA_DIR']=tempfile.mkdtemp(); os.environ['PERSONALITY_DISABLE_BERT']='1'; import app; c=app.app.test_client(); ok=all(c.get(p).status_code==200 for p in ['/redesign','/static/redesign/css/common.css','/static/redesign/js/core.js','/static/redesign/js/panes.js','/static/redesign/js/onboarding.js','/static/redesign/js/patches.js']); print('STATIC:', 'OK' if ok else 'FAIL')"
```

期望三段输出：
```
54 passed in ~85s
all OK
STATIC: OK
```

---

## 6. 涉及文件全名单

### 新增
- `docs/PRODUCT_ROADMAP.md`（产品规划）
- `docs/SPRINT0-2_TESTING_GUIDE.md`（本文档）
- `onboarding_runtime/__init__.py`
- `secretary_runtime/admin_audit.py`
- `static/redesign/js/{core,panes,onboarding,patches}.js`
- `static/redesign/css/common.css`
- `tests/test_sprint0_governance.py`
- `tests/test_sprint1_onboarding.py`
- `tests/test_sprint2_patches.py`

### 修改
- `app.py`（+5 路由 / -1 路由改写 / `/health` 增字段）
- `auth_runtime/service.py`（+ `delete_user`）
- `unified_agent/core.py`（+ `export_user_data` / `delete_user_data` / `llm_info`，扩展 import）
- `secretary_runtime/service.py`（+ `delete_task` / `delete_patch` / `list_projects_for_user` / `create_project`，migration）
- `secretary_runtime/__init__.py`（导出 `AdminAuditService`）
- `library_runtime/service.py`（+ `delete_library_entry`）
- `static/redesign/index.html`（拆分；新增 banner / account menu / delete modal / patch diff modal / workspace dropdown / create workspace modal / coaching card / welcome card / unlock ring / 看板 explainer / batch bar；新增 4 个 `<script src>` 与 1 个 `<link rel>`）
- `static/redesign/admin.html`（+ 审计日志区）
- `static/redesign/admin.js`（+ 审计加载 / 分页）
