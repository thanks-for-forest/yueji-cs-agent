"""LangGraph 编排：Supervisor-Worker StateGraph 组装。

Supervisor：route_intent 节点（意图路由 + 会话状态判断）
Workers：product / order / aftersale / skincare / human 五个专项 Agent
公共节点：security（安全护栏）、emotion（情绪检测）、finalize（记忆回写/响应组装）
"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from src.agents.aftersale_agent import AftersaleAgent
from src.agents.human_agent import HumanAgent
from src.agents.order_agent import OrderAgent
from src.agents.product_agent import ProductAgent
from src.agents.skincare_agent import SkincareAgent
from src.graph import nodes
from src.graph.state import AgentState
from src.tools.registry import get_registry

logger = logging.getLogger(__name__)

_INTENT_TO_NODE = {
    "product_consult": "product",
    "chitchat": "product",
    "order_query": "order",
    "logistics": "order",
    "aftersale": "aftersale",
    "policy": "aftersale",
    "skincare_recommend": "skincare",
    "transfer_human": "human",
}


def _dispatch(state: dict) -> str:
    """Supervisor 分发：情绪转人工优先，否则按意图映射到 Worker。"""
    if state.get("need_transfer") or state.get("intent") == "transfer_human":
        return "human"
    return _INTENT_TO_NODE.get(state.get("intent", ""), "product")


def build_graph() -> StateGraph:
    """构建并绑定 Worker Agent 的 StateGraph。"""
    registry = get_registry()
    agents = {
        "product": ProductAgent(registry),
        "order": OrderAgent(registry),
        "aftersale": AftersaleAgent(registry),
        "skincare": SkincareAgent(registry),
        "human": HumanAgent(registry),
    }
    nodes.bind_agents(agents)

    g = StateGraph(AgentState)
    g.add_node("security", nodes.security_check)
    g.add_node("emotion", nodes.emotion_detect)
    g.add_node("route", nodes.route_intent)
    g.add_node("product", nodes.product_node)
    g.add_node("order", nodes.order_node)
    g.add_node("aftersale", nodes.aftersale_node)
    g.add_node("skincare", nodes.skincare_node)
    g.add_node("human", nodes.human_node)
    g.add_node("finalize", nodes.finalize)

    g.add_edge(START, "security")
    # 安全拦截直接结束（security 节点已生成 payload）
    g.add_conditional_edges("security", lambda s: "emotion" if not s.get("blocked") else END)
    g.add_edge("emotion", "route")
    g.add_conditional_edges("route", _dispatch)
    for worker in ("product", "order", "aftersale", "skincare", "human"):
        g.add_edge(worker, "finalize")
    g.add_edge("finalize", END)
    return g


_compiled = None


def get_compiled_graph():
    """进程级单例：编译后的图。LangGraph 编译图为无状态（状态随调用传入），可安全并发。"""
    global _compiled
    if _compiled is None:
        _compiled = build_graph().compile()
        logger.info("LangGraph 编排图已编译（Supervisor-Worker）")
    return _compiled
