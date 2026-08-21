"""中文/英文关键词启发式。BERT 不可用或文本过短时使用。

不是心理测量量表，只是可解释的启动估计，方便秘书在无模型时仍能督促。
"""

from __future__ import annotations

import re

from .traits import TRAIT_ORDER, clamp01


KEYWORD_WEIGHTS: dict[str, dict[str, float]] = {
    "openness": {
        "新想法": 0.12,
        "好奇": 0.1,
        "探索": 0.1,
        "学习": 0.06,
        "研究": 0.08,
        "创意": 0.1,
        "灵感": 0.08,
        "换个方法": 0.08,
        "试试": 0.05,
        "抽象": 0.06,
        "curious": 0.1,
        "explore": 0.1,
        "creative": 0.1,
        "novel": 0.08,
        "learn": 0.05,
        "按老办法": -0.08,
        "不要变": -0.1,
        "就这样": -0.04,
        "流程固定": -0.08,
    },
    "conscientiousness": {
        "计划": 0.1,
        "截止": 0.12,
        "deadline": 0.12,
        "清单": 0.1,
        "完成": 0.08,
        "做完": 0.1,
        "立刻": 0.08,
        "马上": 0.06,
        "今天就": 0.1,
        "执行": 0.08,
        "自律": 0.12,
        "安排": 0.06,
        "schedule": 0.08,
        "finish": 0.08,
        "拖延": -0.16,
        "明天再说": -0.14,
        "以后再说": -0.12,
        "先不管": -0.1,
        "摸鱼": -0.12,
        "摆烂": -0.14,
        "不想动": -0.12,
        "懒得": -0.1,
        "procrastinate": -0.16,
        "later": -0.06,
    },
    "extraversion": {
        "一起": 0.08,
        "开会": 0.08,
        "讨论": 0.08,
        "找人": 0.08,
        "社交": 0.1,
        "聊天": 0.06,
        "分享": 0.05,
        "团队": 0.06,
        "meetup": 0.08,
        "talk": 0.05,
        "自己待着": -0.1,
        "独处": -0.1,
        "别打扰": -0.08,
        "不想说话": -0.1,
        "一个人": -0.06,
        "introvert": -0.08,
    },
    "agreeableness": {
        "帮忙": 0.08,
        "不好意思": 0.1,
        "拒绝不了": 0.14,
        "答应": 0.06,
        "体谅": 0.08,
        "配合": 0.06,
        "怕麻烦别人": 0.12,
        "sorry": 0.04,
        "help": 0.04,
        "不想帮": -0.08,
        "自己的事先做": -0.06,
        "直接拒绝": -0.1,
        "边界": 0.0,
    },
    "neuroticism": {
        "焦虑": 0.14,
        "紧张": 0.1,
        "压力": 0.1,
        "内耗": 0.14,
        "担心": 0.1,
        "害怕": 0.1,
        "崩溃": 0.12,
        "睡不着": 0.1,
        "完美": 0.06,
        "万一": 0.06,
        "不确定": 0.06,
        "anxious": 0.12,
        "stress": 0.1,
        "worry": 0.1,
        "overthink": 0.12,
        "没关系": -0.04,
        "淡定": -0.08,
        "稳": -0.04,
        "冷静": -0.08,
    },
}


def heuristic_scores(text: str, prior: dict[str, float] | None = None) -> dict[str, float]:
    lowered = (text or "").strip()
    scores = {key: float((prior or {}).get(key, 0.5)) for key in TRAIT_ORDER}
    if not lowered:
        return scores
    compact = re.sub(r"\s+", "", lowered.lower())
    source = lowered.lower()
    for trait, table in KEYWORD_WEIGHTS.items():
        delta = 0.0
        hits = 0
        for word, weight in table.items():
            needle = word.lower()
            if needle in source or needle in compact:
                delta += weight
                hits += 1
        if hits:
            # 多次命中略增强，但不让单句把分数打满
            scores[trait] = clamp01(scores[trait] + max(-0.28, min(0.28, delta)))
    return {key: round(scores[key], 4) for key in TRAIT_ORDER}
