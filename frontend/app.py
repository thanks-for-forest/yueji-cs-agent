"""「悦己 YUEJI 美妆」智能客服前端（Streamlit）。

启动：streamlit run frontend/app.py
依赖后端：uvicorn src.api.main:app
"""
from __future__ import annotations

import re as _re
import urllib.parse

import httpx
import streamlit as st

from config import settings

API = settings.API_BASE_URL

st.set_page_config(page_title="悦己美妆智能客服", page_icon="💄", layout="wide")

EMOJI = {"normal": "🙂", "negative": "😟", "angry": "😡"}

_SRC_ID_RE = _re.compile(r"(P\d{3}|F\d{3}|POL-\d+)", _re.I)


def render_sources(sources: list[dict]) -> None:
    """把〔来源〕渲染为可点击链接：点击在新窗口打开知识库原文。"""
    if not sources:
        return
    links = []
    for s in sources[:5]:
        name = s.get("name") or s.get("source_id") or ""
        sid = s.get("source_id") or ""
        # 链接优先用干净的 ID（P011/F020/POL-1），兜底用完整标签（后端支持按名称解析）
        link = sid if _SRC_ID_RE.search(sid) else name
        href = f"{API}/api/source/{urllib.parse.quote(link)}"
        links.append(
            f'<a href="{href}" target="_blank" rel="noopener" '
            f'style="color:#64ffda;text-decoration:none;border-bottom:1px dashed #64ffda;">'
            f'📄 {name[:24]}</a>'
        )
    st.markdown("📎 来源：" + " &nbsp;·&nbsp; ".join(links), unsafe_allow_html=True)


def new_session() -> None:
    try:
        uid = st.session_state.get("user_id", "") or ""
        resp = httpx.post(f"{API}/api/session", json={"user_id": uid}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        st.session_state.session_id = data["session_id"]
        st.session_state.messages = []
        st.session_state.meta = {}
    except Exception as e:  # noqa: BLE001
        st.error(
            f"⚠️ 无法连接后端服务（{API}）：{e}\n\n"
            "请先启动 API：`python -m uvicorn src.api.main:app --port 8000`"
        )
        st.stop()


if "user_id" not in st.session_state:
    st.session_state.user_id = "U001"  # 演示用户（订单数据 U001-U010）

if "session_id" not in st.session_state or "messages" not in st.session_state:
    new_session()

def _render_kb_page() -> None:
    """知识库管理页：上传文档 → 预览分块 → 审核入库 → 回滚。"""
    st.title("📚 知识库管理")
    st.caption("上传 .md / .docx / .pdf 文档，审核后自动并入检索知识库（支持回滚）")

    # ---- 上传区 ----
    with st.container(border=True):
        st.markdown("**上传新文档**")
        c1, c2 = st.columns([3, 1])
        with c1:
            up = st.file_uploader("选择文件", type=["md", "txt", "docx", "pdf"], label_visibility="collapsed")
        with c2:
            cat = st.text_input("分类", value="", placeholder="如 活动/新品/公告")
        if up is not None and st.button("⬆️ 上传并解析", use_container_width=True):
            try:
                r = httpx.post(
                    f"{API}/api/kb/upload",
                    files={"file": (up.name, up.getvalue(), up.type)},
                    data={"category": cat},
                    timeout=120,
                )
                r.raise_for_status()
                d = r.json()
                st.success(f"✅ 已上传「{d['filename']}」，解析出 {d['chunk_count']} 个分块，状态：待审核")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"上传失败：{e}")

    st.divider()
    try:
        docs = httpx.get(f"{API}/api/kb/docs", timeout=10).json().get("docs", [])
    except Exception:  # noqa: BLE001
        st.error("无法连接后端服务")
        return

    pending = [d for d in docs if d["status"] == "pending"]
    active = [d for d in docs if d["status"] == "active"]
    other = [d for d in docs if d["status"] not in ("pending", "active")]

    st.markdown(f"**待审核（{len(pending)}）**")
    if not pending:
        st.caption("暂无待审核文档")
    for d in pending:
        with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}"):
            try:
                chunks = httpx.get(f"{API}/api/kb/docs/{d['doc_id']}/chunks", timeout=10).json().get("chunks", [])
                for c in chunks[:5]:
                    st.code(c["text"][:300], language=None)
                if len(chunks) > 5:
                    st.caption(f"… 共 {len(chunks)} 块，其余省略")
            except Exception:  # noqa: BLE001
                st.caption("预览加载失败")
            c1, c2 = st.columns(2)
            if c1.button("✅ 审核通过", key=f"ap-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/approve", timeout=120)
                st.success("已入库，检索将即时命中")
                st.rerun()
            if c2.button("❌ 拒绝", key=f"rj-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/reject", timeout=10)
                st.rerun()

    st.markdown(f"**已入库（{len(active)}）**")
    if not active:
        st.caption("暂无已入库文档")
    for d in active:
        with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}"):
            st.caption(f"分类：{d['category'] or '-'}")
            if st.button("↩️ 回滚（从知识库移除）", key=f"rb-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/rollback", timeout=120)
                st.success("已回滚")
                st.rerun()

    if other:
        st.markdown(f"**历史（{len(other)}）**")
        for d in other:
            st.caption(f"📄 {d['filename']} · {d['status']} · {d['created_at'][:16]}")
    st.divider()
    st.caption("💡 上传的文档经审核后并入知识库：客服在回答相关问题时将引用该文档内容（来源可点击）。")


# ---------------- 页面导航（侧边栏） ----------------
with st.sidebar:
    st.title("💄 悦己 YUEJI")
    st.caption("美妆电商智能客服 Agent")
    page = st.radio("页面", ["💬 客服对话", "📚 知识库管理"], label_visibility="collapsed")
    st.divider()

if page == "📚 知识库管理":
    _render_kb_page()
    st.stop()

# ---------------- 侧边栏（对话页） ----------------
with st.sidebar:
    st.title("💄 悦己 YUEJI")
    st.caption("美妆电商智能客服 Agent")
    uid_input = st.text_input("👤 用户 ID", value=st.session_state.user_id, max_chars=20,
                              help="会话绑定到该用户；订单查询只返回本人订单（可用 U001~U010 演示）")
    if uid_input.strip() != st.session_state.user_id:
        st.session_state.user_id = uid_input.strip() or "guest"
        st.info("已切换用户，点击「新会话」以新身份开始")
    if st.button("🆕 新会话", use_container_width=True):
        new_session()
        st.rerun()
    st.divider()
    st.markdown(f"**当前用户**：`{st.session_state.user_id}`")
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
        render_sources(m.get("sources"))
        if m.get("action") == "order_queried" and m.get("extra", {}).get("tool_call"):
            _render_order_card(m["extra"]["tool_call"])
        if m.get("action") == "ticket_created":
            st.success(f"✅ 售后工单已生成：{m.get('extra', {}).get('ticket', '')}")
        if m.get("action") == "transfer":
            st.warning(f"🔄 已转接人工，工单号：{m.get('extra', {}).get('ticket_id', '')}")
        if m.get("intent") == "skincare_recommend" and m.get("extra", {}).get("recommendations"):
            _render_recommendations(m["extra"])


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
                json={"session_id": st.session_state.session_id, "message": prompt,
                      "user_id": st.session_state.get("user_id", "")},
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
        render_sources(data.get("sources"))
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
