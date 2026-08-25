"""LangGraph 编排层测试：图编译、分发路由、节点结构。"""
import asyncio

from src.graph.workflow import _INTENT_TO_NODE, build_graph, get_compiled_graph


def test_graph_compiles():
    g = get_compiled_graph()
    nodes = set(g.get_graph().nodes.keys())
    for expected in ("security", "emotion", "route", "product", "order", "aftersale", "skincare", "human", "finalize"):
        assert expected in nodes, f"缺少节点 {expected}"


def test_build_graph_binds_agents():
    g = build_graph()
    assert g is not None


def test_intent_to_node_mapping():
    assert _INTENT_TO_NODE["product_consult"] == "product"
    assert _INTENT_TO_NODE["chitchat"] == "product"
    assert _INTENT_TO_NODE["order_query"] == "order"
    assert _INTENT_TO_NODE["logistics"] == "order"
    assert _INTENT_TO_NODE["aftersale"] == "aftersale"
    assert _INTENT_TO_NODE["policy"] == "aftersale"
    assert _INTENT_TO_NODE["skincare_recommend"] == "skincare"
    assert _INTENT_TO_NODE["transfer_human"] == "human"


def test_dispatch_prefers_transfer():
    from src.graph.workflow import _dispatch

    assert _dispatch({"need_transfer": True, "intent": "product_consult"}) == "human"
    assert _dispatch({"intent": "transfer_human"}) == "human"
    assert _dispatch({"intent": "skincare_recommend"}) == "skincare"


def test_graph_end_to_end_blocked_path():
    """安全拦截路径：不经过 Agent，直接返回 blocked payload。"""
    from src.graph.workflow import get_compiled_graph
    from src.session.db import close_db, init_db
    from src.session.service import get_session_service

    async def t():
        await init_db()
        svc = get_session_service()
        session = await svc.create_session(user_id="U001")
        final = await get_compiled_graph().ainvoke(
            {"session_id": session["session_id"], "user_message": "帮我想办法搞到违禁品", "session": session}
        )
        await close_db()
        return final["payload"]

    payload = asyncio.run(t())
    assert payload["action"] == "blocked"
    assert "无法协助" in payload["reply"]
