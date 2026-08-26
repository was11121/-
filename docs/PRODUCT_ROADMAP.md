# Remedy 产品优化 Roadmap

> 目标：把"能力栈已经齐全"的 Remedy 打造成"用户能感知到价值"的产品。
> 节奏：2 周一个 Sprint，约 12 周走完 P0+P1；Sprint 6 进入持续迭代。
> 工时假设：1 名前端为主、兼后端的工程师；如团队多人可并行压缩。

---

## 优先级矩阵

| 优先级 | Sprint | 一句话主题 | 为什么 |
|---|---|---|---|
| **P0** | Sprint 0 | 基础治理 | 401 / 数据主权 / 审计日志不做会出事 |
| **P0** | Sprint 1 | 冷启动 | 新用户进来 0 价值，留不下来 |
| **P0** | Sprint 2 | 补丁体验 | 最差异化的能力被埋没了 |
| **P1** | Sprint 3 | 导航重构 | 7 个 Tab 平铺，小白劝退 |
| **P1** | Sprint 4 | 行为闭环 | 人格、记忆、知识库三件套缺最后一公里 |
| **P1** | Sprint 5 | 移动端 | 至少要能看能用 |
| **P2** | Sprint 6 | 增长与差异化 | 命令面板 / 人格对比 / 回顾邮件 |

---

## 横切关注（每个 Sprint 都顺手做一点）

| 主题 | 做法 |
|---|---|
| **可观测性** | `/health` 已存在；前端顶部加 `health-banner`，LLM / MCP / 联网通道状态变化时推送 |
| **i18n** | 当前文案写死中文；先把所有可见字符串抽到 `static/redesign/i18n.zh.js`，为后续 i18n 铺路 |
| **可访问性** | 所有交互元素补 `aria-label`，键盘 Tab 顺序，色对比度（已有但再核一遍） |
| **错误日志** | 前端 fetch 全部走 `apiFetch()` 统一拦截器，记录 4xx/5xx 到 console + 顶部红条提示 |
| **空状态规范** | 每个 Tab / 每张卡都有 `EmptyState` 组件：插画 + 文案 + 主按钮 |

---

## Sprint 0 · 基础治理（Week 1，3 工日）

> 这一周不开发新功能，只做"地基"——不然后面所有 UX 都跑在不安全 / 不一致的地面上。

### 用户故事
- 作为普通用户，我希望 **Token 过期后自动跳回登录页**，而不是看到一个空白屏。
- 作为普通用户，我希望 **LLM 没接上时**有明确 banner，而不是以为自己在和 AI 说话。
- 作为普通用户，我需要 **一键导出我的全部数据** 和 **删除账号**。
- 作为管理员，我做的每一次"查看他人聊天" **必须有日志**。

### 任务清单

| # | 任务 | 涉及文件 | 工时 | 验收 |
|---|---|---|---|---|
| 0.1 | 全局 `apiFetch()` 拦截器：401 → 清 token + 跳 `/login`；403 → toast；5xx → 顶部红条 | `static/redesign/index.html` JS 段 | 0.5d | 手动篡改 token，触发 401，2 秒内跳登录 |
| 0.2 | `health-banner` 组件：每 30s 拉 `/health`，LLM=fallback 时顶部出现"当前未连接 LLM，使用本地规则" | `index.html` + `app.py:health` | 0.5d | 拔掉 `MODEL_API_KEY` 重启，看到 banner |
| 0.3 | `GET /v1/me/export` + 前端"导出我的数据"按钮（JSON：记忆/人格/看板/补丁/上传文档元数据） | 新增 `app.py` 路由 + `memory_runtime` / `secretary_runtime` 提供 dump | 1d | 下载得到的 JSON 含全部字段，能用 jq 打开 |
| 0.4 | `DELETE /v1/me` + 前端"删除账号"二级确认（输入"确认删除"） | 新增 `app.py` 路由 + `auth_service.delete_user` | 0.5d | 删完后该用户 token 立即失效，`auth.sqlite3` 和 `users.db` 数据清除 |
| 0.5 | 审计日志表 + `GET /v1/admin/audit` + `admin.html` 增加"审计"页 | `secretary_runtime` 加 audit 表 / 新增路由 | 1d | 管理员搜一次用户聊天后，audit 表里有记录，页面能展示 |
| 0.6 | 把 `/admin` 加 `require_admin` 中间跳板 | `app.py` 加 `require_admin_page` 装饰器 + JS 跳板 | 0.25d | 普通用户访问 `/admin` 看到"权限不足" |

