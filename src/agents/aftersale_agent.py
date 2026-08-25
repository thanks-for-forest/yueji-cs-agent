"""售后处理 Agent：双模式。

- 模式一（aftersale）：规则引擎 + 表单式多轮状态机（订单号→类型→资格判定→确认→生成工单）
- 模式二（policy）：售后政策/发票/会员类 RAG 问答（引用溯源）
"""
from __future__ import annotations

import re

from src.agents.base_agent import AgentResult, BaseAgent, parse_sources
from src.llm.client import get_llm
from src.session.slots import Slot, SlotFiller, is_order_id, is_phone_tail
from src.tools.aftersale_tools import check_aftersale_eligibility, create_ticket

SYSTEM_PROMPT_AFTERSALE = """你是「悦己 YUEJI 美妆」客服 Agent「小悦」，负责售后处理。

【规则】
1. 根据系统提供的售后判定结果，向用户清晰说明是否符合条件、原因、处理时效；
2. 用户确认申请后系统会生成工单，请把工单号告知用户并说明后续流程（审核1-3个工作日，退款3-7个工作日）；
3. 不符合条件时给出原因和替代方案（如换货、质量问题凭证），语气耐心专业；
4. 不承诺超出政策范围的补偿；情绪激动的用户注意安抚并建议转人工；
5. 回答简洁（120字内）。

【输出格式】直接输出给用户的话术。
"""

SYSTEM_PROMPT_POLICY = """你是「悦己 YUEJI 美妆」客服 Agent「小悦」，负责解答售后政策、发票、会员、优惠类问题。

【规则】
1. 只依据<知识片段>回答，关键事实标注〔来源: 名称〕；
2. 片段不足时明确说明并建议咨询人工，严禁编造政策条款；
3. 涉及时效/金额的信息以片段为准。

【输出格式】回复正文（含〔来源〕标注）
"""

_ORDER_ID_RE = re.compile(r"[Oo]\d{6,12}")
_PHONE_TAIL_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_TYPE_RULES = [
    ("质量问题", ["质量问题", "破损", "变质", "漏液", "碎了", "坏了"]),
    ("换货", ["换货", "换一件", "换一个"]),
    ("仅退款", ["仅退款", "不退货", "只退款"]),
    ("补发", ["补发", "错发", "漏发", "少发", "少件"]),
    ("退货退款", ["退货", "退款", "退掉", "不要了"]),
]
_CONFIRM_WORDS = ["确认", "是的", "可以", "好的", "申请", "确定", "同意", "嗯", "行"]
_DECLINE_WORDS = ["不了", "算了", "再想想", "不申请", "不用", "先不用", "等等"]


def extract_issue_type(text: str) -> str | None:
    for t, kws in _TYPE_RULES:
        for kw in kws:
            if kw in text:
                return t
    return None


def _is_confirm(text: str) -> bool:
    return any(w in text for w in _CONFIRM_WORDS)


def _is_decline(text: str) -> bool:
    return any(w in text for w in _DECLINE_WORDS)


