"""Agent 基类：统一的工具调用循环、消息组装、来源解析。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from config import settings
from src.llm.client import get_llm
from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SOURCE_RE = re.compile(r"〔来源[:：]\s*([^〕]+)〕")
_SRC_ID_RE = re.compile(r"(P\d{3}|F\d{3}|POL-\d+)", re.IGNORECASE)


@dataclass
class AgentResult:
    reply: str
    sources: list[dict] = field(default_factory=list)  # [{name, type, source_id}]
    intent: str = ""
    action: str = ""  # transfer / ticket_created / order_queried / clarify / none
    extra: dict = field(default_factory=dict)  # 结构化输出（订单卡/推荐列表/工单号）
    meta_updates: dict = field(default_factory=dict)  # 写回会话 meta 的字段

    def to_dict(self) -> dict:
        return {
            "reply": self.reply,
            "sources": self.sources,
            "intent": self.intent,
            "action": self.action,
            "extra": self.extra,
        }


def parse_sources(reply: str) -> list[dict]:
    """从回复中解析〔来源: xxx〕标注，并提取干净的来源 ID（P011/F020/POL-1）供溯源链接。"""
    out = []
    for m in SOURCE_RE.finditer(reply):
        label = m.group(1).strip()
        sid_match = _SRC_ID_RE.search(label)
        sid = sid_match.group(1).upper() if sid_match else label
        out.append({"name": label, "type": "unknown", "source_id": sid})
    return out


class BaseAgent:
    name = "base"
    system_prompt = ""
    tool_names: list[str] = []

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._tools = [t for t in registry.schemas() if t["name"] in self.tool_names]

    # ---------- 工具调用循环 ----------
    async def _llm_loop(self, messages: list[dict], ctx: dict | None = None) -> dict:
        """带工具的 LLM 循环，返回 LLMResponse（dict 视图）。ctx 携带会话上下文（如 user_id）供工具归属校验。"""
        import json

        llm = get_llm()
        resp = await llm.chat(messages, tools=self._tools or None)
        tools_used: list[dict] = []
        for _ in range(settings.MAX_TOOL_ITERS):
            if not resp.has_tools:
                break
            # OpenAI 协议：tool 消息必须跟在含 tool_calls 的 assistant 消息之后
            assistant_msg: dict = {
                "role": "assistant",
                "content": resp.content or None,
                "tool_calls": [
                    {
                        "id": tc.id or f"call_{i}",
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                    }
                    for i, tc in enumerate(resp.tool_calls)
                ],
            }
            messages.append(assistant_msg)
            for i, tc in enumerate(resp.tool_calls):
                tools_used.append({"name": tc.name, "arguments": tc.arguments})
                result = await self.registry.execute(tc.name, tc.arguments, context=ctx)
                messages.append({"role": "tool", "content": result, "tool_call_id": tc.id or f"call_{i}"})
                logger.info("Agent[%s] 调用工具 %s(%s)", self.name, tc.name, tc.arguments)
            resp = await llm.chat(messages, tools=self._tools or None)
        return {
            "content": resp.content,
            "tool_calls": [{"name": t.name, "arguments": t.arguments} for t in resp.tool_calls],
            "tools_used": tools_used,
            "provider": resp.provider,
        }

    async def _llm_loop_stream(self, messages: list[dict], ctx: dict | None = None) -> AsyncIterator[str]:
        """流式最终回答（SSE）。ctx 携带会话上下文（如 user_id），备用。

        设计：流式路径不预检工具调用（省一次非流式调用，保证 TTFT）。
        商品/政策/闲聊场景的 <知识片段> 上下文已足够支撑回答；
        订单/售后/推荐等强工具流程走非流式路径（编排器按意图分流）。
        """
        from src.llm.client import get_llm as _get_llm

        llm = _get_llm()
        got = False
        async for delta in llm.chat_stream(messages):
            got = True
            yield delta
        # 极端情况：流式无输出（如模型返回空）→ 非流式兜底
        if not got:
            resp = await llm.chat(messages, tools=self._tools or None)
            if resp.content:
                yield resp.content

    # ---------- 检索上下文注入 ----------
    @staticmethod
    def format_context(retrieved: list[dict]) -> str:
        if not retrieved:
            return ""
        lines = []
        for r in retrieved:
            src = r["meta"].get("source", r["id"])
            label = r["meta"].get("name", src)
            lines.append(f"[来源: {label}({src})]\n{r['text']}")
        return "\n\n".join(lines)

    async def run(
        self,
        user_message: str,
        session: dict,
        memory_messages: list[dict],
        retrieved: Optional[list[dict]] = None,
        **kw,
    ) -> AgentResult:
        raise NotImplementedError
