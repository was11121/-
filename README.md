# Remedy · 现实补丁 Agent

一个把「持续记住你、理解你、并帮你把想法落地成可追踪现实变化」作为核心目标的个人智能体系统。它以本地隔离的反馈记忆为底座，统一 Web/QQ 入口，并提供 AI 图书馆、文档处理、AI 秘书（现实补丁）、大五人格画像、主动思维 Tip 和 3D 记忆图谱可视化六大能力模块，全部围绕同一套跨会话记忆协同工作。

项目简介、技术方案与创新点说明见 [`docs/PROJECT_INTRO.md`](docs/PROJECT_INTRO.md)（或 Word 版 `docs/Remedy-项目简介.docx`）；演示视频大纲与讲解稿见 [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)。

## 技术栈

| 层次 | 技术选型 |
|---|---|
| 后端框架 | Python 3 + Flask，REST API（`API.md` 完整定义 30+ 接口） |
| 数据层 | SQLAlchemy 2.0 ORM；默认 SQLite，`DATABASE_URL` 一键切换 PostgreSQL 16，业务代码零改动 |
| 大模型接入 | DeepSeek 官方 API（`deepseek-v4-flash` / `deepseek-chat`），支持任意 OpenAI 兼容 `BASE_URL`；无密钥/网络异常时自动降级为本地规则响应器 |
| 人格识别模型 | Hugging Face `Minej/bert-base-personality`（BERT 微调，五维大五人格回归），`transformers` + `torch` 推理，未安装时自动回退中文启发式规则引擎 |
| 中文分词与检索 | `jieba` 分词 + 词粒度交集打分，用于记忆语义检索 |
| 文档处理 | `pypdf` / `python-docx` / `python-pptx` / `openpyxl`，统一清洗、SHA-256 去重、索引 |
| 3D 可视化 | three.js + 3d-force-graph，前端力导向图渲染记忆关系网络 |
| 前端 | 原生 HTML/CSS/JS 控制台（`static/redesign/`），无框架依赖，加载轻量 |
| 联网检索 | searxng / Tavily / Jina Reader 三通道自动故障转移，可选 SSH 中转 |
| 认知引擎 | Python 实现为默认路径，预留 C++ 动态库适配器接口（`cognitive_engine/`），加载失败自动回退 |
| 部署 | Docker + docker-compose（Flask app + PostgreSQL + 可选 searxng），`/health` 健康检查与自动重启 |

## 核心算法与模型

- **记忆抽取引擎**（`memory_runtime/service.py`）：基于正则模式库识别偏好、身份、需求、边界、指令、纠正等六类记忆信号，每类带独立置信度权重；重复出现的记忆会提升置信度并累加 `occurrence_count`，形成"越常提及、系统越确信"的自增强机制；识别到身份/纠正类表达时，旧记忆会被标记为 `superseded` 而非直接删除，保留完整变更历史。
- **语义检索**：中文查询先经 `jieba` 分词，再与记忆内容/证据文本做词粒度交集打分排序，兼顾中英文与数字混排场景。
- **大五人格建模**（`personality_runtime/`）：优先调用 `Minej/bert-base-personality` BERT 模型对对话文本做五维人格回归（开放性/尽责性/外向性/宜人性/神经质），并维护跨会话的观测序列做滑动更新；模型不可用时自动切换到基于关键词与语言风格特征的启发式打分，保证功能连续可用。人格分数不驱动角色扮演，而是映射为具体的督促/扬长策略（`traits.py` 的 coaching playbook）。
- **记忆图谱合成算法**（`memory_runtime/graph.py`）：三层建边策略——同证据来源的记忆聚为 evidence 边、同类目记忆按置信度降序链接为 category 边（限流 40 条/类目，避免 O(n²) 爆炸）、再对全体记忆按置信度排序做保底链式连接（related 边），确保图谱始终连通、无孤立散点，供前端 3D 力导向布局渲染。
- **现实补丁状态机**（`secretary_runtime/`）：项目进展变更强制经过 `Draft → Applied → Rolled Back` 三态流转，每次状态迁移写入审计日志，杜绝 AI 单方面修改用户现实状态。
- **主动思维 Tip 引擎**（`tip_engine/`）：基于对话重复度、风险关键词、论证完整度三类启发式规则触发提示，带每类型独立冷却窗口（默认 900 秒）与用户可关闭开关，避免打扰。

## 快速运行

