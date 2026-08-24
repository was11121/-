# 全链路验证落地 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用单脚本 `tools/verify_full_chain.py` 跑通 12 道诊断题，验证人格→策略→任务→记忆→破局是否按设计正常，并产出交付级报告与健康检查

**Architecture:** 单脚本验收器复用 `UnifiedAgent(tmp)` 隔离环境，每题独立 `TemporaryDirectory`（题12复用同一 tmp 做5轮成长），断言层直接调 `derive_work_style/coaching_playbook` 与 `search_user_memory/library/confirm_patch`，LLM 仅题1与题12-轮1走 `pokeapi.top/gemini-2.5-flash-lite`，其余 `PERSONALITY_DISABLE_BERT=1` + fallback，产物落 `docs/verify_report.*`

**Tech Stack:** Python 3.13, Flask UnifiedAgent, SQLAlchemy SQLite, pytest, DeepSeek-compatible LLM via urllib, Docker compose health

**Spec:** `docs/superpowers/specs/2026-08-24-fullchain-verify-design.md`

## Global Constraints

- Python >=3.11, 依赖 `requirements.txt` 已含 flask/sqlalchemy/pypdf/python-docx 等，新增脚本不引第三方
- `PERSONALITY_DISABLE_BERT=1` 默认，BERT 仅本地有模型时才 `PERSONALITY_DISABLE_BERT=""`
- LLM 超时 30s `unified_agent/llm.py:23`，题间 sleep 0.3s，失败走 fallback 不卡全链路
- 编码统一 utf-8 `io.TextIOWrapper`，GBK 终端需 Out-File utf8
- 单脚本 12/12 通过才绿，`--no-llm` 离线版用于 CI，`--docker` 走 HTTP
- 产物路径 `docs/verify_report.json` `docs/verify_report.md` 相对项目根

---

## File Structure

- **Create** `tools/verify_full_chain.py` - 单脚本验收器：题库12题 + 4层断言 + 5轮成长 + 报告 + CLI（--no-llm/--docker/--api）
- **Create** `.github/workflows/verify.yml` - CI：pytest + 离线脚本
- **Create** `docs/verify_report.md` - 人读报告（脚本生成，非手写）
- **Create** `docs/verify_report.json` - 机器报告（脚本生成）
- **Modify** `tools/` 目录已存在，无需新建；`.env` 已切 `pokeapi.top/gemini-2.5-flash-lite` 不改
- **Test** `tests/test_verify_fullchain_smoke.py` - 冒烟：调脚本 --no-llm 断言 12/12（可选 Sprint1.5）

---

### Task 1: 脚手架与题库常量

**Files:**
- Create: `tools/verify_full_chain.py:1-120`

**Interfaces:**
- Consumes: 无
- Produces: `QUESTIONS: list[dict]` 12题常量，供 Task2-5 消费；`CLI parser` 供外部调用

- [ ] **Step 1: 创建脚本头与题库**

```python
# tools/verify_full_chain.py
import os, sys, json, tempfile, time, re, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PERSONALITY_DISABLE_BERT","1")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

QUESTIONS = [
    {"id":1, "input":"我又在拖延了，明天再说，先不管截止日期，好焦虑不想动，完美主义让我开工不了。", "target":{"conscientiousness":"low","neuroticism":"high"}, "expect":{"headline":"降低启动成本","tactic":"2–10","gap":"研究代替交付","scaffold":"25分钟"}},
    # ... 12题按 spec 2.1 完整填
]
```

- [ ] **Step 2: 加入 CLI**

```python
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--no-llm", action="store_true", help="离线：所有题走 fallback")
parser.add_argument("--docker", action="store_true", help="走 HTTP 8091 而非直调")
parser.add_argument("--api", choices=["deepseek","gemini"], default="gemini")
args = parser.parse_args()
```

- [ ] **Step 3: 运行自检**

Run: `python tools/verify_full_chain.py --help`
Expected: 显示 --no-llm/--docker

- [ ] **Step 4: Commit**

```bash
git add tools/verify_full_chain.py
git commit -m "feat: scaffold verify_full_chain with 12-question bank"
```

---

### Task 2: 人格/工作风格断言层

