"""Agent 编排器：一次用户消息的完整处理链路。

安全校验 → 情绪检测 → 意图路由 → 专项 Agent 分发 → 记忆回写 → 响应组装。
"""
from __future__ import annotations

import logging

from config import settings
from src.agents.aftersale_agent import AftersaleAgent
from src.agents.base_agent import AgentResult
from src.agents.human_agent import HumanAgent
from src.agents.order_agent import OrderAgent
from src.agents.product_agent import ProductAgent
from src.agents.router import intent_to_agent, route
from src.agents.skincare_agent import SkincareAgent
from src.emotion.detector import classify_rule
from src.rag.retriever import retrieve_context
from src.session.service import get_session_service
from src.tools.registry import get_registry
from src.utils.security import contains_sensitive, detect_prompt_injection

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
        session = await self.svc.get_session(session_id)
        if session is None:
            session = await self.svc.create_session(session_id=session_id)

        user_message = user_message.strip()
        await self.svc.save_message(session_id, "user", user_message)
        session["meta"] = await self.svc.update_meta(session_id)  # 刷新（可能被并发修改）

        # ---------- 1) 安全护栏 ----------
        bad_word = contains_sensitive(user_message)
        if bad_word:
            await self._finish(session_id, session, SENSITIVE_REPLY, "blocked_sensitive")
            return self._payload(session_id, SENSITIVE_REPLY, [], "chitchat", "normal", "blocked", {"bad_word": bad_word})
        if detect_prompt_injection(user_message):
            await self._finish(session_id, session, INJECTION_REPLY, "blocked_injection")
            return self._payload(session_id, INJECTION_REPLY, [], "chitchat", "normal", "blocked", {})

        # ---------- 2) 情绪检测 ----------
        emotion, _ = classify_rule(user_message)
        need_transfer = await self.svc.push_emotion(session_id, emotion)
        session["meta"] = await self.svc.update_meta(session_id)

        # ---------- 3) 意图路由（会话状态优先于规则；LLM 兜底带历史消解指代） ----------
        memory = await self.svc.build_memory_messages(session)
        # 记忆末尾是刚保存的本轮用户消息，剥离：路由历史与 Agent 上下文都不应重复
        if memory and memory[-1].get("role") == "user":
            memory = memory[:-1]
        step = session["meta"].get("step", "")
        intent, confidence, method = await route(user_message, emotion, history=memory)
        if step == "confirm":
            # 售后等待确认阶段：任何回复都先交给售后 Agent 判断
            intent, confidence, method = "aftersale", 1.0, "state"
        logger.info("session=%s intent=%s(%.2f,%s) emotion=%s transfer=%s", session_id, intent, confidence, method, emotion, need_transfer)

        # ---------- 4) 分发 ----------
        agent_name = intent_to_agent(intent)
        retrieved = None
        if intent in NEED_RETRIEVAL_INTENTS and agent_name in ("product", "aftersale"):
            retrieved = await retrieve_context(user_message)

        if need_transfer or intent == "transfer_human":
            result: AgentResult = await self.agents["human"].run(
                user_message, session, memory,
                emotion=emotion, trigger="emotion" if need_transfer else "user_request",
            )
        else:
            result = await self.agents[agent_name].run(
                user_message, session, memory,
                retrieved=retrieved, intent=intent, emotion=emotion,
            )

        # ---------- 5) 记忆回写 ----------
        if result.meta_updates:
            session["meta"] = await self.svc.update_meta(session_id, **result.meta_updates)
        await self._finish(session_id, session, result.reply, result.action)
        await self.svc.maybe_summarize(session)

        return self._payload(
            session_id, result.reply, result.sources, result.intent,
            emotion, result.action, result.extra,
            transferred=(need_transfer or intent == "transfer_human"),
        )

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


def get_orchestrator() -> AgentOrchestrator:
    global _orch
    if _orch is None:
        _orch = AgentOrchestrator()
    return _orch