### 方式一：双击一键启动（推荐）
直接双击运行项目根目录下的 **`start.bat`**：
- 自动检测 Python 环境与 `.env` 配置；
- 启动全功能服务（含统一对话、现实补丁、文档知识库、用户记忆隔离等）；
- 自动在默认浏览器打开前端交互控制台 (`http://127.0.0.1:8091/`)。

### 方式二：命令行运行
```powershell
cd C:\Users\wby15\Desktop\文件\Remedy
python app.py
```

默认监听 `http://127.0.0.1:8091`。没有配置 LLM 时使用本地 fallback responder，记忆、图书馆、秘书和 Tip 仍可完整验证。

## 评委验收测试指南

本项目提供两层测试，评委可以按需选择：**单元测试**（快、验证基础功能不崩）和 **端到端人设化测试**（慢、验证真实业务闭环与核心创新点）。

### 第一层：单元测试（约 2 分钟）

```powershell
cd C:\Users\wby15\Desktop\文件\MyAgentUnified
pip install -r requirements.txt
python -m pytest tests/ -q
```

覆盖认证与用户隔离、记忆抽取、秘书状态机、Web/LLM 优雅降级等核心模块的确定性逻辑，不需要联网或配置 API Key，全部离线可跑，预期输出 `xx passed`。

### 第二层：端到端人设化测试（评委重点验收，约 5-10 分钟）

这是本项目最核心的验收方式——不测试孤立的接口，而是**模拟四种不同职业背景的真实用户**（通用职场人、初中数学教师、计算机大二学生、民商事律师），对着一个正在运行的服务发起真实对话，完整走一遍「记忆沉淀 → 对话创建任务 → 对话触发任务状态切换 → 人格画像滚动更新 → 身份纠正」的业务闭环，并对每一步的真实后端状态做断言（不是简单看回复像不像话，而是查数据库/查看板/查补丁审计是否真的发生了对应变化）。

**运行方式：**

```powershell
# 1. 先启动服务（另开一个终端窗口，保持运行）
python app.py
# 或直接双击 start.bat

# 2. 再开一个终端运行测试脚本
cd C:\Users\wby15\Desktop\文件\MyAgentUnified
python tests/test_persona_scenarios.py
```

只想跑其中一个人设（比如律师）：`python tests/test_persona_scenarios.py lawyer`（`worker` / `teacher` / `student` / `lawyer` 四选一）。脚本每次运行都会自动注册带随机后缀的全新账号，不会与已有数据冲突，可重复运行；未配置 `MODEL_API_KEY` 时会自动降级为本地规则响应器，本脚本关注的确定性逻辑（任务状态机、记忆库、人格模型）在降级模式下同样可以跑通。

**每个人设走一遍下面 21 项断言（4 人设共 84 项）：**

| 阶段 | 验证点 |
|---|---|
| 记忆沉淀 | 自我介绍后身份记忆正确落库 |
| 任务创建 | 对话创建任务 → 生成补丁草稿 → 确认后任务真正入库；项目同步一次性生成多个任务 |
| **对话触发状态切换**（本项目核心创新） | 显式表达（"XX标记为进行中"）、口语化表达（"XX做完了""XX开始做了"，不含"任务"二字也能识别）、受阻场景（"XX卡住了，原因…"）都能精确匹配到对应任务并生效 |
| 幂等保护 | 对已经生效的状态重复下指令，不会产生重复补丁 |
| 异常兜底 | 提到不存在的任务时不会误改任何数据，给出明确提示 |
| **歧义消解**（本项目核心创新） | 两个同名任务时不会瞎猜，而是列出候选并请用户带任务 ID 复述；带上 ID 后能正确消歧并完成切换 |
| 人格画像 | 拖延/情绪/协作类语料会让尽责性等五大特质分数滚动更新，`samples` 计数随交互增长 |
| **身份纠正与记忆 supersede** | "我的名字应该是X，不是Y" 这类纠正表达后，新身份记忆生效、旧记忆被标记为 `superseded`（保留历史而非删除） |
| **系统动作诚实性防线** | 没有实际触发任何秘书动作的普通闲聊，AI 不会编造"已生成补丁/已同步进展"这类未发生的系统行为 |
| 文档检索 | 领域相关的知识库检索请求正常返回 |

脚本会逐条打印 `[PASS]`/`[FAIL]`，全部通过时输出 `全部测试通过`；任意一项失败会在汇总里列出具体是哪一条，方便定位。测试脚本源码见 [`tests/test_persona_scenarios.py`](tests/test_persona_scenarios.py)，可读性即测试方案文档——每个人设的完整对话轮次、期望的任务状态流转，都以 Python 字典明文写在脚本里。

