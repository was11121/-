"""大五人格工作学映射：用于秘书督促，而不是让 Agent 扮演某种性格。

依据工业与组织心理学中较稳定的结论（Barrick & Mount 1991 工作绩效；
Steel 2007 拖延元分析；Bell 2007 团队 meta；Curșeu 2018 倒U；Roberts 2017 可塑性）：
- 尽责性是执行力/反拖延的最强正向指标；
- 神经质升高时情绪波动与回避上升；
- 开放性升高时探索欲强但易发散；
- 外向性/宜人性/尽责性与团队贡献呈倒U，峰值在中等偏上而非极值；
- 人格 12-24 周可经微干预产生 d≈0.3 可塑。
本模块不做临床诊断，输出仅用于秘书该「督促什么、发扬什么」。
"""

from __future__ import annotations

from typing import Any


TRAITS: dict[str, dict[str, str]] = {
    "openness": {
        "id": "openness",
        "zh": "开放性",
        "en": "Openness",
        "meaning": "对新想法、学习和变化的兴趣。高分好奇爱探索，低分偏好熟悉流程。",
    },
    "conscientiousness": {
        "id": "conscientiousness",
        "zh": "尽责性",
        "en": "Conscientiousness",
        "meaning": "计划、自律、把事情做完的倾向。高分执行力强，低分更容易拖延。",
    },
    "extraversion": {
        "id": "extraversion",
        "zh": "外向性",
        "en": "Extraversion",
        "meaning": "从人际互动中获取能量的程度。高分爱协作讨论，低分擅长深度独处。",
    },
    "agreeableness": {
        "id": "agreeableness",
        "zh": "宜人性",
        "en": "Agreeableness",
        "meaning": "合作、体贴、不愿冲突的程度。高分好协作但难拒绝，低分独立但可能少同步。",
    },
    "neuroticism": {
        "id": "neuroticism",
        "zh": "神经质 / 情绪波动",
        "en": "Neuroticism",
        "meaning": "焦虑、压力敏感和情绪起伏。高分易内耗回避，低分压力下更稳、更偏理性。",
    },
}

TRAIT_ORDER = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]

# Minej/bert-base-personality 输出顺序（模型卡）
MINEJ_LABELS = ["extraversion", "neuroticism", "agreeableness", "conscientiousness", "openness"]

HIGH = 0.62
LOW = 0.42
# 团队贡献甜点（倒U峰）约 0.55±0.10，超出需加约束而非激励
SWEET_PEAK = 0.55
SWEET_WIDTH = 0.20


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def band(score: float) -> str:
    if score >= HIGH:
        return "high"
    if score <= LOW:
        return "low"
    return "mid"


def _in_sweet_zone(score: float) -> bool:
    return abs(score - SWEET_PEAK) <= SWEET_WIDTH / 2


def derive_work_style(scores: dict[str, float]) -> dict[str, Any]:
    """把五大分数转成秘书能用的工作风格，而不是角色口吻。"""
    c = scores.get("conscientiousness", 0.5)
    n = scores.get("neuroticism", 0.5)
    o = scores.get("openness", 0.5)
    e = scores.get("extraversion", 0.5)
    a = scores.get("agreeableness", 0.5)

    rational_index = clamp01((c * 0.35) + ((1 - n) * 0.4) + (o * 0.15) + ((1 - e) * 0.1))
    if rational_index >= 0.58:
        thinking = "rational"
        thinking_zh = "更偏向理性思考"
        thinking_note = "决策时更看计划、证据和步骤；压力下仍可能把事情拆开做。"
    elif rational_index <= 0.42:
        thinking = "affective"
        thinking_zh = "更偏向感性/情绪驱动"
        thinking_note = "心情和压力更容易影响开工；需要先降低启动门槛，再谈效率。"
    else:
        thinking = "balanced"
        thinking_zh = "理性与感性较均衡"
        thinking_note = "能讲道理，但情绪低落时仍会卡住。秘书应同时给步骤和情绪缓冲。"

    execution_index = clamp01((c * 0.7) + ((1 - n) * 0.2) + ((1 - o) * 0.1))
    if execution_index >= 0.58:
        execution = "executor"
        execution_zh = "执行力偏强"
        execution_note = "更可能按计划推进。风险是把日程排太满、不留复盘。"
    elif execution_index <= 0.42:
        execution = "procrastinator"
        execution_zh = "更容易拖延"
        execution_note = "不是能力差，而是启动成本和情绪成本高。需要最小下一步和短截止。"
    else:
        execution = "mixed"
        execution_zh = "执行力中等、偶发拖延"
        execution_note = "感兴趣时推进快，无兴趣或模糊时拖。要把任务写成今天就能开始的一小步。"

    # 倒U甜点判断：E/A/C 高分但超出甜点需约束
    sweet_flags = {
        k: _in_sweet_zone(scores.get(k, 0.5)) for k in ["openness", "conscientiousness", "extraversion", "agreeableness"]
    }

    return {
        "thinking_style": thinking,
        "thinking_label": thinking_zh,
        "thinking_note": thinking_note,
        "rational_index": round(rational_index, 3),
        "execution_style": execution,
        "execution_label": execution_zh,
        "execution_note": execution_note,
        "execution_index": round(execution_index, 3),
        "social_energy": "high" if e >= HIGH else ("low" if e <= LOW else "mid"),
        "boundary_risk": "overcommit" if a >= HIGH else ("undersync" if a <= LOW else "balanced"),
        "sweet_zone": sweet_flags,
        "bands": {key: band(scores.get(key, 0.5)) for key in TRAIT_ORDER},
    }


