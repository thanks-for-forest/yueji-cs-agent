"""自研全链路可观测性：JSONL 追踪器（trace/span）+ 可选 Langfuse 集成。

设计（自研为主，Langfuse 可选）：
1. **JSONL 追踪器（默认开启，零依赖）**：每次请求记录一个 trace，
   各节点（安全/情绪/路由/Agent/记忆回写）记录为 span（含耗时），
   追加到 data/traces/traces.jsonl。可用 scripts/trace_report.py 汇总分析。
2. **Langfuse 集成（可选）**：配置 LANGFUSE_* 密钥后，额外通过
   LangGraph CallbackHandler 上报到 Langfuse 云端/自托管；未配置则跳过。

用法（图节点内埋点，contextvars 传递当前 trace）：
    with Tracer.span("route"):
        ...  # 节点逻辑
    Tracer.set_intent(...) / Tracer.finish(...)
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from config import settings

logger = logging.getLogger(__name__)

# ---------- Langfuse（可选） ----------
_tracing_enabled: bool | None = None


def tracing_enabled() -> bool:
    """是否启用 Langfuse 追踪（配置了密钥）。"""
    global _tracing_enabled
    if _tracing_enabled is None:
        _tracing_enabled = bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)
        if _tracing_enabled:
            logger.info("Langfuse 追踪已启用：%s", settings.LANGFUSE_HOST)
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


# ---------- 自研 JSONL 追踪器 ----------
class Trace:
    """一次请求的追踪记录。"""

    def __init__(self, session_id: str, user_message: str):
        self.trace_id = uuid.uuid4().hex[:12]
        self.ts = time.time()
        self.session_id = session_id
        self.user_message = user_message
        self.user_id: str = ""
        self.intent: str = ""
        self.emotion: str = ""
        self.action: str = ""
        self.transferred: bool = False
        self.reply_preview: str = ""
        self.spans: list[dict] = []
        self.llm_calls: int = 0
        self._stack: list[dict] = []  # 进行中的 span 栈

    @property
    def duration_ms(self) -> float:
        return (time.time() - self.ts) * 1000

    def to_line(self) -> str:
        return json.dumps({
            "trace_id": self.trace_id,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.ts)),
            "duration_ms": round(self.duration_ms, 1),
            "session_id": self.session_id,
            "user_id": self.user_id,
            "message": self.user_message[:200],
            "intent": self.intent,
            "emotion": self.emotion,
            "action": self.action,
            "transferred": self.transferred,
            "llm_calls": self.llm_calls,
            "reply_preview": self.reply_preview[:200],
            "spans": self.spans,
        }, ensure_ascii=False)


class Tracer:
    """进程级追踪器：contextvars 承载当前请求的 Trace，节点用 span 埋点。"""

    _current: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("trace", default=None)
    _file_lock = asyncio.Lock()

    @classmethod
    def begin(cls, session_id: str, user_message: str) -> Trace:
        trace = Trace(session_id, user_message)
        cls._current.set(trace)
        return trace

    @classmethod
    def get(cls) -> Trace | None:
        return cls._current.get()

    @classmethod
    @asynccontextmanager
    async def span(cls, name: str) -> AsyncIterator[None]:
        """异步 span 上下文管理器：记录节点耗时。"""
        trace = cls._current.get()
        if trace is None:
            yield
            return
        start = time.time()
        entry: dict[str, Any] = {"name": name, "start_ms": (start - trace.ts) * 1000}
        try:
            yield
        finally:
            entry["duration_ms"] = round((time.time() - start) * 1000, 1)
            trace.spans.append(entry)

    @classmethod
    async def finish(cls, trace: Trace) -> None:
        """完成并持久化 trace（JSONL 追加写，异步加锁防并发交错）。"""
        try:
            trace_dir = settings.BASE_DIR / "data" / "traces"
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / "traces.jsonl"
            async with cls._file_lock:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _append_line, path, trace.to_line())
        except Exception as e:  # noqa: BLE001
            logger.warning("trace 写入失败：%s", e)
        finally:
            cls._current.set(None)


def _append_line(path: Path, line: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