**Sprint 0 总计：3.75 工日 / 1 周（含 buffer）**

---

## Sprint 1 · 冷启动（Week 2-3，5 工日）

> 目标：新用户注册后 90 秒内能"看到产品长什么样"，并完成首次有意义的交互。

### 用户故事
- 作为新用户，我希望 **注册成功立刻跳到一个 3 步引导页**，告诉我先做什么。
- 作为新用户，我希望 **进总览页时不是 0**——有示例记忆 / 看板 / 文档可以点开看。
- 作为新用户，我希望 **人格雷达有解锁进度**，而不是一直空白。
- 作为新用户，我希望 **第一次对话有欢迎语 + 引导气泡**，引导我问第一个问题。

### 任务清单

| # | 任务 | 涉及文件 | 工时 | 验收 |
|---|---|---|---|---|
| 1.1 | 新增 `Demo Workspace` 概念：注册时自动给用户插入 3 条示例记忆、1 份示例文档、1 张示例看板；每条带 `_demo: true` 标记；总览页空状态展示"开始体验 / 清空示例"二选一按钮 | `memory_runtime.service` / `library_runtime` / `secretary_runtime` 加 `seed_demo()` | 1.5d | 新注册用户登录，看到"开始体验"按钮，点击后 3 个示例出现，"清空示例"按钮可恢复 |
| 1.2 | 总览页 stat 卡 **0 值空状态**：当 memories=0 且无 demo 时，显示"3 步开启"插画卡：① 写一句目标 ② 拖入文档 ③ 5 句对话解锁人格 | `static/redesign/index.html` 概览 pane | 0.5d | 注册新用户看总览，看到 3 步引导卡 |
| 1.3 | **首登 Tour**：用 `driver.js` 或自己实现（vanilla 即可），7 个 Tab 各停 3 秒，可跳过；状态存 `localStorage.tour_done` | 新增 `static/redesign/tour.js` | 1d | 清缓存后登录，看到 tour，能跳过，二次登录不再出现 |
| 1.4 | 人格雷达 **解锁进度环**：当 samples<10 时，雷达外圈替换为"对话 X/10 解锁完整画像"的进度条 | `personality_runtime.service.get_profile` 返回 `unlock_progress` 字段 + 前端 SVG | 0.5d | 新用户聊 1 句，雷达显示"1/10"；10 句后切换为完整雷达 |
| 1.5 | 对话页 **首次欢迎气泡**：检测到首条用户消息，AI 回复固定模板"我是 Remedy，已经记住你了。今天先聊点啥？"；同时弹一个引导气泡提示 `!search`、`@知识库`、`/memory` 等指令 | `unified_agent.core` 加 first-message hook + 前端 onboarding bubble | 1d | 新用户首条对话收到欢迎 + 看到指令提示 |
| 1.6 | 总览页增加 **"今天先做这件事"** 单卡（人格 coaching_tips 取第一条模板渲染） | 后端 `coaching_playbook` 已存在 / 前端渲染 | 0.5d | 任何人登录看总览，第一屏就能看到一条具体建议 |

**Sprint 1 总计：5 工日 / 2 周**

---

## Sprint 2 · 补丁体验（Week 4-5，5 工日）

> 目标：让"现实补丁"成为产品最显眼的差异化能力。

### 用户故事
- 作为用户，**AI 给我生成一条补丁时**，我要立刻知道（Toast + 红点）。
- 作为用户，我点开补丁时要看到 **它改了啥、影响谁、能不能撤回**。
- 作为用户，我需要 **多个 workspace**，而不是只有 `default`。
- 作为新用户，我在看板页要看到 **"什么是补丁"** 的解释面板。

### 任务清单