def _task_scaffold_for(work: dict[str, Any], scores: dict[str, float]) -> dict[str, Any]:
    """根据工作风格与分数，生成任务脚手架（初版：规则式，可后续策略表化）。"""
    execution = work.get("execution_style")
    thinking = work.get("thinking_style")
    bands = work.get("bands", {})
    scaffold: dict[str, Any] = {"steps": [], "timebox": "", "template": ""}

    if execution == "procrastinator" or bands.get("conscientiousness") == "low":
        scaffold["steps"] = [
            "把任务重写为 2-10 分钟就能开始的第一步（例：新建文档写 3 行提纲）",
            "设 25 分钟计时，期间只做这一步",
            "到点即停，做 1 句复盘：完成/卡住点",
        ]
        scaffold["timebox"] = "25min"
        scaffold["template"] = "2分钟启动模板"
    elif execution == "executor":
        scaffold["steps"] = ["确认主任务截止", "拆周计划而非日催", "留复盘缓冲"]
        scaffold["timebox"] = "周级里程碑"
        scaffold["template"] = "里程碑核对模板"
    else:
        scaffold["steps"] = ["把最模糊的那件写成今天能开始的动作"]
        scaffold["timebox"] = "当日闭环"
        scaffold["template"] = "单步闭环模板"

    # 高O需探索/收敛二阶段
    if bands.get("openness") == "high":
        scaffold["steps"].insert(0, "探索设 30 分钟时间盒，到点必须产出 1 个可交付片段")
        if scaffold["timebox"] == "当日闭环":
            scaffold["timebox"] = "30min探索+当日收敛"

    # 高N需允许不完美
    if bands.get("neuroticism") == "high":
        scaffold["steps"].append("允许丑第一版，用清单打勾代替自我攻击")

    # 思维倾向微调
    if thinking == "affective":
        scaffold["steps"].append("先处理愿不愿开始：选最不抗拒的一小步")
    elif thinking == "rational":
        scaffold["steps"].append("附优先级与取舍表，少空泛鼓励")

    return scaffold


def _collaboration_hint(work: dict[str, Any]) -> dict[str, Any]:
    bands = work.get("bands", {})
    social = work.get("social_energy")
    boundary = work.get("boundary_risk")
    hints: list[str] = []
    if social == "high":
        hints.append("保护 90 分钟专注块，讨论后立刻转任务补丁")
    elif social == "low":
        hints.append("卡 25 分钟即外化提问，写成可问别人的具体问题")
    if boundary == "overcommit":
        hints.append("新请求先问会挤掉哪件主任务，主任务今日不可让")
    elif boundary == "undersync":
        hints.append("主动补一句同步：进展/阻塞/需要谁")
    # 倒U约束提示
    for trait in ["extraversion", "agreeableness", "conscientiousness"]:
        score_band = bands.get(trait)
        if score_band == "high":
            # 超峰需约束，非一味扬长
            hints.append(f"{TRAITS[trait]['zh']}偏高（倒U约束）：已过协作甜点，注意别因过度{ '社交' if trait=='extraversion' else '迎合' if trait=='agreeableness' else '控制'}影响贡献")
    return {"hints": hints, "social_energy": social, "boundary_risk": boundary}


