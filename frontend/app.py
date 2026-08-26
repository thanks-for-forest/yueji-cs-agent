"""「悦己 YUEJI 美妆」智能客服前端（Streamlit）—— 四视图架构。

视图：🏠 门户（游客AI客服）｜ 👤 登录/注册 → 用户专属AI客服 ｜ 🔐 管理员 → 知识库管理
启动：streamlit run frontend/app.py（依赖后端 uvicorn :8000）
"""
from __future__ import annotations

import json as _json
import re as _re
import urllib.parse

import httpx
import streamlit as st

from config import settings

API = settings.API_BASE_URL

st.set_page_config(page_title="悦己美妆智能客服", page_icon="💄", layout="wide")

EMOJI = {"normal": "🙂", "negative": "😟", "angry": "😡"}
_SRC_ID_RE = _re.compile(r"(P\d{3}|F\d{3}|POL-\d+|KB-\d+)", _re.I)


def render_sources(sources: list[dict]) -> None:
    """把〔来源〕渲染为可点击链接：点击在新窗口打开知识库原文。"""
    if not sources:
        return
    links = []
    for s in sources[:5]:
        name = s.get("name") or s.get("source_id") or ""
        sid = s.get("source_id") or ""
        link = sid if _SRC_ID_RE.search(sid) else name
        href = f"{API}/api/source/{urllib.parse.quote(link)}"
        links.append(
            f'<a href="{href}" target="_blank" rel="noopener" '
            f'style="color:#64ffda;text-decoration:none;border-bottom:1px dashed #64ffda;">'
            f'📄 {name[:24]}</a>'
        )
    st.markdown("📎 来源：" + " &nbsp;·&nbsp; ".join(links), unsafe_allow_html=True)