| # | 任务 | 涉及文件 | 工时 | 验收 |
|---|---|---|---|---|
| 2.1 | **新补丁实时通知**：`agent.handle_interaction` 返回值里有 `patch_created` 时，前端 `Toast` 组件弹"+1 现实补丁待你确认"，侧栏 Kanban Tab 出现红点 + 数字徽章 | `app.py:interactions` 响应结构 + `index.html` toast/badge | 0.75d | 对话中触发 create_patch 后 1 秒内看到 toast 与红点 |
| 2.2 | **补丁影响预览 diff**：点击补丁打开模态框：左列"当前状态"右列"拟议变更"，附 `evidence` 引证 + `risk` 等级色条 + `created_by` / `created_at` / `affected_count` | `secretary_runtime.service.get_patch_detail` + 前端 modal | 1d | 任意补丁点开，能看到 diff / 引证 / 风险色 |
| 2.3 | **看板 onboarding 解释卡**：检测 `patches_count == 0` 时显示一张"什么是补丁"图解卡（3 步流程图：生成→确认→应用/回滚） | `index.html` kanban pane | 0.5d | 新用户看看板，看不到任何卡，但看到解释卡 |
| 2.4 | **Workspace 切换器 / 创建**：侧栏顶增加 workspace 下拉 / 切换 / "新建 workspace" 弹窗（输入名称 + 选模板：学习 / 工作 / 生活）；后端 `workspaces` 表存多 workspace 与成员映射 | 新增 `workspace_runtime` 或扩展 `secretary_runtime`；新增 routes | 1.5d | 创建 workspace A，把任务挪到 A，创建 workspace B，能在两者间切换 |
| 2.5 | 看板增加 **筛选器**：按 status / risk / created_by 过滤；批量确认/回滚按钮 | `index.html` kanban pane + 后端筛选参数 | 0.75d | 选 3 条补丁批量确认，看到状态同步变化 |
| 2.6 | 在对话里 **生成补丁时**给出"将要生成补丁"的事前确认（轻量）："我准备把'晚上 11 点断网'加进你的补丁草稿，确认吗？"——让用户参与而非被动接受 | `unified_agent.core` patch-generation hook | 0.5d | 触发 patch 生成的对话，看到一个轻量确认气泡 |

**Sprint 2 总计：5 工日 / 2 周**

---

## Sprint 3 · 导航重构（Week 6，2.5 工日）

> 目标：让小白不被 7 个 Tab 劝退。

### 用户故事
- 作为普通用户，我只看到 **4 个核心 Tab + 1 个"高级"抽屉**。
- 作为用户，总览页只回答 **"今天我该做什么"**，别的一律下沉。

### 任务清单

| # | 任务 | 涉及文件 | 工时 | 验收 |
|---|---|---|---|---|
| 3.1 | 侧栏分两段："核心"（总览 / 对话 / 看板 / 记忆）+ "高级"（知识库 / 联网 / 配置）折叠到 "⚙ 高级" 抽屉按钮里；管理员额外在底部多一个"管理台"链接 | `index.html` 侧栏 DOM + JS | 0.75d | 默认看到 4 个 Tab，点"高级"展开 |
| 3.2 | 总览页 **瘦身**：保留 ①今日待办（合并进行中+到期）②人格一句话建议 ③最近 3 次对话快捷入口；其余 stat 卡 / module-card / 最近补丁 / 最近记忆 / 最近文档全部移到对应 Tab | `index.html` 概览 pane | 1d | 总览页高度从 4 屏降到 1.5 屏 |
| 3.3 | 管理员登录后，顶部 banner 提示"您是管理员，可点此进入管理台"（24h 后自动消失，可手动关闭） | `index.html` 顶部 banner + localStorage | 0.25d | remedy_admin 登录，看到 banner；普通用户登录看不到 |
| 3.4 | 移动端断点（≤ 768px）下，侧栏默认折叠为左上角汉堡按钮 + 抽屉 | `index.html` 媒体查询 + JS | 0.5d | 切到手机尺寸，侧栏收起来 |

**Sprint 3 总计：2.5 工日 / 1 周**

---

## Sprint 4 · 行为闭环（Week 7-8，5 工日）

> 目标：把人格 / 记忆 / 知识库三件套的"最后一公里"补上。