def coaching_playbook(scores: dict[str, float], work: dict[str, Any]) -> dict[str, Any]:
    """针对短板督促、针对长处加码。秘书策略，不是让模型变成某种人格。初版已含倒U与脚手架。"""
    bands = work["bands"]
    strengths: list[str] = []
    gaps: list[str] = []
    tactics: list[str] = []
    today_focus: list[str] = []

    # --- 尽责性 ---
    if bands["conscientiousness"] == "high":
        strengths.append("尽责性高：擅长把事情做完、守截止、自己排程。")
        # 倒U约束：过高需防过载
        if not work.get("sweet_zone", {}).get("conscientiousness", True):
            gaps.append("尽责性已过甜点：可能排程过满、完美主义拖慢交付。")
            tactics.append("尽责过甜点约束：用‘够好即交付’替代完美，限 3 个并行主任务，强制复盘缓冲。")
        else:
            tactics.append("把大目标交给用户拆周计划，秘书只做进度核对，避免重复叮嘱造成反感。")
        today_focus.append("确认本周最重要的一件事是否已经有截止时间。")
    elif bands["conscientiousness"] == "low":
        gaps.append("尽责性偏低：更容易拖延、临时抱佛脚、任务停留在“想做”。")
        tactics.append("把任务切成 2–10 分钟就能开始的第一步；用今天的短截止代替遥远 deadline。")
        today_focus.append("只选一件卡住的事，写下“现在立刻做的第一小步”，并设 25 分钟启动。")
    else:
        tactics.append("感兴趣的任务推进快、模糊任务会拖。先把最模糊的那件写成可开始的动作。")

    # --- 神经质 ---
    if bands["neuroticism"] == "high":
        gaps.append("情绪波动偏高：压力下容易内耗、回避、反复确认而不开工。")
        tactics.append("先降启动焦虑：允许不完美的第一稿；避免责备语气；用清单代替自我攻击。")
        today_focus.append("用“丑第一版”代替完美方案，先提交再迭代。")
    elif bands["neuroticism"] == "low":
        strengths.append("情绪较稳：压力下更能理性推进，适合承担有截止的硬任务。")
        tactics.append("可以给稍紧的里程碑，但提醒不要因为稳而忽略他人协作节奏。")

    # --- 开放性 ---
    if bands["openness"] == "high":
        strengths.append("开放性高：学习快、点子多、愿意换方法。")
        gaps.append("探索欲强时可能开太多线、研究代替交付。")
        tactics.append("给探索设时间盒（例如 30 分钟调研），到期必须产出一个可交付片段。")
        today_focus.append("把新想法记入清单，但今天只推进已经开始的那一条。")
    elif bands["openness"] == "low":
        strengths.append("偏好熟悉流程：一旦方法固定，执行会更稳。")
        tactics.append("少推新工具；用已验证模板开工，变化一次只改一个变量。")

    # --- 外向性 ---
    if bands["extraversion"] == "high":
        strengths.append("外向：讨论、同步、找人帮忙来得快。")
        gaps.append("可能用开会和聊天替代深度完成。")
        if not work.get("sweet_zone", {}).get("extraversion", True):
            tactics.append("外向过甜点约束：保护 90 分钟专注块，讨论限 30 分钟，超时必转任务卡。")
        else:
            tactics.append("保护不受打扰的专注块；讨论后立刻写成任务补丁。")
    elif bands["extraversion"] == "low":
        strengths.append("内向深度工作：适合需要专心的学习与编码。")
        gaps.append("卡住时可能不主动求助，问题在独处中放大。")
        tactics.append("预设求助点：卡超过 25 分钟就写出来或向人确认，而不是独自空转。")
        today_focus.append("如果一件事已经想了很久还没动手，把它写成一个可以问别人的具体问题。")

    # --- 宜人性 ---
    if bands["agreeableness"] == "high":
        strengths.append("宜人性高：好协作、愿意帮忙、关系成本低。")
        gaps.append("可能不忍拒绝，日程被别人的请求挤占。")
        if not work.get("sweet_zone", {}).get("agreeableness", True):
            tactics.append("宜人过甜点约束：新请求默认延后，主任务置顶不可让，用拒绝脚本：“我主任务是X，Y能否延至Z”。")
        else:
            tactics.append("每接一个新请求，先问会挤掉哪件自己的事；秘书帮用户守住主任务。")
        today_focus.append("列出今天唯一不可被打断的主任务，其他请求默认延后。")
    elif bands["agreeableness"] == "low":
        strengths.append("边界清楚，不容易被无关请求带走。")
        tactics.append("主动补一条同步：进展、阻塞、需要谁，避免团队误读为不配合。")

    # --- 思维倾向 ---
    if work["thinking_style"] == "affective":
        tactics.append("感性驱动：先处理“愿不愿意开始”，再谈方法。用更小、更具体、可立即完成的动作。")
    elif work["thinking_style"] == "rational":
        tactics.append("理性驱动：给证据、步骤和取舍。少用空泛鼓励，多用优先级和截止。")

    # --- 执行倾向 headline ---
    if work["execution_style"] == "procrastinator":
        headline = "今日秘书重点：降低启动成本，对抗拖延"
    elif work["execution_style"] == "executor":
        headline = "今日秘书重点：守住优先级，防止过载"
    else:
        headline = "今日秘书重点：把模糊事项变成今天能开始的一步"

    # 任务脚手架与协作提示（新增，供 core 使用）
    task_scaffold = _task_scaffold_for(work, scores)
    collaboration = _collaboration_hint(work)

    # 甜点偏离提醒加入 gaps（便于前端展示）
    if not work.get("sweet_zone", {}).get("conscientiousness", True) or not work.get("sweet_zone", {}).get("extraversion", True) or not work.get("sweet_zone", {}).get("agreeableness", True):
        gaps.append("部分特质已过协作甜点（0.55±0.10），需加约束而非再激励。")

    return {
        "headline": headline,
        "strengths": strengths,
        "gaps": gaps,
        "tactics": tactics,
        "today_focus": today_focus or ["选出今天唯一主任务，并写出第一小步。"],
        "task_scaffold": task_scaffold,
        "collaboration": collaboration,
    }


