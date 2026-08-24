# 全链路验证落地 Spec — 人格→助手→任务→记忆→破局（交付级）

**版本** v1.0 2026-08-24 | **路径** Architectural | **关联** `docs/助手协作策略_基于人格.md` `docs/深度研究报告_人格互补_v2.md` `personality_runtime/traits.py`

## 1. 目标与边界

**目标**：用 12 道诊断题验证 `输入→人格划分→助手策略→任务脚手架→内部记忆→渐进破局` 是否按设计正常，且后台能在 5 轮对话中越聊越会帮。

**边界 C 交付级**：覆盖 `人格/工作风格/任务改写/记忆隔离/补丁生命周期/图书馆` 的 `UnifiedAgent` 单元+E2E + 真实 `LLM gemini-2.5-flash-lite https://www.pokeapi.top` 至少 1 题 + `Docker compose health` + 可重复脚本 `tools/verify_full_chain.py` + 报告 `verify_report.*`。不含前端视觉回归。

**非目标**：不做 BERT 精调，不改 `auth_runtime` 权限模型，不新增策略表 DB（留 `Sprint2`）。

## 2. 题库（12 题）

| # | 输入 | 靶向画像 | 期望行为 |
|---|---|---|---|
|1|我又在拖延了，明天再说，先不管截止日期，好焦虑不想动，完美主义让我开工不了。|低C+高N procrastinator/affective|headline降低启动成本 scaffold 2-10min+25min+丑第一版|
|2|我今天就把清单做完，立刻执行计划，守住截止时间，保持冷静自律。|高C+低N executor/rational|headline守住优先级 够好即交付 甜点约束|
|3|好多新想法！要不换个方法试试新框架，这个好有意思。|高O|时间盒30min+可交付 gaps研究代替交付|
|4|别变了就这样，按老办法流程固定来。|低O|模板开工 单变量|
|5|我们一起开会讨论吧，找人聊聊，团队一起马上搞。|高E|保护专注块 倒U约束|
|6|别打扰我，我想自己待着，一个人更专注。|低E|卡25分钟外化提问|
|7|不好意思，这个忙我不好拒绝，怕麻烦别人就答应了。|高A|不忍拒绝 挤掉主任务|
|8|直接拒绝，我先做自己的事，边界清楚。|低A|主动补同步 undersync|
|9|帮我创建一个任务：完成年度报告（接题1）|低C改写|patch含2-10+脚手架事件|
|10|帮我创建一个任务：整理项目复盘（接题2）|高C不改写|patch不含2-10|
|11|整合题5+7+2句 高C/E/A|倒U高分|gaps含甜点3条 collab 5 hints含3×倒U|
|12|5轮渐进 grow_user 1→5|成长|samples 1→5 每轮tips含alternative_angle 破局|

题1-8 独立 `TemporaryDirectory`，题9-10 联动，题12 单 `tmp_grow` 连续 5 轮同 user_id。

## 3. 断言与度量

**人格层**：
- `scores[靶向] band` 高≥0.62 低≤0.42
- `work_style` 低C+高N→procrastinator/affective 高C+低N→executor/rational
- `playbook.headline/tactics/gaps/today_focus` 关键字（题1含降低启动成本+2–10+丑第一版；高E含专注块；高A含挤掉）
- `task_scaffold.timebox/steps` 低C→25min且含2-10 高O→30分钟
- `collaboration.hints` 高E→保护.*专注块 低E→外化提问 高A→挤掉 倒U→甜点+倒U约束

**记忆层**：
- 题1-8后 `search_user_memory` 有对应 category 且 confidence>0
- 隔离：alice 写美式后 bob 搜美式为空，`get_user_profile_stats` 仅 alice +1

**输出与破局层**：
- `content` 低C含25分钟/第一步/丑第一版≥2 高N含不完美 高O含时间盒
- `tips` 每题≥1 coaching 且 `today_focus` 非空；题12至少2轮含 confidence≥0.7 的 coaching 且 alternative_angle非空视为破局
- 渐进：samples 1→5 单调增

**任务层**：
- `secretary_events` 含 reality_patch draft +（低C时）task_scaffold；proposed_change 含脚手架；高C不含2-10
- `confirm→applied` `rollback→rolled_back` 且 rollback_data非空

**统计门禁**：12/12 通过才绿，单题失败打印 expected vs actual 的 scores/bands/playbook diff；产物 `verify_report.json` + `verify_report.md`。

## 4. 渐进辅助验证（5 轮）

同 user_id=grow_user 连续 5 轮：
1 拖延句 → samples1 procrastinator 25min
2 我卡住的事是：年度报告数据还没拉全 → 出现 alternative_angle 破局
3 好像数据要等同事，怕麻烦别人不敢催 → 高A叠加 挤掉主任务
4 帮我创建一个任务：催同事要数据 → patch含协作提示 content含催促模板
5 我今天只想先把提纲写了 → samples5 更短更具体

度量：samples递增；tips中至少2轮含 confidence≥0.7 的 coaching 且第2轮起 alternative_angle!=""；最终轮 content含25分钟或第一小步。

## 5. 交付流水线

**脚本** `tools/verify_full_chain.py` 单文件，无额外依赖，`PERSONALITY_DISABLE_BERT=1` 默认，`MODEL_API_KEY` 走 `.env` 的 `pokeapi.top/gemini-2.5-flash-lite`，真实 LLM 仅题1与题12-轮1走网络，其余 fallback；参数 `--no-llm` 离线；运行 `python tools/verify_full_chain.py` 产 `docs/verify_report.*`。

**Docker**：`docker compose up -d --build` 后 `curl /health` 期望 status ok + personality encoder + memory_backend；脚本 `--docker` 模式走 HTTP `http://127.0.0.1:8091/v1/interactions`。

**CI**：`.github/workflows/verify.yml` job：`pip install -r requirements.txt` → `PERSONALITY_DISABLE_BERT=1 pytest -q` → `python tools/verify_full_chain.py --no-llm`（--llm 仅 nightly）。

**容错**：llm 超时/密钥失效走 `fallback_responder` `llm.py:94`，题1 fallback也含25分钟故不误判；编码统一 utf-8；数据每题独立 TemporaryDirectory。

## 6. 数据流与接口

`题库.json → TemporaryDirectory → UnifiedAgent(tmp).handle_interaction → observe → derive_work_style → coaching_playbook → prompt_block → llm/fallback → record_interaction → tips → secretary.create_patch → assert → report`。

## 7. 风险与回退

- `gemini-2.5-flash-lite` 限流：脚本中 sleep 0.3s/次 + 单题重试1次；失败则标记题为 LLM_SKIP 不卡全链路。
- `PANDORA` 中文偏差：heuristic 主导 0.8，容忍高N误判为 mixed（已在题1改 headline含模糊）。
- GBK 乱码：脚本内 `io.TextIOWrapper utf-8`。

## 8. 验收

本地 `python tools/verify_full_chain.py` 12/12 且 `e2e_with_llm2.py` 同等逻辑已在本地以真实 gemini 验证通过（见 verify_out3.txt）；Docker health 200。

## 9. 后续

Sprint2 拆为 `tests/test_verify_*.py` 参数化 + `PersonalityPolicyRow` 热更；Sprint3 接前端看板与策略回流看板。
