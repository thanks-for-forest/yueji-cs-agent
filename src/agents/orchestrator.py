"""Agent 编排器：一次用户消息的完整处理链路。

主路径（非流式）：LangGraph Supervisor-Worker 图执行（src/graph/*）。
流式路径：保留快路径（handle_stream），与图路径共享相同的预处理语义。
"""
from __future__ import annotations

import logging

from src.agents.aftersale_agent import AftersaleAgent
from src.agents.base_agent import AgentResult, parse_sources
from src.agents.human_agent import HumanAgent
from src.agents.order_agent import OrderAgent
from src.agents.product_agent import ProductAgent
from src.agents.router import intent_to_agent, route
from src.agents.skincare_agent import SkincareAgent
from src.emotion.detector import classify_rule
from src.graph.workflow import get_compiled_graph
from src.rag.retriever import catalog_context, is_catalog_query, retrieve_context
from src.session.service import get_session_service
from src.tools.registry import get_registry
from src.utils.security import contains_sensitive, detect_prompt_injection
from src.utils.tracing import Tracer, graph_config

logger = logging.getLogger(__name__)

SENSITIVE_REPLY = "抱歉，这个话题我无法协助。如有购物相关问题（商品、订单、售后、护肤推荐），欢迎随时告诉我～"
INJECTION_REPLY = "抱歉，我只能提供商品咨询、订单查询、售后处理与护肤推荐服务。如有需要，请直接告诉我您的需求～"
NEED_RETRIEVAL_INTENTS = {"product_consult", "policy", "chitchat"}