def coaching_prompt_block(profile: dict[str, Any]) -> str:
    scores = profile.get("scores") or {}
    work = profile.get("work_style") or {}
    play = profile.get("playbook") or {}
    lines = [
        "【秘书督促档案｜禁止角色扮演】",
        "你是工作与学习秘书，不是心理咨询师，也不要模仿用户的性格说话。",
        "人格分数只用来判断该督促什么、该发挥什么长处。不要输出诊断标签吓人。",
        "五大估计（0-1，仅供协助，存在误差）：",
    ]
    for key in TRAIT_ORDER:
        info = TRAITS[key]
        score = scores.get(key, 0.5)
        lines.append(f"- {info['zh']}({info['en']}): {score:.2f}（{band(score)}）")
    lines.extend(
        [
            f"思维倾向：{work.get('thinking_label', '')}。{work.get('thinking_note', '')}",
            f"执行倾向：{work.get('execution_label', '')}。{work.get('execution_note', '')}",
            f"本轮督促标题：{play.get('headline', '')}",
        ]
    )
    if play.get("gaps"):
        lines.append("需要弥补的短板：")
        lines.extend(f"- {item}" for item in play["gaps"])
    if play.get("strengths"):
        lines.append("可以发扬的长处：")
        lines.extend(f"- {item}" for item in play["strengths"])
    if play.get("today_focus"):
        lines.append("请在回复里落实这些督促动作（具体、可执行、有时间盒）：")
        lines.extend(f"- {item}" for item in play["today_focus"])
    # 新增：任务脚手架与协作提示（精简注入，避免上下文溢出）
    scaffold = play.get("task_scaffold") or {}
    if scaffold.get("steps"):
        lines.append("任务脚手架（按人格给不同起点）：")
        lines.extend(f"- {s}" for s in scaffold["steps"][:3])
        if scaffold.get("timebox"):
            lines.append(f"时间盒：{scaffold['timebox']}")
    collab = play.get("collaboration") or {}
    if collab.get("hints"):
        lines.append("协作提示：")
        lines.extend(f"- {h}" for h in collab["hints"][:2])
    lines.append("若用户在逃避任务，温和但明确地把对话拉回“下一步做什么”。")
    return "\n".join(lines)
