"""LLM 客户端重试容错测试（离线：stub httpx 客户端，不发起真实网络请求）。"""
import asyncio

import httpx
import pytest

from config import settings
from src.llm.client import LLMClient


class _FakeTransport:
    """按序返回预置响应的 stub transport（预置项若是异常则抛出）。"""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []

    async def post(self, url, headers=None, json=None):
        self.calls.append((url, json))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def send(self, req, stream=False):
        self.calls.append((str(req.url), None))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        pass


def _ok_chat() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "你好"}}]},
                          request=httpx.Request("POST", "http://fake"))


def _resp(status: int, text: str = "", **kw) -> httpx.Response:
    return httpx.Response(status, text=text, request=httpx.Request("POST", "http://fake"), **kw)


def _run(coro):
    return asyncio.run(coro)


def _fresh_client(transport: _FakeTransport) -> LLMClient:
    c = LLMClient()
    c._client_for_loop = lambda: transport  # type: ignore[method-assign]
    return c


def test_chat_retries_transport_error_then_succeeds(monkeypatch):
    """传输错误前 2 次重试，第 3 次成功。"""
    monkeypatch.setattr(settings, "LLM_RETRY_TIMES", 3)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY", 0.0)
    t = _FakeTransport([
        httpx.ConnectError("boom"),
        httpx.ConnectError("boom"),
        _ok_chat(),
    ])
    resp = _run(_fresh_client(t).chat([{"role": "user", "content": "hi"}]))
    assert resp.content == "你好"
    assert len(t.calls) == 3


def test_chat_retries_on_429_then_succeeds(monkeypatch):
    """429 限流重试后成功。"""
    monkeypatch.setattr(settings, "LLM_RETRY_TIMES", 3)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY", 0.0)
    t = _FakeTransport([
        _resp(429, text="rate limited"),
        _ok_chat(),
    ])
    resp = _run(_fresh_client(t).chat([{"role": "user", "content": "hi"}]))
    assert resp.content == "你好"
    assert len(t.calls) == 2


def test_chat_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "LLM_RETRY_TIMES", 3)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY", 0.0)
    t = _FakeTransport([
        _resp(503, text="unavailable"),
        _ok_chat(),
    ])
    resp = _run(_fresh_client(t).chat([{"role": "user", "content": "hi"}]))
    assert resp.content == "你好"
    assert len(t.calls) == 2


def test_chat_does_not_retry_client_error_400(monkeypatch):
    """4xx 客户端错误（如参数/工具消息顺序问题）不重试：只调用 1 次即失败。"""
    from src.llm.client import LLMError

    monkeypatch.setattr(settings, "LLM_RETRY_TIMES", 3)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY", 0.0)
    t = _FakeTransport([_resp(400, text="bad request")])
    with pytest.raises(LLMError):
        _run(_fresh_client(t).chat([{"role": "user", "content": "hi"}]))
    # 各提供方仅调用 1 次（无重试）：deepseek 1 + ollama 降级 1
    deepseek_calls = [c for c in t.calls if "deepseek" in c[0]]
    assert len(deepseek_calls) == 1  # 4xx 不重试
    assert len(t.calls) == 2


def test_chat_all_retries_fail_then_fallback_ollama(monkeypatch):
    """DeepSeek 全部重试失败后自动切换 Ollama（主备容错）。"""
    monkeypatch.setattr(settings, "LLM_RETRY_TIMES", 2)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY", 0.0)
    t = _FakeTransport([
        httpx.ConnectError("boom"),      # deepseek 第1次
        httpx.ConnectError("boom"),      # deepseek 第2次（重试）
        _ok_chat(),                      # ollama 成功
    ])
    resp = _run(_fresh_client(t).chat([{"role": "user", "content": "hi"}]))
    assert resp.content == "你好"
    assert resp.provider == "ollama"
    assert len(t.calls) == 3


def test_embed_retries_transport_error(monkeypatch):
    """embed 传输错误重试后成功。"""
    monkeypatch.setattr(settings, "LLM_RETRY_TIMES", 3)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY", 0.0)
    t = _FakeTransport([
        httpx.ConnectError("boom"),
        httpx.Response(200, json={"embeddings": [[0.1, 0.2]]}, request=httpx.Request("POST", "http://fake")),
    ])
    out = _run(_fresh_client(t).embed(["测试"]))
    assert out == [[0.1, 0.2]]
    assert len(t.calls) == 2
