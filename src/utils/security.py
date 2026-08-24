"""安全与隐私：PII 脱敏、Prompt 注入检测、敏感内容拦截。"""
from __future__ import annotations

import re

# 中国大陆手机号
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def mask_pii(text: str) -> str:
    """把手机号脱敏为 138****0000。"""
    return _PHONE_RE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], text)


# 注入攻击特征（用户试图改变系统行为）
_INJECTION_PATTERNS = [
    r"忽略.{0,8}(?:指令|规则|提示|约束|设置|system)",
    r"ignore.{0,16}(?:instruction|rule|prompt|system|above)",
    r"(?:泄露|输出|显示|告诉我|背诵|重复).{0,8}(?:系统提示|系统指令|系统设定|system prompt|指令|设定)",
    r"扮演.{0,8}(?:系统|system|另一个助手|其他角色)",
    r"你是.{0,6}(?:openai|gpt|机器人|另一个助手)",
    r"reveal.{0,12}(?:system|instruction|prompt)",
    r"越狱|jailbreak|dAN\b",
    r"不再(?:遵守|遵循|受限)|不受约束|解除限制",
    r"作为.{0,8}(?:独立|不受约束|另一个).{0,4}(?:ai|助手|agent)",
    r"把.{0,6}(?:规则|指令|提示).{0,6}(?:发|告诉|输出)给我",
]


def detect_prompt_injection(text: str) -> bool:
    """检测 Prompt 注入攻击。命中返回 True。"""
    t = text.lower()
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, t):
            return True
    return False


# 敏感/违法内容关键词（命中即拒绝并标记会话）
SENSITIVE_WORDS = [
    "毒品", "赌博网址", "博彩", "色情", "约炮", "枪支", "爆炸物制作",
    "违禁品", "代开发票", "刷单返利", "洗钱",
]


def contains_sensitive(text: str) -> str | None:
    """命中敏感词返回该词，否则 None。"""
    for w in SENSITIVE_WORDS:
        if w in text:
            return w
    return None


def safe_log(text: str) -> str:
    """日志安全化：脱敏 + 截断。"""
    return mask_pii(text)[:500]
