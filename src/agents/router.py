"""意图路由：规则（关键词优先级）→ LLM 兜底分类。

优先级：人工转接 > 售后 > 订单/物流 > 护肤推荐 > 商品咨询/闲聊。
"""
from __future__ import annotations

import logging

from config import settings
from src.llm.client import get_llm

logger = logging.getLogger(__name__)

# 意图全集（与测试集一致）
INTENTS = [
    "product_consult", "order_query", "logistics", "aftersale", "policy",
    "skincare_recommend", "chitchat", "transfer_human",
]

_RULES: list[tuple[str, list[str]]] = [
    ("transfer_human", ["转人工", "人工客服", "找人工", "真人客服", "投诉专员", "人工！"]),
    # ---- 售后咨询类（政策 RAG，优先于申请类）----
    ("policy", ["售后政策", "退换政策", "退货流程", "怎么退", "能退吗", "可以退吗", "还能退", "还能退货",
                "退款多久", "多久到账", "运费", "运费险", "开发票", "发票", "会员", "积分", "优惠", "活动",
                "优惠券", "价格保护", "七天无理由", "审核多久", "多久能退", "破损怎么", "质量问题怎么",
                "退换货流程", "包邮", "流程是怎样的"]),
    # ---- 售后申请类（进入状态机）----
    ("aftersale", ["我要退货", "申请退", "想退货", "办理", "申请售后", "退货退款", "我要退款", "退掉",
                   "想换货", "申请换货", "仅退款", "补发", "换货", "退货", "退款", "售后",
                   "破损了", "质量有问题", "错发", "漏发", "少件", "缺件", "不想要了"]),
    ("order_query", ["订单号", "查一下我的订单", "查订单", "查一下订单", "我的订单", "待付款", "待发货", "取消订单", "下单了没", "我的订单号"]),
    ("logistics", ["物流", "快递", "到哪了", "到哪", "发货了", "几天到", "签收", "配送", "派送", "运单"]),
    ("skincare_recommend", ["推荐", "适合什么", "肤质", "油皮", "干皮", "敏感肌用", "搭配", "护肤步骤",
                            "水乳推荐", "选什么", "买什么好", "控油推荐", "痘痘肌", "混合皮", "用什么"]),
    ("transfer_human", ["投诉", "315", "曝光", "律师", "起诉", "维权", "媒体"]),
]

_STRONG = {
    "售后": "aftersale", "退货": "aftersale", "退款": "aftersale", "换货": "aftersale",
    "人工": "transfer_human", "投诉": "transfer_human",
    "物流": "logistics", "快递": "logistics",
}


def _rule_route(text: str) -> tuple[str, float] | None:
    """规则匹配：返回 (intent, score)。"""
    for intent, kws in _RULES:
        for kw in kws:
            if kw in text:
                return intent, 0.95
    # 强信号词（更高优先，避免被弱关键词抢占）
    for kw, intent in _STRONG.items():
        if kw in text:
            return intent, 0.98
    return None


async def route(text: str, emotion: str = "normal") -> tuple[str, float, str]:
    """返回 (intent, confidence, method: rule|llm)。"""
    if emotion == "angry":
        return "transfer_human", 1.0, "emotion"

    hit = _rule_route(text)
    if hit:
        return hit[0], hit[1], "rule"

    # LLM 兜底分类
    try:
        llm = get_llm()
        resp = await llm.chat(
            [
                {"role": "system", "content": (
                    "你是客服意图分类器。把用户消息归类为以下之一（只输出类别名）：\n"
                    "product_consult=商品/成分/功效/价格/使用方法咨询；order_query=查订单；logistics=查物流；\n"
                    "aftersale=退换货/售后；policy=售后政策/发票/会员/优惠；skincare_recommend=护肤推荐/肤质搭配；\n"
                    "chitchat=打招呼/闲聊/无关话题；transfer_human=要求人工客服。" 
                )},
                {"role": "user", "content": text},
            ],
            max_tokens=20,
            temperature=0,
        )
        intent = resp.content.strip().strip('"').strip("'").splitlines()[0].strip()
        if intent not in INTENTS:
            intent = "chitchat"
        return intent, 0.7, "llm"
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 分类失败，回退 chitchat：%s", e)
        return "chitchat", 0.5, "fallback"


def intent_to_agent(intent: str) -> str:
    """意图 → Agent 名。"""
    mapping = {
        "product_consult": "product",
        "chitchat": "product",
        "order_query": "order",
        "logistics": "order",
        "aftersale": "aftersale",
        "policy": "aftersale",
        "skincare_recommend": "skincare",
        "transfer_human": "human",
    }
    return mapping.get(intent, "product")
