"""情绪检测：三级（normal / negative / angry）。

链路：情感词典 + 强标点 + 关键词 → 命中即定级（同步、零成本）；
未命中时可选 LLM 三分类兜底（async，由会话服务调用）。
"""
from __future__ import annotations

import re

from config import settings

LEVELS = ("normal", "negative", "angry")

# 负面情感词（不含强投诉词）
_NEG_WORDS = settings.EMOTION_NEGATIVE_WORDS
# 强投诉/维权词 → angry
_ANGRY_WORDS = ["投诉", "315", "曝光", "律师", "媒体", "起诉", "维权", "骗子", "欺诈", "坑人", "投诉到底", "再也不买", "拉黑", "太过分", "恶心", "离谱"]
# 需要转人工的关键词（无论等级）
TRANSFER_KEYWORDS = settings.EMOTION_TRANSFER_KW


def _strong_punct(text: str) -> bool:
    return any(p in text for p in settings.EMOTION_STRONG_PUNCT)


def classify_rule(text: str) -> tuple[str, list[str]]:
    """规则定级。返回 (等级, 命中的词列表)。"""
    hits = [w for w in _ANGRY_WORDS if w in text]
    if hits:
        return "angry", hits
    neg = [w for w in _NEG_WORDS if w in text]
    if neg or _strong_punct(text):
        return "negative", neg
    return "normal", []


def needs_transfer(emotion: str, recent: list[str]) -> bool:
    """会话级转人工策略：
    - 当前 angry → 转
    - 最近连续 2 轮 negative → 转
    - 最近 2 轮内出现转人工关键词 → 转（由关键词单独判定）
    """
    if emotion == "angry":
        return True
    recent_neg = [e for e in recent if e == "negative"]
    if len(recent_neg) >= 2:
        return True
    return False
