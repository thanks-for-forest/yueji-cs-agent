"""「悦己 YUEJI 美妆」智能客服前端 —— 多页面架构（每个角色独立 UI/URL）。

页面：
  /portal  门户（游客 AI 客服，默认）
  /login   登录 / 注册
  /user    用户专属 AI 客服（需登录，守卫自动跳登录页）
  /admin   管理员（口令登录 → 知识库管理）
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

# ================= 会话状态初始化 =================
if "user" not in st.session_state:
    st.session_state.user = None
if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False
if "admin_token" not in st.session_state:
    st.session_state.admin_token = ""


# ================= 公共工具 =================
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


def _render_chat(user_id: str, auth_token: str = "", title: str = "💬 小悦 · 悦己美妆客服") -> None:
    """渲染一个完整客服对话视图（门户游客 / 登录用户共用）。"""
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


# ================= 页面 1：门户（游客 AI 客服 · 营销风） =================
def page_portal() -> None:
    st.sidebar.markdown("### 🌐 门户模式")
    st.sidebar.caption("游客身份 · 会话不关联用户")

    # 营销风 hero 横幅
    st.markdown(
        """
        <div style="border-radius:16px;padding:34px 28px;margin-bottom:10px;
             background:linear-gradient(120deg,#0b1020 0%,#1b2a4a 55%,#3d1f5c 100%);
             border:1px solid rgba(255,255,255,.12);">
          <div style="font-size:2rem;font-weight:700;color:#fff;margin-bottom:6px;">
            💄 悦己 YUEJI · AI 护肤顾问「小悦」
          </div>
          <div style="color:#b8c4e0;font-size:1rem;">
            商品咨询 · 订单查询 · 退换货 · 护肤推荐 · 24 小时在线
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    for col, (icon, t, d) in zip(
        [c1, c2, c3],
        [("🛍️", "智能商品问答", "成分·功效·价格，带来源可溯源"),
         ("💆", "专属护肤方案", "肤质标签匹配 + 搭配建议"),
         ("🔄", "售后一站式", "退换货资格判定 + 工单生成")],
    ):
        with col:
            st.markdown(
                f"""<div style="border:1px solid rgba(255,255,255,.14);border-radius:12px;
                    padding:14px;background:rgba(255,255,255,.05);">
                    <div style="font-size:1.4rem">{icon}</div>
                    <div style="font-weight:600;color:#e8ecf5;margin:4px 0">{t}</div>
                    <div style="font-size:.82rem;color:#8892b0">{d}</div></div>""",
                unsafe_allow_html=True,
            )
    st.divider()
    _render_chat("guest", "", title="💬 和小悦聊聊")
    st.caption("💡 登录后（👤 登录/注册 页）可绑定专属账号与订单；管理员后台在独立应用（端口 8502）。")


# ================= 页面 2：登录 / 注册 =================
def page_auth() -> None:
    st.sidebar.markdown("### 👤 账户")
    if st.session_state.user:
        st.sidebar.caption(f"已登录：{st.session_state.user['username']}（{st.session_state.user['user_id']}）")
        if st.sidebar.button("🚪 退出登录", use_container_width=True):
            httpx.post(f"{API}/api/auth/logout",
                       headers={"X-Auth-Token": st.session_state.user["token"]}, timeout=10)
            st.session_state.user = None
            st.rerun()

    st.title("👤 用户登录 / 注册")
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
                        st.success("登录成功，正在进入专属客服…")
                        st.switch_page(user_page)
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


# ================= 页面 3：用户专属 AI 客服（守卫 + 侧栏会话/订单） =================
def _user_sessions(user: dict) -> list[dict]:
    try:
        r = httpx.get(f"{API}/api/user/sessions", headers={"X-Auth-Token": user["token"]}, timeout=10)
        return r.json().get("sessions", []) if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return []


def _user_orders(user: dict) -> list[dict]:
    try:
        r = httpx.get(f"{API}/api/orders/me", headers={"X-Auth-Token": user["token"]}, timeout=10)
        return r.json().get("orders", []) if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return []


def _load_history(user: dict, session_id: str) -> None:
    """把历史会话加载到当前聊天视图。"""
    try:
        r = httpx.get(f"{API}/api/session/{session_id}/history",
                      headers={"X-Auth-Token": user["token"]}, timeout=10)
        if r.status_code != 200:
            return
        data = r.json()
        msgs = [{"role": m["role"], "content": m["content"]}
                for m in data.get("messages", []) if m["role"] in ("user", "assistant")]
        uid = user["user_id"]
        st.session_state[f"session_id_{uid}"] = session_id
        st.session_state[f"messages_{uid}"] = msgs
        st.session_state[f"meta_{uid}"] = {"emotion": data.get("emotion", "normal"), "intent": "-",
                                           "transferred": False, "ticket": "-"}
    except Exception:  # noqa: BLE001
        pass


def page_user() -> None:
    user = st.session_state.user
    if user is None:
        st.title("🔒 需要登录")
        st.warning("请先登录后再使用专属客服。")
        if st.button("去登录 / 注册"):
            st.switch_page(auth_page)
        return

    with st.sidebar:
        st.markdown("### 👤 专属模式")
        st.caption(f"{user['username']}（{user['user_id']}）· 数据仅本人可见")
        if st.button("🚪 退出登录", use_container_width=True):
            httpx.post(f"{API}/api/auth/logout", headers={"X-Auth-Token": user["token"]}, timeout=10)
            st.session_state.user = None
            st.rerun()
        st.divider()
        # 我的会话
        st.markdown("#### 📋 我的会话")
        sessions = _user_sessions(user)
        if not sessions:
            st.caption("暂无历史会话")
        for sess in sessions[:10]:
            label = f"{sess['session_id'][:10]} · {sess['msg_count']}条 · {sess['updated_at'][:10]}"
            if st.button(label, key=f"ss-{sess['session_id']}", use_container_width=True):
                _load_history(user, sess["session_id"])
                st.rerun()
        st.divider()
        # 我的订单
        st.markdown("#### 📦 我的订单")
        orders = _user_orders(user)
        if not orders:
            st.caption("暂无订单（新注册用户无预置订单）")
        for o in orders[:8]:
            st.markdown(f"**{o['order_id']}** · {o['status']} · ¥{o['total_amount']}")
            st.caption(f"{o['created_at'][:10]}" + (f" · 售后:{o['aftersale_status']}" if o.get('aftersale_status') else ""))
    _render_chat(user["user_id"], user["token"], title=f"💬 小悦 · {user['username']} 专属客服")


# ================= 多页面路由（每个角色独立 UI/URL） =================
portal_page = st.Page(page_portal, title="🏠 门户客服", url_path="portal", default=True)
auth_page = st.Page(page_auth, title="👤 登录/注册", url_path="login")
user_page = st.Page(page_user, title="👤 我的专属客服", url_path="user")

nav = st.navigation([portal_page, auth_page, user_page], position="sidebar")
with st.sidebar:
    st.divider()
    st.caption("🛠️ 管理后台为独立应用：`http://localhost:8502`（详见 docs/部署手册.md）")
nav.run()
