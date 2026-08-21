"""大五人格工作学映射：用于秘书督促，而不是让 Agent 扮演某种性格。

依据工业与组织心理学中较稳定的结论（Barrick & Mount 1991 工作绩效；
Steel 2007 拖延元分析）：尽责性是执行力/反拖延的最强正向指标；
神经质升高时情绪波动与回避上升；开放性升高时探索欲强但易发散；
外向性影响社交能量与深度独处；宜人性影响拒绝能力与协作负担。
本模块不做临床诊断。
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


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def band(score: float) -> str:
    if score >= HIGH:
        return "high"
    if score <= LOW:
        return "low"
    return "mid"


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
        "bands": {key: band(scores.get(key, 0.5)) for key in TRAIT_ORDER},
    }


def coaching_playbook(scores: dict[str, float], work: dict[str, Any]) -> dict[str, Any]:
    """针对短板督促、针对长处加码。秘书策略，不是让模型变成某种人格。"""
    bands = work["bands"]
    strengths: list[str] = []
    gaps: list[str] = []
    tactics: list[str] = []
    today_focus: list[str] = []

    if bands["conscientiousness"] == "high":
        strengths.append("尽责性高：擅长把事情做完、守截止、自己排程。")
        tactics.append("把大目标交给用户拆周计划，秘书只做进度核对，避免重复叮嘱造成反感。")
        today_focus.append("确认本周最重要的一件事是否已经有截止时间。")
    elif bands["conscientiousness"] == "low":
        gaps.append("尽责性偏低：更容易拖延、临时抱佛脚、任务停留在“想做”。")
        tactics.append("把任务切成 2–10 分钟就能开始的第一步；用今天的短截止代替遥远 deadline。")
        today_focus.append("只选一件卡住的事，写下“现在立刻做的第一小步”，并设 25 分钟启动。")
    else:
        tactics.append("感兴趣的任务推进快、模糊任务会拖。先把最模糊的那件写成可开始的动作。")

    if bands["neuroticism"] == "high":
        gaps.append("情绪波动偏高：压力下容易内耗、回避、反复确认而不开工。")
        tactics.append("先降启动焦虑：允许不完美的第一稿；避免责备语气；用清单代替自我攻击。")
        today_focus.append("用“丑第一版”代替完美方案，先提交再迭代。")
    elif bands["neuroticism"] == "low":
        strengths.append("情绪较稳：压力下更能理性推进，适合承担有截止的硬任务。")
        tactics.append("可以给稍紧的里程碑，但提醒不要因为稳而忽略他人协作节奏。")

    if bands["openness"] == "high":
        strengths.append("开放性高：学习快、点子多、愿意换方法。")
        gaps.append("探索欲强时可能开太多线、研究代替交付。")
        tactics.append("给探索设时间盒（例如 30 分钟调研），到期必须产出一个可交付片段。")
        today_focus.append("把新想法记入清单，但今天只推进已经开始的那一条。")
    elif bands["openness"] == "low":
        strengths.append("偏好熟悉流程：一旦方法固定，执行会更稳。")
        tactics.append("少推新工具；用已验证模板开工，变化一次只改一个变量。")

    if bands["extraversion"] == "high":
        strengths.append("外向：讨论、同步、找人帮忙来得快。")
        gaps.append("可能用开会和聊天替代深度完成。")
        tactics.append("保护不受打扰的专注块；讨论后立刻写成任务补丁。")
    elif bands["extraversion"] == "low":
        strengths.append("内向深度工作：适合需要专心的学习与编码。")
        gaps.append("卡住时可能不主动求助，问题在独处中放大。")
        tactics.append("预设求助点：卡超过 25 分钟就写出来或向人确认，而不是独自空转。")
        today_focus.append("如果一件事已经想了很久还没动手，把它写成一个可以问别人的具体问题。")

    if bands["agreeableness"] == "high":
        strengths.append("宜人性高：好协作、愿意帮忙、关系成本低。")
        gaps.append("可能不忍拒绝，日程被别人的请求挤占。")
        tactics.append("每接一个新请求，先问会挤掉哪件自己的事；秘书帮用户守住主任务。")
        today_focus.append("列出今天唯一不可被打断的主任务，其他请求默认延后。")
    elif bands["agreeableness"] == "low":
        strengths.append("边界清楚，不容易被无关请求带走。")
        tactics.append("主动补一条同步：进展、阻塞、需要谁，避免团队误读为不配合。")

    if work["thinking_style"] == "affective":
        tactics.append("感性驱动：先处理“愿不愿意开始”，再谈方法。用更小、更具体、可立即完成的动作。")
    elif work["thinking_style"] == "rational":
        tactics.append("理性驱动：给证据、步骤和取舍。少用空泛鼓励，多用优先级和截止。")

    if work["execution_style"] == "procrastinator":
        headline = "今日秘书重点：降低启动成本，对抗拖延"
    elif work["execution_style"] == "executor":
        headline = "今日秘书重点：守住优先级，防止过载"
    else:
        headline = "今日秘书重点：把模糊事项变成今天能开始的一步"

    return {
        "headline": headline,
        "strengths": strengths,
        "gaps": gaps,
        "tactics": tactics,
        "today_focus": today_focus or ["选出今天唯一主任务，并写出第一小步。"],
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
    lines.append("若用户在逃避任务，温和但明确地把对话拉回“下一步做什么”。")
    return "\n".join(lines)
