"""「悦己 YUEJI」管理后台 —— 独立子应用（端口 8502）。

独立于客服门户的管理员界面：深色管理风，口令登录 → 知识库管理（上传/审核/回滚 + 审计）。
启动：streamlit run frontend/admin_app.py --server.port 8502
"""
from __future__ import annotations

import json as _json
import re as _re

import httpx
import streamlit as st

from config import settings

API = settings.API_BASE_URL
ADMIN_PORT = 8502

st.set_page_config(page_title="悦己管理后台", page_icon="🛠️", layout="wide")

# ---------- 深色管理风主题（注入 CSS） ----------
st.markdown(
    """
<style>
[data-testid="stAppViewContainer"] { background: #0b1020; }
[data-testid="stHeader"] { background: transparent; }
h1, h2, h3, p, label, .stCaption { color: #e8ecf5 !important; }
[data-testid="stSidebar"] { background: #0d1526; border-right: 1px solid rgba(255,255,255,.08); }
.stMetric [data-testid="stMetricValue"] { color: #64ffda; }
[data-testid="stMetricLabel"] { color: #8892b0; }
</style>
""",
    unsafe_allow_html=True,
)

_SRC_ID_RE = _re.compile(r"(P\d{3}|F\d{3}|POL-\d+|KB-\d+)", _re.I)


def _admin_headers() -> dict:
    return {"X-Admin-Token": st.session_state.get("admin_token", ""),
            "X-Admin-Name": st.session_state.get("admin_name", "admin") or "admin"}


# ================= 管理员登录 =================
def admin_login_ui() -> None:
    st.title("🛠️ 悦己管理后台")
    st.caption("知识库管理 · 管理员专属")
    st.divider()
    c1, _, c2 = st.columns([1, 0.2, 1])
    with c1:
        st.markdown("#### 🔐 管理员登录")
        with st.form("admin_login"):
            p = st.text_input("管理员口令", type="password")
            if st.form_submit_button("登录", use_container_width=True):
                try:
                    r = httpx.post(f"{API}/api/kb/verify", headers={"X-Admin-Token": p}, timeout=10)
                    if r.status_code == 200:
                        st.session_state.admin_token = p
                        st.session_state.admin_ok = True
                        st.session_state.admin_name = "admin"
                        st.rerun()
                    else:
                        st.error("口令错误")
                except Exception as e:  # noqa: BLE001
                    st.error(f"网络错误：{e}")


# ================= 知识库管理 =================
def kb_page() -> None:
    st.title("🛠️ 悦己管理后台 · 知识库")
    st.caption("上传 .md / .docx / .pdf → 分块预览 → 审核入库 → 回滚（操作留痕）")

    try:
        docs = httpx.get(f"{API}/api/kb/docs", headers=_admin_headers(), timeout=10).json().get("docs", [])
    except Exception:  # noqa: BLE001
        st.error("无法连接后端服务（或管理员令牌已失效）")
        return

    pending = [d for d in docs if d["status"] == "pending"]
    active = [d for d in docs if d["status"] == "active"]
    other = [d for d in docs if d["status"] not in ("pending", "active")]
    total_chunks = sum(d["chunk_count"] for d in active)

    # 指标行（管理风）
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("待审核文档", len(pending))
    m2.metric("已入库文档", len(active))
    m3.metric("活动知识块", total_chunks)
    m4.metric("历史记录", len(other))
    st.divider()

    # 上传区
    with st.container(border=True):
        st.markdown("**⬆️ 上传新文档**")
        c1, c2 = st.columns([3, 1])
        with c1:
            up = st.file_uploader("选择文件", type=["md", "txt", "docx", "pdf"], label_visibility="collapsed")
        with c2:
            cat = st.text_input("分类", value="", placeholder="如 活动/新品/公告")
        if up is not None and st.button("上传并解析", use_container_width=True):
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
                st.success(f"✅ 已上传「{d['filename']}」，解析出 {d['chunk_count']} 个分块")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"上传失败：{e}")

    st.divider()
    st.markdown(f"#### ⏳ 待审核（{len(pending)}）")
    if not pending:
        st.caption("暂无待审核文档")
    for d in pending:
        with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}（上传人：{d.get('created_by') or '-'}）"):
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
                st.success("已入库")
                st.rerun()
            if c2.button("❌ 拒绝", key=f"rj-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/reject", headers=_admin_headers(), timeout=10)
                st.rerun()

    st.markdown(f"#### ✅ 已入库（{len(active)}）")
    if not active:
        st.caption("暂无已入库文档")
    for d in active:
        with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}（审核人：{d.get('approved_by') or '-'}）"):
            st.caption(f"分类：{d['category'] or '-'}")
            if st.button("↩️ 回滚（从知识库移除）", key=f"rb-{d['doc_id']}"):
                httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/rollback", headers=_admin_headers(), timeout=120)
                st.success("已回滚")
                st.rerun()

    if other:
        st.markdown(f"#### 🗂️ 历史（{len(other)}）")
        for d in other:
            st.caption(f"📄 {d['filename']} · {d['status']} · {d['created_at'][:16]}")


# ================= 入口 =================
with st.sidebar:
    st.title("🛠️ 悦己管理后台")
    st.caption("独立管理端 · 端口 8502")
    st.divider()
    if st.session_state.get("admin_ok"):
        if st.button("🚪 退出管理员", use_container_width=True):
            st.session_state.admin_ok = False
            st.session_state.admin_token = ""
            st.rerun()
    st.caption("🔗 客服门户：http://localhost:8501")

if st.session_state.get("admin_ok"):
    kb_page()
else:
    admin_login_ui()