### 手动验收（可选，用于直观感受产品体验）

如果想亲眼看交互效果而不是只看断言结果：
1. 启动服务后打开 `http://127.0.0.1:8091/`，注册一个账号；
2. 在「交互工作台」依次尝试："我叫XX，是XX职业" → "帮我创建一个任务：XX" → 在弹出的补丁审计表点"应用" → 回到对话框说"XX这个任务做完了"；
3. 切到「秘书看板」看任务是否真的从待办移动到了对应泳道，也可以直接在看板卡片的状态下拉框手动切换；
4. 再问一句"你还记得我叫什么吗"验证记忆确实生效。

## 目录

- `unified_agent/`：协议、统一 Agent Core 和响应提供器
- `auth_runtime/`：登录注册、Bearer Token、角色权限（admin / user）
- `storage/`：集中式用户数据库（SQLAlchemy 模型与连接层）
- `memory_runtime/`：用户分区、反馈记忆、画像上下文、`graph.py`（3D 记忆图谱节点/边合成）
- `personality_runtime/`：大五人格识别与秘书督促策略（补短板、扬长处）
- `library_runtime/`：文档解析、净化、索引、检索和引用
- `web_runtime/`：联网搜索与网页读取（searxng / Tavily / Jina Reader，可配 SSH 中转）
- `secretary_runtime/`：项目秘书、现实补丁、审计和回滚
- `tip_engine/`：换角度提示检测与冷却
- `cognitive_engine/`：Python fallback 与可选 C++ 动态库适配器
- `adapters/`：Web/QQ 渠道适配说明和兼容层
- `tools/`：数据迁移等运维脚本
- `docs/ARCHITECTURE.md`：统一架构蓝图
- `docs/PROJECT_INTRO.md` / `docs/Remedy-项目简介.docx`：项目简介（问题、场景、功能、技术方案、创新点、完成情况）
- `docs/DEMO_SCRIPT.md`：演示视频大纲与逐段讲解稿
- `docs/Remedy-项目完全解读.docx`：面向零基础读者的完整说明
- `docs/Remedy-前端控制台接口文档.docx`：控制台操作与 HTTP 接口映射
- `tests/`：核心闭环测试

## 数据库架构（集中库）

所有用户数据统一存放于**一个集中数据库**（不再是每人一个 SQLite 文件）：

| 数据 | 表 | 存储位置 |
|---|---|---|
| 账号 / Token | users / tokens | `data/auth.sqlite3` |
| 用户记忆 / 交互 / 反馈 | memories / interactions / feedback | `data/users.db`（集中库） |
| 大五人格画像 / 观察 | personalities / personality_observations | `data/users.db`（集中库） |
| 秘书看板 / 补丁 / 审计 | Workspace / Task / RealityPatch … | `data/secretary.sqlite3` |
| 知识库索引 | — | `data/library/` |

- 默认使用 SQLite：`DATABASE_URL` 留空时自动落到 `<MYAGENT_DATA_DIR>/users.db`（单文件备份即全量备份）。
- **生产部署（Linux / Docker）**：设置 `DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/myagent` 即切换到 PostgreSQL，所有表结构自动建表，业务代码无需改动。
- 旧版散文件数据可用 `python tools/migrate_to_central_db.py` 一次性迁入集中库（幂等，可 `--dry-run` 预览）。

## 环境变量与模型配置

`MYAGENT_DATA_DIR` 控制数据目录，默认为项目下的 `data`。

复制 `.env.example` 为 `.env` 后填写密钥。默认对接 **DeepSeek 官方 API**：
- `MODEL_API_KEY`: 你的 API Key（不要提交到 Git）
- `BASE_URL`: `https://api.deepseek.com`
- `CURRENT_MODEL`: `deepseek-v4-flash`（或 `deepseek-chat`）

未配置密钥或网络异常时，系统会降级到本地规则响应器，记忆、知识库与补丁流转仍可验证。

可选 C++ 引擎：设置 `COGNITIVE_ENGINE_LIBRARY` 指向共享库；加载失败会自动回退到 Python。

## 联网搜索配置

对话中输入 `!search 关键词`（或包含"搜索/查一下/最新"等词、粘贴 http 链接）会自动触发联网：

