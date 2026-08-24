"""「悦己 YUEJI 美妆」智能客服前端（Streamlit）。

启动：streamlit run frontend/app.py
依赖后端：uvicorn src.api.main:app
"""
from __future__ import annotations

import httpx
import streamlit as st

from config import settings

API = f"http://127.0.0.1:{settings.API_PORT}"

st.set_page_config(page_title="悦己美妆智能客服", page_icon="💄", layout="wide")

EMOJI = {"normal": "🙂", "negative": "😟", "angry": "😡"}


def new_session() -> None:
    resp = httpx.post(f"{API}/api/session")
    data = resp.json()
    st.session_state.session_id = data["session_id"]
    st.session_state.messages = []
    st.session_state.meta = {}


if "session_id" not in st.session_state or "messages" not in st.session_state:
    new_session()

# ---------------- 侧边栏 ----------------
with st.sidebar:
    st.title("💄 悦己 YUEJI")
    st.caption("美妆电商智能客服 Agent")
    if st.button("🆕 新会话", use_container_width=True):
        new_session()
        st.rerun()
    st.divider()
    st.markdown("**会话 ID**")
    st.code(st.session_state.session_id, language=None)
    st.divider()
    st.markdown("**可以这样问**")
    st.caption("• 这款面霜适合敏感肌吗\n• 查一下我的订单\n• 我要退货\n• 我是油皮推荐什么\n• 售后政策是怎样的")
    st.divider()
    st.caption("v1.0 · DeepSeek + RAG + Function Calling")

# ---------------- 主区域 ----------------
st.title("💬 小悦 · 悦己美妆客服")
st.caption("商品咨询 · 订单查询 · 退换货 · 护肤推荐 · 情绪转人工")

# 会话状态条
meta = st.session_state.get("meta", {})
cols = st.columns(4)
cols[0].metric("会话状态", meta.get("emotion", "normal"), delta=None)
cols[1].metric("当前意图", meta.get("intent", "-"))
cols[2].metric("转人工", "✅ 已转接" if meta.get("transferred") else "-")
cols[3].metric("工单", meta.get("ticket", "-"))

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        m = msg.get("meta", {})
        if m.get("sources"):
            srcs = " · ".join(f"`{s['name']}`" for s in m["sources"][:3])
            st.caption(f"📎 来源：{srcs}")
        if m.get("action") == "order_queried" and m.get("extra", {}).get("tool_call"):
            _render_order_card(m["extra"]["tool_call"])
        if m.get("action") == "ticket_created":
            st.success(f"✅ 售后工单已生成：{m.get('extra', {}).get('ticket', '')}")
        if m.get("action") == "transfer":
            st.warning(f"🔄 已转接人工，工单号：{m.get('extra', {}).get('ticket_id', '')}")
        if m.get("intent") == "skincare_recommend" and m.get("extra", {}).get("recommendations"):
            _render_recommendations(m["extra"])


def _render_order_card(tool_call: dict) -> None:
    """根据工具调用参数重新查询订单并渲染卡片。"""
    args = tool_call.get("arguments", {})
    oid = args.get("order_id", "")
    tail = args.get("phone_tail", "")
    if not oid:
        return
    try:
        resp = httpx.get(f"{API}/api/order/{oid}", params={"phone_tail": tail}, timeout=10)
        if resp.status_code != 200:
            return
        order = resp.json()
        with st.container(border=True):
            st.markdown(f"📦 **{order['order_id']}** · {order['status']}")
            items = order.get("items", [])
            for it in items:
                st.markdown(f"- {it['name']} ×{it['qty']}  ¥{it['price']}")
            st.markdown(f"**合计：¥{order['total_amount']}**")
            if order.get("latest_event"):
                st.caption(f"🚚 最新物流：{order['latest_event']['desc']}（{order['latest_event']['time']}）")
    except Exception:  # noqa: BLE001
        pass


def _render_recommendations(extra: dict) -> None:
    recs = extra.get("recommendations", [])
    if not recs:
        return
    st.markdown("#### ✨ 为你推荐")
    cols = st.columns(len(recs))
    for col, rec in zip(cols, recs):
        with col:
            with st.container(border=True):
                st.markdown(f"**{rec['name']}**")
                st.markdown(f"¥{rec['price']} · {rec.get('category', '')}")
                st.caption(" / ".join(rec.get("efficacy", [])[:2]))
                st.caption("✓ " + "；".join(rec.get("reasons", [])[:2]))
    if extra.get("routine"):
        st.markdown("**搭配建议**：")
        st.markdown(" → ".join(f"{r['name']}（¥{r['price']}）" for r in extra["routine"]))


# ---------------- 输入 ----------------
if prompt := st.chat_input("请输入您的问题…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""
        data = {}
        try:
            with httpx.stream(
                "POST",
                f"{API}/api/chat/stream",
                json={"session_id": st.session_state.session_id, "message": prompt},
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        ev = __import__("json").loads(payload)
                    except Exception:  # noqa: BLE001
                        continue
                    if ev.get("type") == "delta":
                        full_text += ev["text"]
                        placeholder.markdown(full_text + "▌")
                    elif ev.get("type") == "done":
                        data = ev.get("result", {})
        except Exception as e:  # noqa: BLE001
            placeholder.error(f"服务异常：{e}")
            st.session_state.messages.pop()
            st.stop()

        placeholder.markdown(full_text)
        if data.get("sources"):
            srcs = " · ".join(f"`{s['name']}`" for s in data["sources"][:3])
            st.caption(f"📎 来源：{srcs}")
        if data.get("action") == "order_queried" and data.get("extra", {}).get("tool_call"):
            _render_order_card(data["extra"]["tool_call"])
        if data.get("action") == "ticket_created":
            st.success(f"✅ 售后工单已生成：{data.get('extra', {}).get('ticket', '')}")
        if data.get("action") == "transfer":
            st.warning(f"🔄 已转接人工，工单号：{data.get('extra', {}).get('ticket_id', '')}")
        if data.get("intent") == "skincare_recommend" and data.get("extra", {}).get("recommendations"):
            _render_recommendations(data["extra"])

        st.session_state.messages.append({
            "role": "assistant",
            "content": full_text,
            "meta": data,
        })
        st.session_state.meta = {
            "emotion": f"{EMOJI.get(data.get('emotion', 'normal'), '')} {data.get('emotion', 'normal')}",
            "intent": data.get("intent", "-"),
            "transferred": data.get("transferred", False),
            "ticket": data.get("extra", {}).get("ticket") or data.get("extra", {}).get("ticket_id", "-"),
        }
        st.rerun()