# ---------------- 会话管理（按用户隔离） ----------------
def _new_session(user_id: str, auth_token: str = "") -> None:
    try:
        headers = {"X-Auth-Token": auth_token} if auth_token else {}
        resp = httpx.post(f"{API}/api/session", json={"user_id": user_id}, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        st.session_state[f"session_id_{user_id}"] = data["session_id"]
        st.session_state[f"messages_{user_id}"] = []
        st.session_state[f"meta_{user_id}"] = {}
    except Exception as e:  # noqa: BLE001
        st.error(f"⚠️ 无法连接后端服务（{API}）：{e}\n\n请先启动 API：`python -m uvicorn src.api.main:app --port 8000`")
        st.stop()


def _chat_headers(auth_token: str = "") -> dict:
    return {"X-Auth-Token": auth_token} if auth_token else {}


# ---------------- 客服对话视图（门户游客 / 登录用户共用） ----------------
def _render_chat(user_id: str, auth_token: str = "", title: str = "💬 小悦 · 悦己美妆客服") -> None:
    sid_key = f"session_id_{user_id}"
    msg_key = f"messages_{user_id}"
    meta_key = f"meta_{user_id}"
    if sid_key not in st.session_state:
        _new_session(user_id, auth_token)

    st.title(title)
    st.caption("商品咨询 · 订单查询 · 退换货 · 护肤推荐 · 情绪转人工")

    meta = st.session_state.get(meta_key, {})
    cols = st.columns(4)
    cols[0].metric("会话状态", meta.get("emotion", "normal"), delta=None)
    cols[1].metric("当前意图", meta.get("intent", "-"))
    cols[2].metric("转人工", "✅ 已转接" if meta.get("transferred") else "-")
    cols[3].metric("工单", meta.get("ticket", "-"))

    for msg in st.session_state.get(msg_key, []):
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

    if prompt := st.chat_input("请输入您的问题…"):
        msgs = st.session_state.setdefault(msg_key, [])
        msgs.append({"role": "user", "content": prompt})
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
                    json={"session_id": st.session_state[sid_key], "message": prompt, "user_id": user_id},
                    headers=_chat_headers(auth_token),
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
                            ev = _json.loads(payload)
                        except Exception:  # noqa: BLE001
                            continue
                        if ev.get("type") == "delta":
                            full_text += ev["text"]
                            placeholder.markdown(full_text + "▌")
                        elif ev.get("type") == "done":
                            data = ev.get("result", {})
            except Exception as e:  # noqa: BLE001
                placeholder.error(f"服务异常：{e}")
                msgs.pop()
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

            msgs.append({"role": "assistant", "content": full_text, "meta": data})
            st.session_state[meta_key] = {
                "emotion": f"{EMOJI.get(data.get('emotion', 'normal'), '')} {data.get('emotion', 'normal')}",
                "intent": data.get("intent", "-"),
                "transferred": data.get("transferred", False),
                "ticket": data.get("extra", {}).get("ticket") or data.get("extra", {}).get("ticket_id", "-"),
            }
            st.rerun()


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
            for it in order.get("items", []):
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


# ---------------- 知识库管理（管理员视图） ----------------
def _admin_headers() -> dict:
    return {"X-Admin-Token": st.session_state.get("admin_token", ""),
            "X-Admin-Name": st.session_state.get("admin_name", "admin") or "admin"}


def _render_kb_page() -> None:
    st.title("📚 知识库管理")
    st.caption("上传 .md / .docx / .pdf 文档，审核后自动并入检索知识库（支持回滚）｜ 管理员专属，操作留痕")

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
                    headers=_admin_headers(),
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
        docs = httpx.get(f"{API}/api/kb/docs", headers=_admin_headers(), timeout=10).json().get("docs", [])
    except Exception:  # noqa: BLE001
        st.error("无法连接后端服务（或管理员令牌已失效）")
        return

    pending = [d for d in docs if d["status"] == "pending"]
    active = [d for d in docs if d["status"] == "active"]
    other = [d for d in docs if d["status"] not in ("pending", "active")]

    st.markdown(f"**待审核（{len(pending)}）**")
    if not pending:
        st.caption("暂无待审核文档")
    for d in pending:
        with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}"
                         f"（上传人：{d.get('created_by') or '-'}）"):
            try:
                chunks = httpx.get(f"{API}/api/kb/docs/{d['doc_id']}/chunks", headers=_admin_headers(), timeout=10).json().get("chunks", [])
                for c in chunks[:5]:
                    st.code(c["text"][:300], language=None)
                if len(chunks) > 5:
                    st.caption(f"… 共 {len(chunks)} 块，其余省略")
            except Exception:  # noqa: BLE001
                st.caption("预览加载失败")
            c1, c2 = st.columns(2)
            if c1.button("✅ 审核通过", key=f"ap-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/approve", headers=_admin_headers(), timeout=120)
                st.success("已入库，检索将即时命中")
                st.rerun()
            if c2.button("❌ 拒绝", key=f"rj-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/reject", headers=_admin_headers(), timeout=10)
                st.rerun()

    st.markdown(f"**已入库（{len(active)}）**")
    if not active:
        st.caption("暂无已入库文档")
    for d in active:
        with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}"
                         f"（审核人：{d.get('approved_by') or '-'}）"):
            st.caption(f"分类：{d['category'] or '-'}")
            if st.button("↩️ 回滚（从知识库移除）", key=f"rb-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/rollback", headers=_admin_headers(), timeout=120)
                st.success("已回滚")
                st.rerun()

    if other:
        st.markdown(f"**历史（{len(other)}）**")
        for d in other:
            st.caption(f"📄 {d['filename']} · {d['status']} · {d['created_at'][:16]}")
    st.divider()
    st.caption("💡 上传的文档经审核后并入知识库：客服在回答相关问题时将引用该文档内容（来源可点击）。")


# ---------------- 登录 / 注册视图 ----------------
def _render_login() -> None:
    st.title("👤 用户登录")
    st.caption("登录后享受专属客服：会话与订单绑定您的账号")
    tab1, tab2 = st.tabs(["登录", "注册"])

    with tab1:
        with st.form("login"):
            u = st.text_input("用户名")
            p = st.text_input("密码", type="password")
            if st.form_submit_button("登录", use_container_width=True):
                try:
                    r = httpx.post(f"{API}/api/auth/login", json={"username": u, "password": p}, timeout=15)
                    if r.status_code == 200:
                        st.session_state.user = r.json()
                        st.session_state.view = "user"
                        st.rerun()
                    else:
                        st.error(r.json().get("detail", "登录失败"))
                except Exception as e:  # noqa: BLE001
                    st.error(f"网络错误：{e}")
        st.info("演示账号：**demo1** / **demo2**（密码均为 demo123）—— demo1 可查本人订单 U001")

    with tab2:
        with st.form("register"):
            u2 = st.text_input("新用户名")
            p2 = st.text_input("新密码", type="password", help="至少6位")
            if st.form_submit_button("注册", use_container_width=True):
                try:
                    r = httpx.post(f"{API}/api/auth/register", json={"username": u2, "password": p2}, timeout=15)
                    if r.status_code == 200:
                        st.success("注册成功，请到「登录」页登录")
                    else:
                        st.error(r.json().get("detail", "注册失败"))
                except Exception as e:  # noqa: BLE001
                    st.error(f"网络错误：{e}")