- **searxng**（本地实例，推荐）：`SEARXNG_URL=http://localhost:8080/search`，可用 Docker 一键起：`docker run -d -p 8080:8080 searxng/searxng`
- **Tavily**：`TAVILY_API_KEY`（https://app.tavily.com 免费申请）；留空自动尝试读取 `~/.dsh/.credentials.yaml`
- **Jina Reader**：网页正文读取，无需配置
- **SSH 中转**（可选兜底）：设置 `WEB_RELAY_SSH_HOST/USER/KEY` 后，直连被墙时可经境外服务器中转搜索与读网页

搜索通道自动故障转移，全部不可用时消息照常走普通对话。接口见 `API.md` 的 `/v1/web/*`。

## 登录与数据隔离

打开控制台后需先登录。所有用户数据统一落库 `data/users.db`（集中库，按 `user_id` 分区），账户与令牌存在 `data/auth.sqlite3`。

账号说明（Remedy 品牌）：
- 唯一管理员 `remedy_admin` / `Remedy@2025`（或环境变量 `REMEDY_ADMIN_PASSWORD`）：可查看全部用户 `名字/账号/人格雷达 + 聊天检索/删除/标注`，入口 `static/redesign/admin.html`
- 普通用户：通过 `POST /v1/auth/register` 开放注册即 `role=user`，仅可使用助手功能并访问自身记忆；未登录或越权访问他人记忆/`/v1/admin/*` 返回 `401`/`403`
- 旧测试账号 `alice` / `bob` 已彻底移除（`tools/migrate_remove_test_users.py` 幂等清理 `auth.sqlite3` 与 `users.db` 四表），`login alice` 将失败

请求头使用 `Authorization: Bearer <token>`。接口细节见 `API.md` 第 3.16、3.17 节。

## 大五人格与秘书督促

系统会从对话中估计大五人格（开放性、尽责性、外向性、宜人性、神经质），再映射为：
- 更偏理性还是感性
- 执行力强还是容易拖延
- 今天该督促什么、该发挥什么长处

这不是让 Agent 用某种人格说话，也不是心理诊断。优先使用 Hugging Face 上的 `Minej/bert-base-personality`；未安装 `torch`/`transformers` 时自动用中文启发式。可在 `.env` 设置 `PERSONALITY_DISABLE_BERT=1` 强制跳过模型下载。

## 3D 记忆图谱

控制台「记忆图谱」Tab（`GET /v1/users/<user_id>/memory/graph`）把用户的记忆实时合成为节点/边结构并做 3D 可视化：

- **evidence 边**：同一段证据文本衍生出的多条记忆之间连线
- **category 边**：同类目记忆按置信度链式连接（限流避免大类目下 O(n²) 连接数）
- **related 保底边**：为避免出现完全孤立的散点，按置信度把所有记忆串成一条链兜底

前端基于 three.js + 3d-force-graph（`static/redesign/vendor/`）渲染，可拖拽旋转、点击节点查看详情。普通用户仅能查看自身图谱，越权访问返回 `403`。

## Linux / Docker 部署（生产）

项目自带 `Dockerfile` 与 `docker-compose.yml`，面向 Linux 服务器一键部署：

```bash
# 1. 上传项目（排除 .env 内的密钥，可只传代码 + 新建 .env）
# 2. 复制配置模板并填写密钥
cp .env.example .env
# 3. 构建并启动（app + PostgreSQL 集中库；searxng 需要时用 --profile search）
docker compose up -d --build
# 4. 大量使用联网搜索时再启动 searxng 通道
docker compose --profile search up -d
```

- **数据库**：compose 自动拉起 PostgreSQL 16，应用通过 `DATABASE_URL` 连接，全用户数据落在一个 PG 库中；数据卷 `pg_data` 持久化，`docker volume` 即可备份/迁移。
- **镜像说明**：默认安装精简依赖（不含 torch），人格走启发式，镜像约 300MB；需要 BERT 人格时构建加参数：`docker compose build --build-arg WITH_AI=1 app`。
- **健康检查**：`/health` 每 30s 探测，异常自动重启（restart: unless-stopped）。
- **迁移旧数据**：容器内执行 `docker compose exec app python tools/migrate_to_central_db.py` 可把旧 per-user 文件迁入集中库（本地在 `data/` 卷内）。
- **升级**：`docker compose pull && docker compose up -d`。
- 容器外直接用 Python 运行时（`python app.py`）不依赖 Docker，开发调试保持原样。
