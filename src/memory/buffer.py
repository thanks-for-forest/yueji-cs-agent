"""会话记忆：短期窗口 + 中期摘要。"""
from __future__ import annotations

import logging

from config import settings
from src.llm.client import get_llm

logger = logging.getLogger(__name__)


def trim_to_window(messages: list[dict], window: int | None = None) -> list[dict]:
    """保留最近 N 轮（1 轮 = user + assistant）。"""
    window = window or settings.MEMORY_WINDOW
    if len(messages) <= window * 2:
        return messages
    return messages[-(window * 2):]


async def summarize(messages: list[dict]) -> str:
    """把一段对话压缩为摘要。"""
    if not messages:
        return ""
    transcript = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in messages)
    try:
        llm = get_llm()
        resp = await llm.chat(
            [
                {"role": "system", "content": "你是客服会话摘要器。把对话压缩为100字以内的中文摘要，保留：用户身份信息、咨询对象、关键槽位值（订单号/手机尾号/售后类型）、未解决的问题。只输出摘要。"},
                {"role": "user", "content": transcript},
            ],
            max_tokens=300,
        )
        return resp.content.strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("摘要生成失败：%s", e)
        return ""