# ---------------- 管理员登录视图 ----------------
def _render_admin_login() -> None:
    st.title("🔐 管理员登录")
    st.caption("仅限知识库管理员（口令见服务端配置 ADMIN_TOKEN）")
    with st.form("admin_login"):
        p = st.text_input("管理员口令", type="password")
        if st.form_submit_button("登录", use_container_width=True):
            try:
                r = httpx.post(f"{API}/api/kb/verify", headers={"X-Admin-Token": p}, timeout=10)
                if r.status_code == 200:
                    st.session_state.admin_token = p
                    st.session_state.admin_ok = True
                    st.session_state.admin_name = "admin"
                    st.session_state.view = "admin"
                    st.rerun()
                else:
                    st.error("口令错误")
            except Exception as e:  # noqa: BLE001
                st.error(f"网络错误：{e}")


def _nav_current() -> str:
    """根据当前 view 反推导航项（刷新后保持选中）。"""
    if st.session_state.view == "portal":
        return "🏠 门户客服"
    if st.session_state.view == "login":
        return "👤 登录 / 注册" if not st.session_state.user else f"👤 {st.session_state.user['username']} 专属客服"
    if st.session_state.view == "user":
        return f"👤 {st.session_state.user['username']} 专属客服" if st.session_state.user else "🏠 门户客服"
    if st.session_state.view == "admin":
        return "🔐 管理员"
    return "🏠 门户客服"


# ---------------- 顶部导航（四视图状态机） ----------------
if "view" not in st.session_state:
    st.session_state.view = "portal"
if "user" not in st.session_state:
    st.session_state.user = None
if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False
if "admin_token" not in st.session_state:
    st.session_state.admin_token = ""

with st.sidebar:
    st.title("💄 悦己 YUEJI")
    st.caption("美妆电商智能客服 Agent")
    nav_options = ["🏠 门户客服"]
    if st.session_state.user:
        nav_options.append(f"👤 {st.session_state.user['username']} 专属客服")
    else:
        nav_options.append("👤 登录 / 注册")
    nav_options.append("🔐 管理员")
    choice = st.radio("导航", nav_options, label_visibility="collapsed", index=nav_options.index(_nav_current()))
    st.divider()

    if st.session_state.user and choice.startswith("👤"):
        if st.button("🚪 退出登录", use_container_width=True):
            httpx.post(f"{API}/api/auth/logout",
                       headers={"X-Auth-Token": st.session_state.user["token"]}, timeout=10)
            st.session_state.user = None
            st.session_state.view = "portal"
            st.rerun()
    if choice.startswith("🔐") and st.session_state.admin_ok:
        if st.button("🚪 退出管理员", use_container_width=True):
            st.session_state.admin_ok = False
            st.session_state.admin_token = ""
            st.session_state.view = "portal"
            st.rerun()
    st.caption("v3.1 · 门户/登录/专属客服/管理员")


# ---------------- 视图分发 ----------------
if choice.startswith("🏠"):
    st.session_state.view = "portal"
    _render_chat("guest", "", title="💬 小悦 · 悦己美妆客服（游客）")
    st.caption("💡 登录后可绑定专属账号与订单；游客会话不关联用户。")

elif choice.startswith("👤 登录"):
    st.session_state.view = "login"
    _render_login()

elif choice.startswith("👤") and st.session_state.user:
    st.session_state.view = "user"
    u = st.session_state.user
    _render_chat(u["user_id"], u["token"], title=f"💬 小悦 · {u['username']} 专属客服")
    st.caption(f"👤 已登录：{u['username']}（{u['user_id']}）· 订单查询仅返回本人订单")

elif choice.startswith("🔐"):
    st.session_state.view = "admin"
    if st.session_state.admin_ok:
        _render_kb_page()
    else:
        _render_admin_login()
