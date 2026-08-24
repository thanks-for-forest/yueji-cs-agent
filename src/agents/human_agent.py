"""人工转接 Agent：致歉 → 生成转人工工单（含对话摘要）→ 告知转接。"""
from __future__ import annotations

from datetime import datetime

from src.agents.base_agent import AgentResult, BaseAgent
from src.session.db import get_conn

APOLOGY_BY_EMOTION = {
    "angry": "非常抱歉给您带来了这么不好的体验，您的情绪我们完全理解，请先消消气🙏。",
    "negative": "抱歉给您带来了不好的体验，我理解您的心情😔。",
    "normal": "好的，这就为您转接人工客服专员。",
}

SYSTEM_PROMPT_HUMAN = """你是「悦己 YUEJI 美妆」客服 Agent「小悦」。用户要求转接人工客服。

【规则】
1. 先真诚致歉/共情，再告知转接，语气温和，避免用户觉得被"甩锅"；
2. 告知已生成转接工单号、预计接入时间（1-3分钟内）；
3. 说明人工客服已看到对话记录，无需重复描述；
4. 回复控制在80字内。
"""


class HumanAgent(BaseAgent):
    name = "human"
    system_prompt = SYSTEM_PROMPT_HUMAN
    tool_names = []

    async def run(self, user_message, session, memory_messages, retrieved=None, **kw):
        emotion = kw.get("emotion", "normal")
        trigger = kw.get("trigger", "user_request")

        # 1) 生成转人工工单（含摘要）
        summary_lines = [f"{m['role']}: {m['content'][:120]}" for m in memory_messages[-8:]]
        summary = "\n".join(summary_lines) if summary_lines else user_message[:200]
        import uuid

        ticket_id = f"TR{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4].upper()}"
        conn = await get_conn()
        await conn.execute(
            "INSERT INTO tickets (ticket_id, session_id, user_id, type, reason, description, evidence, condition_check, status, emotion, summary, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ticket_id, session.get("session_id"), session.get("user_id") or "", "转人工",
                "情绪升级" if trigger == "emotion" else "用户主动要求转人工",
                user_message[:500], "[]", "{}", "已转接", emotion, summary,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        await conn.commit()

        # 2) 生成致歉+转接话术
        apology = APOLOGY_BY_EMOTION.get(emotion, APOLOGY_BY_EMOTION["normal"])
        reply = (
            f"{apology}\n"
            f"我已把您的问题和对话记录整理好（转接工单号：**{ticket_id}**），"
            f"人工客服专员预计 **1-3分钟** 内接入，请稍等。您也可以直接回复「人工」重新接入。"
        )

        return AgentResult(
            reply=reply,
            sources=[],
            intent="transfer_human",
            action="transfer",
            extra={"ticket_id": ticket_id, "trigger": trigger, "emotion": emotion},
            meta_updates={"ticket": ticket_id, "step": ""},
        )