class AgentOrchestrator:
    def __init__(self) -> None:
        registry = get_registry()
        self.svc = get_session_service()
        self.agents = {
            "product": ProductAgent(registry),
            "order": OrderAgent(registry),
            "aftersale": AftersaleAgent(registry),
            "skincare": SkincareAgent(registry),
            "human": HumanAgent(registry),
        }

    async def handle(self, session_id: str, user_message: str) -> dict:
        """主路径：LangGraph 图执行（Supervisor-Worker），自研 JSONL 追踪 + 可选 Langfuse。"""
        session = await self.svc.get_session(session_id)
        if session is None:
            session = await self.svc.create_session(session_id=session_id)

        user_message = user_message.strip()
        await self.svc.save_message(session_id, "user", user_message)
        session["meta"] = await self.svc.update_meta(session_id)  # 刷新（可能被并发修改）

        trace = Tracer.begin(session_id, user_message)
        trace.user_id = session.get("user_id", "") or ""
        payload: dict = {}
        try:
            final = await get_compiled_graph().ainvoke(
                {"session_id": session_id, "user_message": user_message, "session": session},
                config=graph_config(),
            )
            payload = final["payload"]
        finally:
            trace.intent = payload.get("intent", "")
            trace.emotion = payload.get("emotion", "")
            trace.action = payload.get("action", "")
            trace.transferred = bool(payload.get("transferred"))
            trace.reply_preview = payload.get("reply", "")
            await Tracer.finish(trace)
        return payload

    # ---------- 流式聊天（SSE） ----------
    STREAM_INTENTS = {"product_consult", "policy", "chitchat"}

    async def handle_stream(self, session_id: str, user_message: str):
        """流式版本：yield {"type":"delta","text":...} 与 {"type":"done","result":{...}}。"""
        session = await self.svc.get_session(session_id)
        if session is None:
            session = await self.svc.create_session(session_id=session_id)

        user_message = user_message.strip()
        await self.svc.save_message(session_id, "user", user_message)
        session["meta"] = await self.svc.update_meta(session_id)

        trace = Tracer.begin(session_id, user_message)
        trace.user_id = session.get("user_id", "") or ""

        bad_word = contains_sensitive(user_message)
        if bad_word:
            reply = SENSITIVE_REPLY
            yield {"type": "delta", "text": reply}
            await self._finish(session_id, session, reply, "blocked_sensitive")
            payload = self._payload(session_id, reply, [], "chitchat", "normal", "blocked", {"bad_word": bad_word})
            yield {"type": "done", "result": payload}
            trace.action = "blocked"
            trace.reply_preview = reply
            await Tracer.finish(trace)
            return
        if detect_prompt_injection(user_message):
            reply = INJECTION_REPLY
            yield {"type": "delta", "text": reply}
            await self._finish(session_id, session, reply, "blocked_injection")
            payload = self._payload(session_id, reply, [], "chitchat", "normal", "blocked", {})
            yield {"type": "done", "result": payload}
            trace.action = "blocked"
            trace.reply_preview = reply
            await Tracer.finish(trace)
            return

        emotion, _ = classify_rule(user_message)
        need_transfer = await self.svc.push_emotion(session_id, emotion)
        session["meta"] = await self.svc.update_meta(session_id)

        memory = await self.svc.build_memory_messages(session)
        if memory and memory[-1].get("role") == "user":
            memory = memory[:-1]
        step = session["meta"].get("step", "")
        intent, confidence, method = await route(user_message, emotion, history=memory)
        if step == "confirm":
            intent, confidence, method = "aftersale", 1.0, "state"

        # 可流式的意图 → Agent 流式；否则回退非流式后按块输出（保证 SSE 统一体验）
        agent_name = intent_to_agent(intent)
        retrieved = None
        if intent in NEED_RETRIEVAL_INTENTS and agent_name in ("product", "aftersale"):
            from src.graph.nodes import _enrich_query

            retrieved = await retrieve_context(_enrich_query(user_message, session))
            if not retrieved and intent in ("product_consult", "chitchat") and is_catalog_query(user_message):
                retrieved = catalog_context(user_message)
                catalog_mode = True

        if need_transfer or intent == "transfer_human":
            result: AgentResult = await self.agents["human"].run(
                user_message, session, memory,
                emotion=emotion, trigger="emotion" if need_transfer else "user_request",
            )
            for piece in _chunk_text(result.reply, 20):
                yield {"type": "delta", "text": piece}
        elif intent in self.STREAM_INTENTS:
            streamer = self.agents[agent_name].stream(
                user_message, session, memory, retrieved=retrieved, intent=intent, emotion=emotion,
            )
            full = []
            async for delta in streamer:
                full.append(delta)
                yield {"type": "delta", "text": delta}
            result = AgentResult(reply="".join(full), sources=[], intent=intent, action="none")
            result.sources = parse_sources(result.reply)
            if not result.sources and retrieved:
                for r in retrieved[:3]:
                    result.sources.append({"name": r["meta"].get("name", r["meta"].get("source")), "type": r["meta"]["type"], "source_id": r["meta"].get("source", "")})
        else:
            result = await self.agents[agent_name].run(
                user_message, session, memory,
                retrieved=retrieved, intent=intent, emotion=emotion,
            )
            for piece in _chunk_text(result.reply, 20):
                yield {"type": "delta", "text": piece}

        if result.meta_updates:
            session["meta"] = await self.svc.update_meta(session_id, **result.meta_updates)
        await self._finish(session_id, session, result.reply, result.action)
        await self.svc.maybe_summarize(session)
        payload = self._payload(
            session_id, result.reply, result.sources, result.intent,
            emotion, result.action, result.extra,
            transferred=(need_transfer or intent == "transfer_human"),
        )
        yield {"type": "done", "result": payload}
        trace.intent = payload["intent"]
        trace.emotion = payload["emotion"]
        trace.action = payload["action"]
        trace.transferred = payload["transferred"]
        trace.reply_preview = payload["reply"]
        await Tracer.finish(trace)

    # ---------- 工具方法 ----------
    async def _finish(self, session_id: str, session: dict, reply: str, action: str) -> None:
        await self.svc.save_message(session_id, "assistant", reply)
        await self.svc.touch(session_id)

    @staticmethod
    def _payload(session_id, reply, sources, intent, emotion, action, extra, transferred=False) -> dict:
        return {
            "session_id": session_id,
            "reply": reply,
            "sources": sources,
            "intent": intent,
            "emotion": emotion,
            "action": action,
            "extra": extra,
            "transferred": transferred,
        }


_orch: AgentOrchestrator | None = None


def _chunk_text(text: str, size: int = 20) -> list[str]:
    """把长文本按块切分（用于非流式结果的 SSE 输出）。"""
    return [text[i : i + size] for i in range(0, len(text), size)]


def get_orchestrator() -> AgentOrchestrator:
    global _orch
    if _orch is None:
        _orch = AgentOrchestrator()
    return _orch
