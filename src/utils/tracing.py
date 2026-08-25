"""Langfuse 可观测性封装（全链路追踪）。

设计：
- 配置了 LANGFUSE_PUBLIC_KEY / SECRET_KEY 时启用真实追踪（trace 包裹图执行，
  通过 LangGraph CallbackHandler 自动记录每个节点/LLM 调用为 span）；
- 未配置时返回 None（no-op），系统行为与未接入时完全一致（优雅降级）。

用法：
    handler = make_callback_handler()
    config = {"callbacks": [handler]} if handler else {}
    await graph.ainvoke(state, config=config)
"""
from __future__ import annotations

import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

_tracing_enabled: bool | None = None


def tracing_enabled() -> bool:
    """是否启用 Langfuse 追踪（配置了密钥）。"""
    global _tracing_enabled
    if _tracing_enabled is None:
        _tracing_enabled = bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)
        if _tracing_enabled:
            logger.info("Langfuse 追踪已启用：%s", settings.LANGFUSE_HOST)
        else:
            logger.info("Langfuse 未配置密钥，追踪关闭（优雅降级 no-op）")
    return _tracing_enabled


def make_callback_handler():
    """返回 LangGraph 用的 Langfuse CallbackHandler；未配置返回 None。"""
    if not tracing_enabled():
        return None
    try:
        from langfuse.callback import CallbackHandler

        return CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            trace_name="yueji_cs_chat",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Langfuse CallbackHandler 创建失败（降级 no-op）：%s", e)
        return None


def graph_config() -> dict:
    """组装 LangGraph invoke 的 config（含 callbacks）。"""
    handler = make_callback_handler()
    if handler is None:
        return {}
    return {"callbacks": [handler], "metadata": {"app": "yueji-cs-agent", "version": "2.0"}}