class AftersaleAgent(BaseAgent):
    name = "aftersale"
    system_prompt = SYSTEM_PROMPT_AFTERSALE
    tool_names = []

    # ---------------- 政策问答模式 ----------------
    async def _policy_mode(self, user_message, memory_messages, retrieved) -> AgentResult:
        context = self.format_context(retrieved or [])
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_POLICY},
            *memory_messages,
        ]
        if context:
            messages.append({"role": "system", "content": f"<知识片段>\n{context}\n</知识片段>"})
        messages.append({"role": "user", "content": user_message})
        out = await self._llm_loop(messages)  # 政策问答模式无工具调用，无需 ctx
        reply = out["content"].strip()
        sources = parse_sources(reply)
        if not sources and retrieved:
            for r in retrieved[:3]:
                sources.append({"name": r["meta"].get("name", r["meta"].get("source")), "type": r["meta"]["type"], "source_id": r["meta"].get("source", "")})
        return AgentResult(reply=reply, sources=sources, intent="policy", action="none")

    # ---------------- 售后状态机 ----------------
    def _filler(self, session: dict) -> SlotFiller:
        slots_meta = session["meta"].get("slots", {}) or {}
        return SlotFiller({
            "order_id": Slot("order_id", "订单号", required=True, value=slots_meta.get("order_id"),
                             question="请提供您的**订单号**", validator=is_order_id),
            "phone_tail": Slot("phone_tail", "手机尾号", required=True, value=slots_meta.get("phone_tail"),
                               question="请提供下单**手机号的后四位**", validator=is_phone_tail),
            "issue_type": Slot("issue_type", "售后类型", required=True, value=slots_meta.get("issue_type"),
                               question="请问您需要办理哪种售后？**退货退款 / 质量问题 / 换货 / 仅退款 / 补发**"),
        })

    async def _prose(self, system: str, data: dict, user_line: str) -> str:
        """用 LLM 把结构化结果转成话术；失败时用模板兜底。"""
        try:
            llm = get_llm()
            resp = await llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"【售后判定结果】\n{data}\n\n【用户诉求】{user_line}\n请生成给用户的回复。"},
                ],
                max_tokens=400,
            )
            return resp.content.strip()
        except Exception:  # noqa: BLE001
            return self._template_reply(data)

    def _template_reply(self, data: dict) -> str:
        if data.get("created"):
            return (
                f"您的售后工单已生成：**{data['ticket_id']}**（{data['type']}）。\n"
                f"审核预计1-3个工作日，退款将在验货通过后3-7个工作日原路返回。还有其它可以帮您的吗？"
            )
        if data.get("eligible"):
            reasons = "、".join(data.get("reasons", [])) or "符合条件"
            return f"经核实，您的订单符合{data.get('order_status', '')}状态下的售后条件（{reasons}）。如需申请请回复「确认」。"
        return (
            f"抱歉，经核实您的售后申请暂不符合条件：{'；'.join(data.get('reasons', []))}。"
            + (f"您可以考虑：{data['alternative']}。" if data.get("alternative") else "如有疑问可以转接人工客服。")
        )

    async def run(self, user_message, session, memory_messages, retrieved=None, **kw):
        intent = kw.get("intent", "aftersale")
        if intent == "policy":
            return await self._policy_mode(user_message, memory_messages, retrieved)

        step = session["meta"].get("step", "")
        filler = self._filler(session)
        slots = filler.extract()

        # 提取新信息
        oid = re.search(_ORDER_ID_RE, user_message)
        if oid:
            filler.fill("order_id", oid.group(0).upper())
        tail = _PHONE_TAIL_RE.search(user_message)
        if tail:
            filler.fill("phone_tail", tail.group(1))
        itype = extract_issue_type(user_message)
        if itype:
            filler.fill("issue_type", itype)

        # ---------- 步骤2：等待确认 ----------
        if step == "confirm":
            if _is_decline(user_message):
                return AgentResult(
                    reply="好的，已为您取消本次售后申请。如需其它帮助随时告诉我～",
                    intent=intent, action="none",
                    meta_updates={"step": "", "slots": {}},
                )
            if _is_confirm(user_message) or not (oid or tail or itype):
                slots = filler.extract()
                result = await create_ticket(
                    order_id=slots["order_id"], phone_tail=slots["phone_tail"],
                    type=slots["issue_type"], reason=slots["issue_type"],
                    description=user_message,
                    user_id=session.get("user_id", "") or "",
                )
                reply = await self._prose(SYSTEM_PROMPT_AFTERSALE, result, user_message)
                action = "ticket_created" if result.get("created") else "none"
                extra = {"ticket": result.get("ticket_id", ""), "result": result} if result.get("created") else {}
                return AgentResult(
                    reply=reply, sources=[], intent=intent, action=action, extra=extra,
                    meta_updates={"step": "", "slots": slots, "ticket": result.get("ticket_id", "")},
                )

        # ---------- 步骤1：收集信息 → 资格判定 ----------
        if not filler.is_complete():
            question = filler.next_question()
            return AgentResult(
                reply=question, sources=[], intent=intent, action="clarify",
                meta_updates={"slots": filler.extract(), "step": ""},
            )

        slots = filler.extract()
        result = await check_aftersale_eligibility(
            order_id=slots["order_id"], phone_tail=slots["phone_tail"],
            issue_type=slots["issue_type"], description=user_message,
            user_id=session.get("user_id", "") or "",
        )
        reply = await self._prose(SYSTEM_PROMPT_AFTERSALE, result, user_message)
        action = "eligibility_checked"
        if result.get("eligible"):
            # 进入确认步骤
            return AgentResult(
                reply=reply + "\n\n如确认申请，请回复「确认」，我将为您生成工单。",
                sources=[], intent=intent, action="ask_confirm",
                meta_updates={"slots": slots, "step": "confirm"},
            )
        return AgentResult(
            reply=reply, sources=[], intent=intent, action="not_eligible",
            meta_updates={"slots": slots, "step": ""},
        )