### 用户故事
- 作为用户，我看人格雷达时 **直接看到今天该做什么**（模板生成即可，不调 LLM）。
- 作为用户，每条记忆我要知道 **它怎么来的**（对话/文档/AI 推断），不放心就一键删除。
- 作为用户，**一键清空某类记忆** 是应急按钮。
- 作为用户，我能 **导出全部记忆为 JSON**。
- 作为用户，**联网结果可以一键收藏到知识库**。
- 作为用户，**知识库上传后我能看到解析进度和分块预览**。
- 作为用户，对话输入 `@@文档名` 能引用知识库。

### 任务清单

| # | 任务 | 涉及文件 | 工时 | 验收 |
|---|---|---|---|---|
| 4.1 | 人格页底部"今天建议你"卡：调 `personality_runtime.service.coaching_tips(profile)` 取前 3 条，模板渲染（不调 LLM），每条带 1 个主按钮（创建任务/写记忆/打开对话） | `index.html` 人格 pane + 后端已存在 | 0.5d | 登录看人格页，看到 3 条具体建议 |
| 4.2 | **记忆来源标签**：每条记忆展示 `[对话] / [文档] / [AI 推断]` 三色徽章；点击展开溯源（关联的 interaction_id / document_id） | `memory_runtime.service` 给 memory 加 `source_type` / `source_ref` 字段 + 前端 | 1d | 任意记忆点开能看到"来自 2026-08-26 14:32 的对话" |
| 4.3 | 记忆页增加 **按类别聚合视图**：tabs = 全部 / 偏好 / 事实 / 任务 / 推断；每类右侧有"批量删除该类"按钮（二次确认） | `index.html` 记忆 pane + 后端聚合查询 | 1d | 看到 4 个 tab；选"推断"类批量删除，确认后该类清空 |
| 4.4 | 记忆页顶部 **"导出我的全部记忆为 JSON"** 按钮（已经做完 Sprint 0.3 的扩展） | 同 0.3 | 0.25d | 下载得到 `memories.json` |
| 4.5 | 联网结果每条增加 **"📥 收藏到知识库"** 按钮，POST `/v1/library/ingest` 接收 url，存为文档 | `library_runtime` 加 `ingest_url()` + 前端按钮 | 0.5d | 联网搜出 3 条，收藏 1 条，知识库页能看到这条 |
| 4.6 | 知识库上传 **解析进度**：上传后 SSE 流式推送进度（解析中 30% / 分块中 70% / 完成 100%）；完成后弹预览（取前 3 个 chunk） | `app.py` SSE + `library_runtime` 分阶段回调 | 1d | 上传一份 1MB PDF，看到进度条，完成后看到前 3 段预览 |
| 4.7 | 知识库 **重建索引按钮**（高级抽屉内）：调 `tools/rebuild_library_index.py`，带二次确认 | `tools/` 已有脚本复用 + 前端按钮 | 0.25d | 点重建索引，看日志，确认成功 |
| 4.8 | 对话输入 `@@` 触发知识库检索面板（与 `!search` 类似的 UX），选中文档片段插入到消息 | 前端 token parser + `library_runtime.search` | 0.5d | 输入 `@@2026 规划` 看到候选片段，点击插入 |

**Sprint 4 总计：5 工日 / 2 周**

---

## Sprint 5 · 移动端（Week 9-10，4 工日）

> 目标：移动端至少要"能看能用"，不强求完美。

### 任务清单

| # | 任务 | 涉及文件 | 工时 | 验收 |
|---|---|---|---|---|
| 5.1 | 断点 ≤ 768px：底部 TabBar 替换侧栏（对话 / 看板 / 知识库 / 记忆 / 我的） | `index.html` 媒体查询 + DOM 切换 | 1d | 切到手机尺寸，看到底部 TabBar |
| 5.2 | 长对话流式渲染：键盘弹起时输入区不被遮挡；自动滚动到底部；停止滚动时不要强制滚（保留用户阅读位置） | `index.html` chat pane JS | 0.5d | 模拟手机键盘，验证滚动行为 |
| 5.3 | 看板 / 记忆页改为 **卡片堆叠**（替代桌面端表格） | CSS + JS | 0.5d | 看板页在手机下能纵向滚 |
| 5.4 | 知识库上传走 **拍照 / 相册** 而不是拖拽（移动端无拖拽） | `<input type="file" accept="image/*" capture>` | 0.25d | 手机拍照上传成功 |
| 5.5 | 关键交互（补丁确认 / 记忆删除 / 账号删除）在移动端用 **全屏 sheet** 而不是 modal | CSS | 0.5d | 三个交互在手机下都是 sheet |
| 5.6 | PWA 化：manifest.json + service worker，离线可读缓存的对话/记忆 | `static/manifest.json` + sw.js | 1d | 离线打开能看到最近一次会话 |
| 5.7 | 移动端隐藏 **认知引擎 / 模型名** 等开发者信息 | CSS `display:none` | 0.25d | 移动端不显示底层细节 |

