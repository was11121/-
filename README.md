# 现实补丁 Agent

这是从 `MyAgent重构` 抽取出来的独立统一 Agent 骨架。原项目保持不变。本项目以本地隔离的反馈记忆为底座，统一 Web/QQ 入口，并提供 AI 图书馆、文档处理、AI 秘书、现实补丁和主动思维 Tip。

## 快速运行

### 方式一：双击一键启动（推荐）
直接双击运行项目根目录下的 **`start.bat`**：
- 自动检测 Python 环境与 `.env` 配置；
- 启动全功能服务（含统一对话、现实补丁、文档知识库、用户记忆隔离等）；
- 自动在默认浏览器打开前端交互控制台 (`http://127.0.0.1:8091/`)。

### 方式二：命令行运行
```powershell
cd C:\Users\wby15\Desktop\文件\MyAgentUnified
python app.py
```

默认监听 `http://127.0.0.1:8091`。没有配置 LLM 时使用本地 fallback responder，记忆、图书馆、秘书和 Tip 仍可完整验证。

## 目录

- `unified_agent/`：协议、统一 Agent Core 和响应提供器
- `auth_runtime/`：登录注册、Bearer Token、角色权限（admin / user）
- `memory_runtime/`：用户分区、反馈记忆、画像上下文
- `personality_runtime/`：大五人格识别与秘书督促策略（补短板、扬长处）
- `library_runtime/`：文档解析、净化、索引、检索和引用
- `web_runtime/`：联网搜索与网页读取（searxng / Tavily / Jina Reader，可配 SSH 中转）
- `secretary_runtime/`：项目秘书、现实补丁、审计和回滚
- `tip_engine/`：换角度提示检测与冷却
- `cognitive_engine/`：Python fallback 与可选 C++ 动态库适配器
- `adapters/`：Web/QQ 渠道适配说明和兼容层
- `docs/ARCHITECTURE.md`：统一架构蓝图
- `docs/MyAgentUnified-项目完全解读.docx`：面向零基础读者的完整说明
- `docs/MyAgentUnified-前端控制台接口文档.docx`：控制台操作与 HTTP 接口映射
- `tests/`：核心闭环测试

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

打开控制台后需先登录。记忆按用户落在独立 SQLite 文件 `data/users/<user_id>/memory.sqlite3`，账户与令牌存在 `data/auth.sqlite3`。

默认账号：
- 管理员 `admin` / `admin123`：可查看全部用户列表与个人画像
- 普通用户 `alice` / `123456`、`bob` / `123456`：仅可使用助手功能并访问自身记忆

请求头使用 `Authorization: Bearer <token>`。普通用户访问他人记忆或 `/v1/admin/*` 会返回 `403`。接口细节见 `API.md` 第 3.16、3.17 节。

## 大五人格与秘书督促

系统会从对话中估计大五人格（开放性、尽责性、外向性、宜人性、神经质），再映射为：
- 更偏理性还是感性
- 执行力强还是容易拖延
- 今天该督促什么、该发挥什么长处

这不是让 Agent 用某种人格说话，也不是心理诊断。优先使用 Hugging Face 上的 `Minej/bert-base-personality`；未安装 `torch`/`transformers` 时自动用中文启发式。可在 `.env` 设置 `PERSONALITY_DISABLE_BERT=1` 强制跳过模型下载。