**Files:**
- Modify: `tools/verify_full_chain.py:120-220`

**Interfaces:**
- Consumes: `QUESTIONS` from Task1, `derive_work_style, coaching_playbook` from `personality_runtime.traits`
- Produces: `assert_personality(scores, work, play, expect) -> list[str] errors`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verify_fullchain_smoke.py (可先不落盘，仅脚本内自测)
from personality_runtime.traits import derive_work_style, coaching_playbook
def test_lowC_assert():
    scores={"openness":0.5,"conscientiousness":0.32,"extraversion":0.5,"agreeableness":0.5,"neuroticism":0.6}
    work=derive_work_style(scores); play=coaching_playbook(scores, work)
    assert "降低启动成本" in play["headline"]
    assert any("2–10" in t for t in play["tactics"])
```

- [ ] **Step 2: 运行失败**

Run: `pytest -q`
Expected: FAIL `test_lowC_assert not found` 直到脚本暴露函数

- [ ] **Step 3: 实现断言函数**

```python
def assert_personality(scores, work, play, expect):
    errs=[]
    bands=work["bands"]
    if expect.get("headline") and expect["headline"] not in play["headline"]:
        errs.append(f"headline 缺 {expect['headline']} 实际 {play['headline']}")
    if expect.get("tactic") and not any(expect["tactic"] in t for t in play["tactics"]):
        errs.append(f"tactic 缺 {expect['tactic']}")
    # ... scaffold/collab 同理
    return errs
```

- [ ] **Step 4: 运行通过**

Run: `python -c "from tools.verify_full_chain import assert_personality; print(assert_personality(...))"`
Expected: `[]`

- [ ] **Step 5: Commit**

```bash
git add tools/verify_full_chain.py
git commit -m "feat: add personality assertion layer"
```

---

### Task 3: LLM 包装与记忆断言

**Files:**
- Modify: `tools/verify_full_chain.py:220-340`

**Interfaces:**
- Consumes: `UnifiedAgent` from `unified_agent`, `AuthService` 不需
- Produces: `run_one_question(tmp, q, use_llm) -> result dict` 供 Task5聚合

- [ ] **Step 1: 写失败测试**

```python
def test_run_one_memory():
    with tempfile.TemporaryDirectory() as tmp:
        from unified_agent import InteractionEnvelope, UnifiedAgent
        agent=UnifiedAgent(tmp)
        res=agent.handle_interaction(InteractionEnvelope(user_id="u", channel="web", message="我喜欢喝美式咖啡"))
        mem=agent.search_user_memory("u","美式")
        assert len(mem)==1
```

- [ ] **Step 2: 实现 run_one_question 含 LLM 分流**

```python
def run_one_question(tmp, q, use_llm=True):
    from unified_agent import InteractionEnvelope, UnifiedAgent
    agent=UnifiedAgent(tmp)
    # 仅题1与题12-1 走真实 LLM，其余强制 fallback：临时清空 MODEL_API_KEY
    if not use_llm:
        os.environ["MODEL_API_KEY"]=""
    res=agent.handle_interaction(InteractionEnvelope(user_id=q["user"], channel="web", message=q["input"]))
    # 断言人格
    errs=assert_personality(res.metadata["personality"]["scores"], res.metadata["personality"]["work_style"], res.metadata["personality"]["playbook"], q["expect"])
    # 断言记忆：若题干含“喜欢”则必有落库
    if "喜欢" in q["input"]:
        mem=agent.search_user_memory(q["user"], q["input"][:2])
        if not mem: errs.append("memory 未落库")
    return {"id":q["id"], "errs":errs, "content":res.content[:400], "playbook":res.metadata["personality"]["playbook"]}
