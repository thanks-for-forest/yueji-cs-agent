"""商品咨询 Agent：RAG 问答 + 引用溯源 + 澄清/拒答。"""
from __future__ import annotations

from src.agents.base_agent import AgentResult, BaseAgent, parse_sources

SYSTEM_PROMPT_PRODUCT = """你是「悦己 YUEJI 美妆」官方客服 Agent「小悦」，负责商品咨询与一般对话。

【输入格式】
<知识片段>
[来源: 产品名(编号) 原文片段] ...
</知识片段>
<对话历史>...</对话历史>
<用户问题>...</用户问题>

【硬性规则】
1. 优先依据<知识片段>回答；每个关键事实断言后标注〔来源: 名称(编号)〕；
2. 片段不足或与问题无关时，明确说明"这个问题我需要确认一下"，并追问具体产品/问题，严禁编造；
3. 价格/库存/成分/功效以片段为准，不推测；
4. 功效表述使用"有助于/可改善/帮助"等合规措辞，不做绝对化承诺；
5. 用户提到敏感肌、孕妇、儿童等特殊人群时，必须提示"建议先做皮肤测试/遵医嘱"；
6. 遇到打招呼/闲聊（如"你好""谢谢""在吗"），简短友好回应并引导回购物话题；
7. 回答简洁自然（一般150字内），口语化但不失专业；
8. 用户的问题涉及订单/物流/售后/退换货时，礼貌告知"这类问题请让我为您转接对应服务"，并继续服务。

【输出格式】回复正文（含〔来源〕标注）
"""


class ProductAgent(BaseAgent):
    name = "product"
    system_prompt = SYSTEM_PROMPT_PRODUCT
    tool_names = ["search_product", "get_product"]

    async def run(self, user_message, session, memory_messages, retrieved=None, **kw):
        intent = kw.get("intent", "product_consult")
        context = self.format_context(retrieved or [])
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
        ]
        messages.extend(memory_messages)
        if context:
            messages.append({"role": "system", "content": f"<知识片段>\n{context}\n</知识片段>"})
        messages.append({"role": "user", "content": user_message})

        out = await self._llm_loop(messages)
        reply = out["content"].strip()
        sources = parse_sources(reply)
        # 若回复未标注来源，但使用了检索片段，自动附上（用于前端展示）
        if not sources and retrieved:
            for r in retrieved[:3]:
                sources.append({"name": r["meta"].get("name", r["meta"].get("source")), "type": r["meta"]["type"], "source_id": r["meta"].get("source", "")})

        # 澄清/拒答判定
        action = "none"
        if "我需要确认" in reply or "需要确认一下" in reply:
            action = "clarify"
        if not retrieved and "来源" not in reply and intent != "chitchat":
            # 无检索结果且未引用 → 提示不可信
            pass

        # 尝试提取最近产品（澄清策略用）
        last_product = kw.get("last_product", "")
        for r in retrieved or []:
            if r["meta"]["type"] == "product":
                last_product = r["meta"].get("name", "")
                break
        if not last_product:
            import re

            for src in sources:
                m = re.match(r"(.+?)[（(]?P\d{3}", src.get("name", ""))
                if m:
                    last_product = m.group(1).strip()

        return AgentResult(
            reply=reply,
            sources=sources,
            intent=intent,
            action=action,
            meta_updates={"last_product": last_product} if last_product else {},
        )