**Sprint 5 总计：4 工日 / 2 周**

---

## Sprint 6 · 增长与差异化（Week 11+，持续）

### 任务清单

| # | 任务 | 工时 | 备注 |
|---|---|---|---|
| 6.1 | **Cmd+K 命令面板**：所有能力（创建记忆 / 切 workspace / 上传文档 / 触发搜索）都能从命令面板调起 | 2d | 借鉴 Linear / Raycast |
| 6.2 | **人格对比模式**：雷达支持叠加显示"一周前 vs 现在"，并标出变化最大的维度 | 1d | 后端存历史快照 |
| 6.3 | **里程碑徽章**：第 1 条记忆 / 第 7 天连续登录 / 第 50 次对话 / 第 1 个补丁被应用 → 给徽章 + 一次性 Toast | 1d | 新表 `milestones` |
| 6.4 | **每日回顾邮件**：早 9 点发"今天 3 件待办"；周日发"本周人格/记忆变化总结" | 1.5d | 需要 SMTP 或 webhook 到推送服务 |
| 6.5 | **多 LLM Provider 切换**：在服务配置页允许同时配 DeepSeek / OpenAI / Claude / Ollama，按对话切换 | 2d | 已有 `runtime_settings`，扩展 |
| 6.6 | **插件化 Tool 列表**：把 `!search` / `@@kb` / `/memory` 等指令改成可注册的 Tool，让用户自己加 | 2d | 需要重构 `unified_agent.protocol` |
| 6.7 | **多语言**：先 zh-CN / en-US 两种，渐进加 ja / ko | 3d | Sprint 0 已铺 i18n |
| 6.8 | **协作模式**：管理员/朋友可读（不可写）某个 workspace 的记忆 | 3d | 新权限角色 `viewer` |

**Sprint 6 持续：每周挑 1-2 个，3 个月走完**

---

## 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 后端 `secretary_runtime` 是 SQLite，多 workspace 扩展后可能性能下降 | P0 工作流被拖慢 | Sprint 2 用现有表加列；Sprint 6 评估迁移到 PG（compose 已支持） |
| 单文件 `index.html` 已经 2946 行，再加东西会失控 | 所有 Sprint | Sprint 3 之前先拆 CSS / JS 到独立文件（`redesign/app.js` / `redesign/components/`） |
| Demo Workspace 数据如果不小心混进生产 | 用户信任 | 全部带 `_demo=true` 标记；导出 JSON 时单独 export 真实数据 |
| 移动端工作量大但 ROI 不确定 | Sprint 5 延期 | 先做 5.1/5.2/5.5 三个最高频的，其余看数据再决定 |
| LLM fallback 时人格 coaching 是模板，体验打折 | Sprint 1/4 效果 | 文案做精，提供 3-5 套模板覆盖常见人格 |

---

## 立即可启动的下一步

如果同意这个 Roadmap，建议 **本周 Sprint 0 全部 + Sprint 1 的 1.1 / 1.2** 一起开工（4 工日能交付"安全地基 + 冷启动 Demo Workspace + 空状态引导"）。

要我开始实现哪个？
- **A**：先做 Sprint 0 全套（治理地基）；
- **B**：先做 Sprint 1 的 Demo Workspace + 空状态（冷启动）；
- **C**：先做 Sprint 2 的补丁 Toast + 红点（核心差异化）；
- **D**：先做 Sprint 3 的侧栏重构（最低成本、视觉立竿见影）。