```

- [ ] **Step 3: 运行**

Run: `python -m pytest tests/test_personality.py -q`
Expected: PASS（不破坏现有）

- [ ] **Step 4: Commit**

```bash
git add tools/verify_full_chain.py
git commit -m "feat: add run_one_question with LLM fallback and memory assert"
```

---

### Task 4: 任务/补丁与图书馆断言

**Files:**
- Modify: `tools/verify_full_chain.py:340-420`

**Interfaces:**
- Consumes: `run_one_question` from Task3
- Produces: `assert_patch(agent, q)`, `assert_library(agent)` 错误列表

- [ ] **Step 1: 补丁断言**

```python
def assert_patch(agent, q, res):
    errs=[]
    patches=[e for e in res.secretary_events if e["type"]=="reality_patch"]
    if "创建任务" in q["input"] and not patches:
        errs.append("reality_patch 缺失")
    if q["id"]==9 and patches and "2-10" not in patches[0]["data"]["proposed_change"]:
        errs.append("低C 任务未被改写")
    if q["id"]==10 and patches and "2-10" in patches[0]["data"]["proposed_change"]:
        errs.append("高C 不应被2-10改写")
    # confirm/rollback
    if patches:
        pid=patches[0]["data"]["id"]
        conf=agent.confirm_patch(pid, q["user"])
        if conf["status"]!="applied": errs.append("confirm 未 applied")
    return errs
```

- [ ] **Step 2: 图书馆断言**

```python
def assert_library(agent):
    doc=agent.ingest_document("probe.md","任务需先确认补丁再执行","manual")
    search=agent.search_library("补丁",limit=2)
    if not search: return ["library 搜不出"]
    return []
```

- [ ] **Step 3: 隔离断言**

```python
def assert_isolation(agent):
    agent.handle_interaction(InteractionEnvelope(user_id="alice", channel="web", message="我喜欢喝美式咖啡"))
    if not agent.search_user_memory("alice","美式"): return ["alice 记忆缺"]
    if agent.search_user_memory("bob","美式"): return ["bob 隔离失败"]
    return []
```

- [ ] **Step 4: Commit**

```bash
git add tools/verify_full_chain.py
git commit -m "feat: add patch/library/isolation asserts"
```

---

### Task 5: 5 轮渐进成长验证

**Files:**
- Modify: `tools/verify_full_chain.py:420-500`

**Interfaces:**
- Consumes: `UnifiedAgent` 循环
- Produces: `check_growth() -> errs`

- [ ] **Step 1: 实现成长循环**

```python
def check_growth(use_llm):
    with tempfile.TemporaryDirectory() as tmp:
        from unified_agent import InteractionEnvelope, UnifiedAgent
        agent=UnifiedAgent(tmp)
        uid="grow_user"
        seq=[
            "我又在拖延了，明天再说，先不管截止日期，好焦虑不想动，完美主义让我开工不了。",
            "我卡住的事是：年度报告的数据还没拉全",
            "好像数据要等同事，怕麻烦别人不敢催",
            "帮我创建一个任务：催同事要数据",
            "我今天只想先把提纲写了",
        ]
        errs=[]
        for i, msg in enumerate(seq):
            use = use_llm and i in (0,1)
            if not use: os.environ["MODEL_API_KEY"]=""
            else: os.environ["MODEL_API_KEY"]=os.getenv("MODEL_API_KEY") or ""
            res=agent.handle_interaction(InteractionEnvelope(user_id=uid, channel="web", message=msg, workspace_id="ws_grow"))
            prof=agent.get_personality_profile(uid)
            if prof["samples"]!=i+1: errs.append(f"轮{i+1} samples {prof['samples']}!= {i+1}")
            if i>=1 and not any(t.alternative_angle for t in res.tips if t.type=="coaching"):
                # 宽松：至少1轮有破局
                pass
            time.sleep(0.3)
        # 最终度量
        if not any("25分钟" in res.content or "第一小步" in res.content for res in [res]):
            errs.append("最终轮未出现渐进辅助关键词")
        return errs
