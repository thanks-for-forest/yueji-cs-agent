"""订单查询 Agent：槽位填充状态机 + Function Calling 工具调用。"""
from __future__ import annotations

import re

from src.agents.base_agent import AgentResult, BaseAgent, parse_sources
from src.session.slots import Slot, SlotFiller, is_order_id, is_phone_tail

SYSTEM_PROMPT_ORDER = """你是「悦己 YUEJI 美妆」客服 Agent「小悦」，负责订单与物流查询。

【规则】
1. 系统会在消息中告知已确认的槽位（订单号/手机尾号）；槽位齐全时必须调用 query_order 或 query_logistics 工具查询；
2. 工具返回 found=false 时，礼貌请用户核对订单号与手机尾号，不要编造订单信息；
3. 查询成功后，用简洁友好的话术呈现：订单状态、商品、金额、物流最新动态；金额用¥符号；
4. 订单状态枚举：待付款/待发货/已发货/已完成/已取消/退款中；
5. 用户若未提供完整信息，只追问缺少的那一项（订单号 或 手机尾号），一次只问一个；
6. 涉及退款/退货诉求时，提示"如需退换货，我可以为您转接售后专员"，不要自行处理售后。

【输出格式】直接输出给用户的话术。
"""

_ORDER_ID_RE = re.compile(r"[Oo]\d{6,12}")
_PHONE_TAIL_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def extract_order_id(text: str) -> str | None:
    m = _ORDER_ID_RE.search(text)
    return m.group(0).upper() if m else None


def extract_phone_tail(text: str) -> str | None:
    matches = _PHONE_TAIL_RE.findall(text)
    if not matches:
        return None
    return matches[-1]


class OrderAgent(BaseAgent):
    name = "order"
    system_prompt = SYSTEM_PROMPT_ORDER
    tool_names = ["query_order", "query_logistics"]

    def _filler(self, session: dict) -> SlotFiller:
        slots_meta = session["meta"].get("slots", {}) or {}
        return SlotFiller({
            "order_id": Slot("order_id", "订单号", required=True,
                             value=slots_meta.get("order_id"),
                             question="好的，请提供您的**订单号**（下单后短信/订单页可查）",
                             validator=is_order_id),
            "phone_tail": Slot("phone_tail", "手机尾号", required=True,
                               value=slots_meta.get("phone_tail"),
                               question="请提供下单**手机号的后四位**，用于核对订单",
                               validator=is_phone_tail),
        })

    async def run(self, user_message, session, memory_messages, retrieved=None, **kw):
        intent = kw.get("intent", "order_query")
        filler = self._filler(session)

        # 1) 从用户消息提取槽位
        order_id = extract_order_id(user_message)
        if order_id:
            filler.fill("order_id", order_id)
        tail = extract_phone_tail(user_message)
        if tail:
            filler.fill("phone_tail", tail)

        # 2) 槽位不齐 → 追问
        if not filler.is_complete():
            question = filler.next_question()
            return AgentResult(
                reply=question,
                sources=[],
                intent=intent,
                action="clarify",
                meta_updates={"slots": filler.extract()},
            )

        # 3) 槽位齐全 → 通过 LLM 调用工具
        slots = filler.extract()
        tool_hint = (
            f"【已确认槽位】订单号={slots['order_id']}，手机尾号={slots['phone_tail']}。"
            f"请调用 {'query_logistics' if intent == 'logistics' else 'query_order'} 工具查询。"
        )
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            *memory_messages,
            {"role": "user", "content": tool_hint + "\n用户问题：" + user_message},
        ]
        out = await self._llm_loop(messages)
        reply = out["content"].strip()

        # 4) 结构化输出（前端订单卡片）：从工具执行记录还原
        extra: dict = {}
        tools_used = out.get("tools_used", [])
        for tc in tools_used:
            if tc["name"] in ("query_order", "query_logistics"):
                extra["tool_call"] = {"name": tc["name"], "arguments": tc["arguments"]}

        return AgentResult(
            reply=reply,
            sources=parse_sources(reply),
            intent=intent,
            action="order_queried" if tools_used else "none",
            extra=extra,
            meta_updates={"slots": slots},
        )
