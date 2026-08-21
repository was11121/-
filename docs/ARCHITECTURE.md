# 现实补丁 Agent 统一产品架构

本文档描述一个统一 Agent 产品：以用户隔离的反馈记忆为底座，通过 Web 与 QQ 两个入口，提供 AI 图书馆、文档处理、项目秘书、现实补丁和主动思维提示。

## 产品原则

- 一个 Agent Core，渠道只是适配器。
- 每个用户独立分区，个人记忆不跨用户共享。
- 任何改变现实状态的动作先形成补丁，经过确认后再执行。
- 知识先净化、可追溯，再参与回答。
- C++ 只作为可插拔计算加速层，缺失时 Python fallback 必须可用。

## 运行架构

```text
Web Adapter ----\
                 > Interaction Gateway -> Unified Agent Core
QQ/NapCat Adapter/
                         |
      +------------------+------------------+
      |                  |                  |
 Memory Runtime     Library Runtime     Secretary Runtime
      |                  |                  |
 User Partition     Document Pipeline   Reality Patch
      +------------------+------------------+
                         |
                 Feedback / Tip Engine
                         |
                 LLM + Tools + Optional C++
```

## 统一交互协议

`InteractionEnvelope` 是所有渠道进入核心的唯一输入格式：

```json
{
  "user_id": "user-1",
  "channel": "web",
  "conversation_id": "conv-1",
  "workspace_id": "workspace-1",
  "message": "把刚才的讨论整理成任务",
  "attachments": [],
  "timestamp": "2026-08-20T12:00:00+08:00",
  "permissions": ["read_memory", "propose_patch"],
  "context": {}
}
```

`ResponseEnvelope` 统一承载文本、媒体、引用、记忆事件、秘书事件、Tip 和确认要求。

## Memory Runtime

每个用户的 `UserPartition` 至少包含 identity、preferences、dislikes、needs、boundaries、corrections、topics、style、relationship、interaction_history 和 feedback_history。

记忆闭环为：交互记录 -> 候选提取 -> 去重/置信度/时间衰减 -> 自动保存或用户反馈 -> 更新画像和关系 -> 下一次相关检索。

反馈类型：`confirm`、`correct`、`reject`、`forget`、`prefer_style`、`change_preference`。

个人记忆默认本地隔离。共享空间只接收公开知识或经过确认的秘书记录。

## Personality Runtime

人格模块估计大五人格，只服务于秘书督促：补短板、扬长处。禁止用人格去改变 Agent 口吻或扮演用户。

默认编码器为 Hugging Face `Minej/bert-base-personality`（BERT 文本分类，输出外向性、神经质、宜人性、尽责性、开放性）。中文或未安装权重时与启发式混合。映射包括理性/感性倾向、执行/拖延倾向，以及当日可执行的督促动作。

## Library Runtime

图书馆流水线为：格式识别 -> 文本/表格/页码提取 -> 净化 -> 去重 -> 来源和时间标记 -> 分块 -> 关键词/向量索引 -> 检索 -> 引用。

首版支持 PDF、DOCX、PPTX、XLSX、Markdown、TXT、CSV 和 JSON。文档解析由 `DocumentProcessor` 适配器提供；索引层不依赖具体解析器。

净化规则包括重复检测、过期标记、事实/观点/推测区分、来源保留、敏感信息检测、人工纠正、下架恢复和引用回溯。

## Secretary Runtime 和 Reality Patch

秘书核心实体为 Workspace、Project、Member、Update、Task、Decision、Risk、SyncSession、RealityPatch 和 AuditEvent。

所有现实变更遵循：`draft -> review -> confirm -> apply -> audit -> rollback`。未经确认的补丁永远不会写入正式任务、决策或外部系统。

秘书支持进展同步、任务认领/完成/阻塞、决策和风险、截止提醒、早晚报、四日倒计时、GitHub 只读状态、复盘导出和撤销。

## Tip Engine

TipEngine 检测重复确认、单一来源、对立僵局、抽象停留、任务阻塞、忽略风险、事实冲突和主题漂移，输出可关闭、带置信度和冷却时间的方向提示。Tip 不覆盖主回答，用户采纳或拒绝会进入反馈记忆。

## Optional Cognitive Engine

Python 是默认运行时。`CognitiveEngine` 可由 C++ 动态库或 sidecar 实现，用于文本特征、新颖度、反馈评分、关系计算和方向偏移检测。所有调用都有 Python fallback，并通过固定结构化接口交换结果。第三方 Soar/OpenCog 等候选必须另行完成许可证、维护状态、API 和部署评估。

## 接口

```text
POST /v1/interactions
POST /v1/interactions/stream
POST /v1/feedback
GET  /v1/users/{user_id}/memory
POST /v1/users/{user_id}/memory/{memory_id}/forget
POST /v1/library/documents
GET  /v1/library/search
POST /v1/workspaces/{workspace_id}/sync
POST /v1/patches/{patch_id}/confirm
POST /v1/patches/{patch_id}/rollback
GET  /v1/workspaces/{workspace_id}/dashboard
```

QQ 适配器只暴露 `/qq`、`/health` 和 `/voice/{user_key}`，不得在适配器内复制 Agent 业务逻辑。

## 迁移策略

原项目保持不变。新项目只抽取 Agent Core、记忆、关系、知识库、文档处理、群秘书状态机和必要适配器，并通过兼容层保留 `run_agent`、`run_agent_simple`、`ingest_interaction`、`search_memories`、`search_knowledge` 等旧调用名。

迁移顺序：核心协议 -> 记忆底座 -> Web/QQ 适配 -> 图书馆和文档 -> 秘书和现实补丁 -> TipEngine -> C++ 加速层 -> 数据导入和并行验证。

## 验收重点

- 用户之间记忆完全隔离，跨 Web/QQ 入口一致。
- 记住、纠正、拒绝、忘记均可验证。
- 文档可解析、净化、去重、检索并返回引用。
- 秘书草稿需确认后才正式写入，补丁可审计和回滚。
- Tip 不打断主回复，具备冷却和反馈闭环。
- 无 C++ 环境时完整功能仍可运行。
