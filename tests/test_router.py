"""意图路由测试（同步包装异步路由）。"""
import asyncio

import pytest

from src.agents.router import intent_to_agent, route


def _route(text, emotion="normal"):
    return asyncio.run(route(text, emotion))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("我要退货", "aftersale"),
        ("退货流程是怎样的", "policy"),
        ("超过7天还能退货吗", "policy"),
        ("查一下订单 O202600001", "order_query"),
        ("我的快递到哪了", "logistics"),
        ("我是油皮推荐什么", "skincare_recommend"),
        ("转人工", "transfer_human"),
        ("投诉315", "transfer_human"),
    ],
)
def test_rule_route(text, expected):
    intent, conf, method = _route(text)
    assert intent == expected, f"{text} -> {intent}"
    assert method == "rule"


def test_ambiguous_intent_via_llm():
    """无强规则信号时由 LLM 兜底，意图仍应正确。"""
    intent, conf, method = _route("烟酰胺精华适合敏感肌吗")
    assert intent == "product_consult"
    assert method == "llm"


def test_llm_fallback_for_ambiguous():
    """规则未命中时应走 LLM 兜底且返回合法意图。"""
    intent, conf, method = _route("说说你们家的历史吧")
    assert intent in ("product_consult", "chitchat", "policy")


def test_angry_emotion_forces_transfer():
    intent, conf, method = _route("我要投诉", emotion="angry")
    assert intent == "transfer_human"
    assert method == "emotion"


def test_intent_to_agent_mapping():
    assert intent_to_agent("product_consult") == "product"
    assert intent_to_agent("chitchat") == "product"
    assert intent_to_agent("order_query") == "order"
    assert intent_to_agent("logistics") == "order"
    assert intent_to_agent("aftersale") == "aftersale"
    assert intent_to_agent("policy") == "aftersale"
    assert intent_to_agent("skincare_recommend") == "skincare"
    assert intent_to_agent("transfer_human") == "human"
