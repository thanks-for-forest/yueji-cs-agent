"""离线测试用假 LLM：确定性向量 + 规则化回复，接口对齐 src/llm/client.py 的 LLMClient。

用途：CI / 无 DeepSeek / 无 Ollama 环境下运行测试。
- chat：路由器场景（系统提示含"意图"）返回合法意图；其余场景返回固定客服话术。
  返回 LLMResponse 形态（content/tool_calls/has_tools/provider），兼容 Agent 工具循环。
- embed：基于文本的确定性伪随机单位向量（同文本同向量）。
- 注意：embedding 无语义，仅保证接口与确定性；语义检索类测试请标记 @pytest.mark.integration。
"""
from __future__ import annotations

import hashlib
import math

from src.llm.client import LLMResponse, ToolCall

DIM = 1024


class FakeLLM:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {"chat": 0, "embed": 0}

    # ---------- 聊天 ----------
    async def chat(self, messages: list[dict], tools: list | None = None,
                   temperature: float | None = None, max_tokens: int | None = None,
                   json_mode: bool = False) -> LLMResponse:
        self.calls["chat"] += 1
        sys_text = " ".join(m.get("content", "") or "" for m in messages if m.get("role") == "system")
        if "意图" in sys_text and "chitchat" in sys_text:
            # 路由器意图分类：返回合法意图
            return LLMResponse("product_consult", [], "fake", "stop")
        return LLMResponse("好的，小悦为您解答：这是离线测试回复。", [], "fake", "stop")

    async def chat_stream(self, messages: list[dict], tools: list | None = None,
                          temperature: float | None = None, max_tokens: int | None = None,
                          json_mode: bool = False):
        self.calls["chat"] += 1
        sys_text = " ".join(m.get("content", "") or "" for m in messages if m.get("role") == "system")
        content = "product_consult" if ("意图" in sys_text and "chitchat" in sys_text) \
            else "好的，小悦为您解答：这是离线测试回复。"
        for ch in content:
            yield {"type": "delta", "text": ch}

    # ---------- 向量化 ----------
    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls["embed"] += 1
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        v = []
        for i in range(DIM):
            h = hashlib.blake2b(f"{text}#{i}".encode(), digest_size=4).digest()
            v.append(int.from_bytes(h, "big") / 2**32 - 0.5)
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def close(self) -> None:
        return None
