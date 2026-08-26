"""LangGraph 编排：图节点（安全 → 情绪 → 路由 → Worker Agent → 记忆回写）。

节点复用现有 Agent 实现，仅做编排层改造；所有逻辑与原 orchestrator.handle 对齐，
保证评测/接口行为一致。
"""
from __future__ import annotations

import logging

from config import settings
from src.agents.router import route
from src.emotion.detector import classify_rule
from src.rag.retriever import catalog_context, is_catalog_query, retrieve_context
from src.session.service import get_session_service
from src.utils.security import contains_sensitive, detect_prompt_injection
from src.utils.tracing import Tracer

logger = logging.getLogger(__name__)

SENSITIVE_REPLY = "抱歉，这个话题我无法协助。如有购物相关问题（商品、订单、售后、护肤推荐），欢迎随时告诉我～"
INJECTION_REPLY = "抱歉，我只能提供商品咨询、订单查询、售后处理与护肤推荐服务。如有需要，请直接告诉我您的需求～"
NEED_RETRIEVAL_INTENTS = {"product_consult", "policy", "chitchat"}

_agents: dict[str, object] = {}


def bind_agents(agents: dict[str, object]) -> None:
    """注入 5 个 Worker Agent（由 workflow 构建时调用）。"""
    global _agents
    _agents = agents


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


# ---------------- 节点 1：安全护栏 ----------------
async def security_check(state: dict) -> dict:
    async with Tracer.span("security"):
        return await _security_check_impl(state)


async def _security_check_impl(state: dict) -> dict:
    svc = get_session_service()
    sid = state["session_id"]
    msg = state["user_message"]
    bad = contains_sensitive(msg)
    if bad:
        await svc.save_message(sid, "assistant", SENSITIVE_REPLY)
        await svc.touch(sid)
        return {
            "blocked": True, "blocked_reason": "sensitive",
            "payload": _payload(sid, SENSITIVE_REPLY, [], "chitchat", "normal", "blocked", {"bad_word": bad}),
        }
    if detect_prompt_injection(msg):
        await svc.save_message(sid, "assistant", INJECTION_REPLY)
        await svc.touch(sid)
        return {
            "blocked": True, "blocked_reason": "injection",
            "payload": _payload(sid, INJECTION_REPLY, [], "chitchat", "normal", "blocked", {}),
        }
    return {"blocked": False}


# ---------------- 节点 2：情绪检测 ----------------
async def emotion_detect(state: dict) -> dict:
    async with Tracer.span("emotion"):
        return await _emotion_detect_impl(state)


async def _emotion_detect_impl(state: dict) -> dict:
    svc = get_session_service()
    sid = state["session_id"]
    emotion, _ = classify_rule(state["user_message"])
    need_transfer = await svc.push_emotion(sid, emotion)
    session = await svc.get_session(sid)  # 刷新 meta（push_emotion 已更新情绪历史）
    return {"emotion": emotion, "need_transfer": need_transfer, "session": session}


# ---------------- 节点 3：意图路由（Supervisor） ----------------
async def route_intent(state: dict) -> dict:
    async with Tracer.span("route"):
        return await _route_intent_impl(state)


async def _route_intent_impl(state: dict) -> dict:
    svc = get_session_service()
    session = state["session"]
    memory = await svc.build_memory_messages(session)
    if memory and memory[-1].get("role") == "user":
        memory = memory[:-1]  # 剥离本轮用户消息（Agent 会自行注入）
    step = session["meta"].get("step", "")
    intent, confidence, method = await route(state["user_message"], state["emotion"], history=memory)
    if step == "confirm":
        intent, confidence, method = "aftersale", 1.0, "state"
    logger.info("session=%s intent=%s(%.2f,%s) emotion=%s transfer=%s",
                state["session_id"], intent, confidence, method, state["emotion"], state.get("need_transfer"))
    return {"intent": intent, "confidence": confidence, "route_method": method, "memory": memory}


def _enrich_query(msg: str, session: dict) -> str:
    """指代性/短句查询：拼上会话中最近讨论的产品名，提升检索针对性（如"那适合敏感肌吗"）。"""
    meta = session.get("meta") or {}
    last = meta.get("last_product", "")
    if not last or not msg.strip():
        return msg
    if last in msg:
        return msg
    if len(msg) <= 12 or any(w in msg for w in ("那", "这", "它", "该产品", "这款", "这个", "那个")):
        return f"{msg}（{last}）"
    return msg


# ---------------- Worker Agent 节点（通用执行器） ----------------
async def _run_agent(state: dict, agent_name: str, trigger: str = "") -> dict:
    agent = _agents[agent_name]
    session, memory = state["session"], state.get("memory", [])
    kw: dict = {"intent": state.get("intent"), "emotion": state.get("emotion")}
    if trigger:
        kw["trigger"] = trigger
    retrieved = None
    if state.get("intent") in NEED_RETRIEVAL_INTENTS and agent_name in ("product", "aftersale"):
        query = _enrich_query(state["user_message"], session)
        retrieved = await retrieve_context(query)
        # 泛化导购兜底：检索为空时给出热门产品目录
        if not retrieved and state.get("intent") in ("product_consult", "chitchat") and is_catalog_query(state["user_message"]):
            retrieved = catalog_context(state["user_message"])
            kw["catalog_mode"] = True
    async with Tracer.span(f"agent:{agent_name}"):
        result = await agent.run(state["user_message"], session, memory, retrieved=retrieved, **kw)
    return {"result": result.to_dict(), "session": session}


async def product_node(state: dict) -> dict:
    return await _run_agent(state, "product")


async def order_node(state: dict) -> dict:
    return await _run_agent(state, "order")


async def aftersale_node(state: dict) -> dict:
    return await _run_agent(state, "aftersale")


async def skincare_node(state: dict) -> dict:
    return await _run_agent(state, "skincare")


async def human_node(state: dict) -> dict:
    trigger = "emotion" if state.get("need_transfer") else "user_request"
    return await _run_agent(state, "human", trigger=trigger)


# ---------------- 节点 4：记忆回写 + 响应组装 ----------------
async def finalize(state: dict) -> dict:
    async with Tracer.span("finalize"):
        return await _finalize_impl(state)


async def _finalize_impl(state: dict) -> dict:
    svc = get_session_service()
    sid = state["session_id"]
    session = state["session"]
    result = state["result"]
    if result.get("meta_updates"):
        session["meta"] = await svc.update_meta(sid, **result["meta_updates"])
    await svc.save_message(sid, "assistant", result["reply"])
    await svc.touch(sid)
    await svc.maybe_summarize(session)
    payload = _payload(
        sid, result["reply"], result.get("sources", []), result.get("intent", state.get("intent", "")),
        state.get("emotion", "normal"), result.get("action", "none"), result.get("extra", {}),
        transferred=(state.get("need_transfer") or state.get("intent") == "transfer_human"),
    )
    return {"payload": payload}
