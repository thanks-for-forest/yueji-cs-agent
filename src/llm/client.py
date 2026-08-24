"""OpenAI 兼容 LLM 客户端。

主提供方：DeepSeek（deepseek-chat）；兜底提供方：Ollama（qwen2.5）。
支持：普通对话、工具调用（function calling）、JSON 模式、流式输出、批量 Embedding。
设计为 Agent 层唯一 LLM 入口，便于统一切换/降级/埋点。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用最终失败（主备均失败）。"""


class ToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict):
        self.id = call_id
        self.name = name
        self.arguments = arguments

    def __repr__(self) -> str:  # pragma: no cover
        return f"ToolCall({self.name}, {self.arguments})"


class LLMResponse:
    def __init__(
        self,
        content: str,
        tool_calls: list[ToolCall],
        provider: str,
        finish_reason: str = "",
        usage: Optional[dict] = None,
    ):
        self.content = content or ""
        self.tool_calls = tool_calls
        self.provider = provider
        self.finish_reason = finish_reason
        self.usage = usage or {}

    @property
    def has_tools(self) -> bool:
        return bool(self.tool_calls)


def _openai_tools(schemas: list[dict]) -> list[dict]:
    """把 {name, description, parameters} 转为 OpenAI tools 格式。"""
    return [
        {"type": "function", "function": {"name": s["name"], "description": s.get("description", ""), "parameters": s.get("parameters", {"type": "object", "properties": {}})}}
        for s in schemas
    ]


def _parse_message(msg: dict, provider: str) -> LLMResponse:
    content = msg.get("content") or ""
    tool_calls: list[ToolCall] = []
    for tc in msg.get("tool_calls") or []:
        try:
            args = json.loads(tc["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(tc.get("id", ""), tc["function"].get("name", ""), args))
    finish = (msg.get("finish_reason") or "") if isinstance(msg, dict) else ""
    return LLMResponse(content, tool_calls, provider, finish)


class LLMClient:
    """异步 LLM 客户端。用法：单例，进程退出前调用 close()。

    注意：httpx.AsyncClient 绑定事件循环，脚本中多次 asyncio.run() 时
    按循环懒创建客户端，避免 "Event loop is closed"。
    """

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(90.0, connect=10.0)
        self._clients: dict[int, httpx.AsyncClient] = {}

    def _client_for_loop(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        key = id(loop)
        if key not in self._clients:
            self._clients[key] = httpx.AsyncClient(timeout=self._timeout)
        return self._clients[key]

    # ---------------- 对话 / 工具调用 ----------------

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,  # {name, description, parameters}
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """先 DeepSeek，失败自动切换 Ollama。"""
        errors: list[str] = []
        try:
            return await self._chat_deepseek(messages, tools, temperature, max_tokens, json_mode)
        except Exception as e:  # noqa: BLE001
            errors.append(f"deepseek: {e}")
            logger.warning("DeepSeek 调用失败，切换 Ollama：%s", e)
        try:
            return await self._chat_ollama(messages, tools, temperature, max_tokens, json_mode)
        except Exception as e:  # noqa: BLE001
            errors.append(f"ollama: {e}")
        raise LLMError("LLM 主备均失败: " + " | ".join(errors))

    async def _chat_deepseek(
        self, messages, tools, temperature, max_tokens, json_mode
    ) -> LLMResponse:
        if not settings.DEEPSEEK_API_KEY:
            raise LLMError("未配置 DEEPSEEK_API_KEY")
        payload: dict[str, Any] = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.TEMPERATURE,
            "max_tokens": max_tokens or settings.MAX_TOKENS,
            "stream": False,
        }
        if tools:
            payload["tools"] = _openai_tools(tools)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        client = self._client_for_loop()
        resp = await client.post(
            f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
            json=payload,
        )
        if resp.status_code >= 400:
            logger.warning("DeepSeek 返回 %s: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
        return _parse_message(data["choices"][0]["message"], "deepseek")

    async def _chat_ollama(
        self, messages, tools, temperature, max_tokens, json_mode
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": settings.OLLAMA_CHAT_MODEL,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.TEMPERATURE,
            "max_tokens": max_tokens or settings.MAX_TOKENS,
            "stream": False,
        }
        if tools:
            payload["tools"] = _openai_tools(tools)
        client = self._client_for_loop()
        resp = await client.post(
            f"{settings.OLLAMA_BASE_URL}/v1/chat/completions", json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_message(data["choices"][0]["message"], "ollama")

    # ---------------- 流式输出（仅用于最终回答，无工具调用） ----------------

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """流式返回文本增量。DeepSeek 失败则静默降级为 Ollama 流式。"""
        payload = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.TEMPERATURE,
            "max_tokens": max_tokens or settings.MAX_TOKENS,
            "stream": True,
        }
        try:
            client = self._client_for_loop()
            async with client.stream(
                "POST",
                f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
            return
        except Exception as e:  # noqa: BLE001
            logger.warning("DeepSeek 流式失败，切换 Ollama：%s", e)
        payload["model"] = settings.OLLAMA_CHAT_MODEL
        client = self._client_for_loop()
        async with client.stream(
            "POST", f"{settings.OLLAMA_BASE_URL}/v1/chat/completions", json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta

    # ---------------- Embedding（Ollama bge-m3，批量） ----------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化。空输入返回空列表。keep_alive 让模型驻留内存，避免频繁冷加载。"""
        if not texts:
            return []
        client = self._client_for_loop()
        resp = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/embed",
            json={"model": settings.EMBED_MODEL, "input": texts, "keep_alive": "10m"},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]

    async def close(self) -> None:
        for c in self._clients.values():
            await c.aclose()
        self._clients.clear()


# 进程级单例
_llm: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


async def close_llm() -> None:
    global _llm
    if _llm is not None:
        await _llm.close()
        _llm = None