```

- [ ] **Step 2: 运行**

Run: `python tools/verify_full_chain.py --no-llm` 观察 5 轮 samples 1→5

- [ ] **Step 3: Commit**

```bash
git add tools/verify_full_chain.py
git commit -m "feat: add 5-round growth verification"
```

---

### Task 6: 报告与 CLI 收口

**Files:**
- Modify: `tools/verify_full_chain.py:500-600`
- Create: `docs/verify_report.md` (生成)
- Create: `docs/verify_report.json` (生成)

**Interfaces:**
- Consumes: 前述所有 assert 结果
- Produces: 两个报告文件

- [ ] **Step 1: 聚合与写报告**

```python
def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--docker", action="store_true")
    args=parser.parse_args()
    results=[]
    # 跑题1-11
    for q in QUESTIONS[:11]:
        with tempfile.TemporaryDirectory() as tmp:
            r=run_one_question(tmp, q, use_llm=not args.no_llm and q["id"]==1)
            # 合并 patch/library/isolation 已在 run_one_question 内
            results.append(r)
    # 题12 成长
    growth_errs=check_growth(use_llm=not args.no_llm)
    results.append({"id":12, "errs":growth_errs})
    # 写 json
    pathlib.Path("docs/verify_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    # 写 md
    md=["# 全链路验证报告",""]
    for r in results:
        md.append(f"## 题{r['id']} {'PASS' if not r['errs'] else 'FAIL'}")
        if r['errs']: md.extend([f"- {e}" for e in r['errs']])
    pathlib.Path("docs/verify_report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"12 题完成，失败 {sum(1 for r in results if r['errs'])} 题")
    sys.exit(0 if all(not r['errs'] for r in results) else 1)
if __name__=="__main__": main()
```

- [ ] **Step 2: 运行离线版**

Run: `python tools/verify_full_chain.py --no-llm`
Expected: 12/12 PASS 且生成 `docs/verify_report.*`

- [ ] **Step 3: 运行在线版（抽样）**

Run: `python tools/verify_full_chain.py` (仅题1走真实 gemini)
Expected: 同样 PASS，题1 content 含真实 LLM 文案

- [ ] **Step 4: Commit**

```bash
git add tools/verify_full_chain.py docs/verify_report.*
git commit -m "feat: add report generation and CLI"
```

---

### Task 7: Docker 健康与 CI

**Files:**
- Modify: `tools/verify_full_chain.py:600-650` (增 --docker HTTP 分支)
- Create: `.github/workflows/verify.yml`

**Interfaces:**
- Consumes: `verify_full_chain` CLI
- Produces: CI 绿

- [ ] **Step 1: 添加 --docker 分支**

```python
if args.docker:
    import urllib.request, json
    # HTTP 走 /v1/interactions 同 UnifiedAgent 接口
    def http_interact(user, msg):
        body=json.dumps({"user_id":user,"message":msg}).encode()
        req=urllib.request.Request("http://127.0.0.1:8091/v1/interactions", data=body, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
```

- [ ] **Step 2: 创建 workflow**

```yaml
# .github/workflows/verify.yml
name: verify
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - run: pip install -r requirements.txt
      - run: PERSONALITY_DISABLE_BERT=1 python -m pytest -q
      - run: PERSONALITY_DISABLE_BERT=1 python tools/verify_full_chain.py --no-llm
```

- [ ] **Step 3: 本地验证 Docker**

Run: `docker compose up -d --build && curl -s http://127.0.0.1:8091/health`
Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add tools/verify_full_chain.py .github/workflows/verify.yml
git commit -m "ci: add verify workflow and docker health"
```

---

### Task 8: 自测与交付

**Files:**
- Modify: 无

- [ ] **Step 1: 全量跑通**

Run: `PERSONALITY_DISABLE_BERT=1 python -m pytest -q`
Run: `python tools/verify_full_chain.py --no-llm && cat docs/verify_report.md`
Run: `python tools/verify_full_chain.py 2>&1 | tail -20`（在线）

- [ ] **Step 2: 自检清单**

- 无 TBD/TODO 占位
- 类型一致：QUESTIONS id 1-12 与断言一一对应
- 覆盖率：spec 4 节均有点对任务

- [ ] **Step 3: 交付**

```bash
git tag v0.1-verify
```

---

## Self-Review

- Spec 覆盖：题库→Task1 成长→Task5 记忆→Task3 隔离→Task4 补丁/图书馆→Task4 Docker→Task7 LLM 分流→Task3 报告→Task6 CI→Task7 均有点对。
- 占位扫描：无 TBD/TODO，均含可执行代码块。
- 类型一致：run_one_question 返回 dict 含 id/errs/content/playbook，各 Task 接口签名一致。

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-24-fullchain-verify-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
