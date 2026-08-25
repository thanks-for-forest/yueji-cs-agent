"""自研 JSONL 追踪器测试。"""
import asyncio
import json

from src.utils.tracing import Tracer


def test_span_records_duration(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)

    async def t():
        trace = Tracer.begin("t-session", "测试消息")
        async with Tracer.span("node_a"):
            await asyncio.sleep(0.01)
        trace.intent = "product_consult"
        trace.action = "none"
        trace.reply_preview = "ok"
        await Tracer.finish(trace)
        return trace

    trace = asyncio.run(t())
    assert len(trace.spans) == 1
    assert trace.spans[0]["name"] == "node_a"
    assert trace.spans[0]["duration_ms"] >= 5
    assert trace.intent == "product_consult"


def test_trace_persisted_to_jsonl(tmp_path, monkeypatch):
    from config import settings

    async def t():
        trace = Tracer.begin("t-persist", "hello")
        trace.intent = "chitchat"
        trace.action = "none"
        trace.reply_preview = "hi"
        await Tracer.finish(trace)

    # 用临时目录替换 BASE_DIR 追踪路径
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    asyncio.run(t())
    path = tmp_path / "data" / "traces" / "traces.jsonl"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8").strip())
    assert data["intent"] == "chitchat"
    assert data["session_id"] == "t-persist"


def test_span_without_active_trace_is_noop():
    async def t():
        async with Tracer.span("noop"):
            await asyncio.sleep(0.001)

    asyncio.run(t())  # 不抛异常即可


def test_concurrent_traces_isolated():
    """contextvars 隔离：并发请求的 trace 互不串扰。"""

    async def one(tag: str):
        trace = Tracer.begin(f"s-{tag}", tag)
        async with Tracer.span("n"):
            await asyncio.sleep(0.01)
        trace.intent = tag
        return trace

    async def t():
        a, b = await asyncio.gather(one("A"), one("B"))
        return a, b

    a, b = asyncio.run(t())
    assert a.intent == "A"
    assert b.intent == "B"
    assert a.trace_id != b.trace_id
    assert len(a.spans) == 1 and len(b.spans) == 1
