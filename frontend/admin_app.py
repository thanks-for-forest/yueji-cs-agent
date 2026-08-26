"""「悦己 YUEJI」管理后台 —— 独立子应用（端口 8502）。

功能（参考 Langchain-Chatchat / Dify / RAGFlow 的 KB 管理）：
- 知识库统计面板（文档数/知识块/分类分布/基础库 vs KB 占比）
- 文档列表筛选（状态/分类/关键词）+ 批量审核/回滚
- 分块预览与编辑（改文本 → 重新向量化 → 已入库自动重建索引）
- 检索命中测试（输入问题看召回块 + 一键问客服）
启动：streamlit run frontend/admin_app.py --server.port 8502
"""
from __future__ import annotations

import json as _json
import re as _re
import sys
from pathlib import Path

import httpx
import streamlit as st

# 保证从任意工作目录启动都能 import 到项目根目录的 config 包
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import settings

API = settings.API_BASE_URL

st.set_page_config(page_title="悦己管理后台", page_icon="🛠️", layout="wide")

# ---------- 主题：登录页米黄色 / 管理页深色（按视图切换） ----------
DARK_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #0b1020; }
[data-testid="stHeader"] { background: transparent; }
h1, h2, h3, p, label, .stCaption { color: #e8ecf5 !important; }
[data-testid="stSidebar"] { background: #0d1526; border-right: 1px solid rgba(255,255,255,.08); }
.stMetric [data-testid="stMetricValue"] { color: #64ffda; }
[data-testid="stMetricLabel"] { color: #8892b0; }
</style>
"""

BEIGE_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #F8F3E7; }
[data-testid="stHeader"] { background: transparent; }
h1, h2, h3 { color: #4A3F33 !important; }
p, label, .stCaption { color: #5B4A3A !important; }
[data-testid="stSidebar"] { background: #F0E8D5; border-right: 1px solid #E3D8C3; }
.stButton button { background: #B08968; color: #fff; border: none; }
.stButton button:hover { background: #9A7355; color: #fff; }
.stTextInput input { background: #FDFAF2; border: 1px solid #E3D8C3; color: #4A3F33; }
[data-testid="stMetricValue"] { color: #B08968; }
</style>
"""


def _apply_theme() -> None:
    css = DARK_CSS if st.session_state.get("admin_ok") else BEIGE_CSS
    st.markdown(css, unsafe_allow_html=True)


_apply_theme()

_SRC_ID_RE = _re.compile(r"(P\d{3}|F\d{3}|POL-\d+|KB-\d+)", _re.I)


def _admin_headers() -> dict:
    return {"X-Admin-Token": st.session_state.get("admin_token", ""),
            "X-Admin-Name": st.session_state.get("admin_name", "admin") or "admin"}


# ================= 管理员登录（米黄色） =================
def admin_login_ui() -> None:
    st.title("🛠️ 悦己管理后台")
    st.caption("知识库管理 · 管理员专属")
    st.divider()
    c1, _, c2 = st.columns([1, 0.2, 1])
    with c1:
        st.markdown(
            """
            <div style="border:1px solid #E3D8C3;border-radius:16px;background:#FDFAF2;
                 padding:26px 22px;box-shadow:0 6px 20px rgba(176,137,104,.18);">
              <div style="font-size:1.3rem;font-weight:700;color:#4A3F33;">🔐 管理员登录</div>
              <div style="color:#8A7A63;font-size:.85rem;margin:4px 0 14px;">悦己美妆管理后台 · 知识库管理</div>
            """,
            unsafe_allow_html=True,
        )
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
        st.markdown("</div>", unsafe_allow_html=True)


# ================= 统计面板 =================
def stats_panel(stats: dict) -> None:
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("文档总数", stats["doc_total"])
    m2.metric("待审核", stats["pending"])
    m3.metric("已入库文档", stats["active"])
    m4.metric("活动知识块", stats["active_chunks"])
    m5.metric("基础库块", stats["base_chunks"])
    cat = stats.get("category_dist", {})
    if cat:
        st.caption("分类分布（知识块）：" + " · ".join(f"{k} {v}" for k, v in sorted(cat.items(), key=lambda x: -x[1])))


# ================= 检索命中测试 =================
def query_test_tool() -> None:
    with st.expander("🔎 检索命中测试（输入问题看召回块）", expanded=False):
        c1, c2 = st.columns([4, 1])
        with c1:
            q = st.text_input("测试问题", placeholder="如：烟酰胺精华适合敏感肌吗", label_visibility="collapsed")
        with c2:
            topk = st.selectbox("TopK", [3, 5, 10], index=1, label_visibility="collapsed")
        if q and st.button("🔎 测试检索", use_container_width=True):
            r = httpx.post(f"{API}/api/kb/query-test",
                           json={"query": q, "top_k": topk}, headers=_admin_headers(), timeout=30)
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                if not hits:
                    st.warning("未召回到任何知识块（会走澄清/拒答流程）")
                for h in hits:
                    tag = "📚KB" if h["is_kb"] else f"{h['type']}"
                    with st.container(border=True):
                        st.markdown(f"**[{h['dense_score']:.2f}] {tag} · {h['name']}** (`{h['source']}`)")
                        st.caption(h["text"])
                if st.button("🤖 问客服（看完整回答）"):
                    with st.chat_message("user"):
                        st.markdown(q)
                    with st.chat_message("assistant"):
                        try:
                            resp = httpx.post(f"{API}/api/chat",
                                              json={"session_id": "admin-test", "message": q}, timeout=120)
                            st.markdown(resp.json().get("reply", "（无回复）"))
                        except Exception as e:  # noqa: BLE001
                            st.error(str(e))
            else:
                st.error(f"检索失败：{r.status_code}")


# ================= 分块编辑器 =================
def _chunk_editor(doc_id: str, chunks: list[dict]) -> None:
    """分块预览 + 编辑（改文本→重新向量化→已入库自动重建索引）。"""
    with st.container(border=True):
        for c in chunks[:8]:
            new_text = st.text_area(f"块 #{c['index']}", value=c["text"], height=80,
                                    key=f"ct-{doc_id}-{c['index']}")
            if st.button("💾 保存该块（重新向量化）", key=f"cs-{doc_id}-{c['index']}",
                         disabled=new_text == c["text"]):
                r = httpx.post(f"{API}/api/kb/docs/{doc_id}/chunk/update",
                               json={"index": c["index"], "text": new_text},
                               headers=_admin_headers(), timeout=60)
                if r.status_code == 200:
                    st.success(f"块 #{c['index']} 已更新")
                    st.rerun()
                else:
                    st.error(r.json().get("detail", "更新失败"))
        if len(chunks) > 8:
            st.caption(f"… 共 {len(chunks)} 块，仅显示前 8 块")


# ================= 文档管理（筛选/批量/分块编辑） =================
def doc_listing(docs: list[dict]) -> None:
    pending = [d for d in docs if d["status"] == "pending"]
    active = [d for d in docs if d["status"] == "active"]
    other = [d for d in docs if d["status"] not in ("pending", "active")]

    if pending:
        st.markdown(f"#### ⏳ 待审核（{len(pending)}）· 可批量")
        sel_p = {d["doc_id"]: st.checkbox(f"📄 {d['filename']} · {d['chunk_count']}块"
                                          f"（上传人：{d.get('created_by') or '-'}）", key=f"bp-{d['doc_id']}")
                 for d in pending}
        c1, c2 = st.columns(2)
        if c1.button("✅ 批量通过", use_container_width=True):
            ids = [k for k, v in sel_p.items() if v]
            if ids:
                httpx.post(f"{API}/api/kb/docs/batch-approve", json={"doc_ids": ids},
                           headers=_admin_headers(), timeout=120)
                st.success(f"批量通过 {len(ids)} 个文档")
                st.rerun()
        if c2.button("❌ 批量拒绝", use_container_width=True):
            ids = [k for k, v in sel_p.items() if v]
            for did in ids:
                httpx.post(f"{API}/api/kb/docs/{did}/reject", headers=_admin_headers(), timeout=10)
            if ids:
                st.rerun()
        st.divider()
        for d in pending:
            with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}"
                             f"（上传人：{d.get('created_by') or '-'}）"):
                try:
                    chunks = httpx.get(f"{API}/api/kb/docs/{d['doc_id']}/chunks",
                                       headers=_admin_headers(), timeout=10).json().get("chunks", [])
                except Exception:  # noqa: BLE001
                    chunks = []
                _chunk_editor(d["doc_id"], chunks)
                c1, c2 = st.columns(2)
                if c1.button("✅ 审核通过", key=f"ap-{d['doc_id']}"):
                    httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/approve", headers=_admin_headers(), timeout=120)
                    st.rerun()
                if c2.button("❌ 拒绝", key=f"rj-{d['doc_id']}"):
                    httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/reject", headers=_admin_headers(), timeout=10)
                    st.rerun()

    if active:
        st.markdown(f"#### ✅ 已入库（{len(active)}）· 可批量回滚")
        sel_a = {d["doc_id"]: st.checkbox(f"📄 {d['filename']} · {d['chunk_count']}块"
                                          f"（审核人：{d.get('approved_by') or '-'}）", key=f"ba-{d['doc_id']}")
                 for d in active}
        if st.button("↩️ 批量回滚", use_container_width=True):
            ids = [k for k, v in sel_a.items() if v]
            if ids:
                httpx.post(f"{API}/api/kb/docs/batch-rollback", json={"doc_ids": ids},
                           headers=_admin_headers(), timeout=120)
                st.success(f"批量回滚 {len(ids)} 个文档")
                st.rerun()
        st.divider()
        for d in active:
            with st.expander(f"📄 {d['filename']} · {d['chunk_count']} 块 · {d['created_at'][:16]}"
                             f"（审核人：{d.get('approved_by') or '-'}）"):
                st.caption(f"分类：{d['category'] or '-'}")
                try:
                    chunks = httpx.get(f"{API}/api/kb/docs/{d['doc_id']}/chunks",
                                       headers=_admin_headers(), timeout=10).json().get("chunks", [])
                except Exception:  # noqa: BLE001
                    chunks = []
                _chunk_editor(d["doc_id"], chunks)
                if st.button("↩️ 回滚（从知识库移除）", key=f"rb-{d['doc_id']}"):
                    httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/rollback", headers=_admin_headers(), timeout=120)
                    st.rerun()

    if other:
        st.markdown(f"#### 🗂️ 历史（{len(other)}）")
        for d in other:
            st.caption(f"📄 {d['filename']} · {d['status']} · {d['created_at'][:16]}")


# ================= 主页面 =================
def kb_page() -> None:
    st.title("🛠️ 悦己管理后台 · 知识库")
    st.caption("上传 .md / .docx / .pdf → 分块预览/编辑 → 审核入库 → 回滚（操作留痕）｜ 支持检索命中测试")

    try:
        stats = httpx.get(f"{API}/api/kb/stats", headers=_admin_headers(), timeout=10).json()
        stats_panel(stats)
    except Exception:  # noqa: BLE001
        st.error("无法连接后端服务（或管理员令牌已失效）")
        return

    query_test_tool()

    st.divider()
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
    f1, f2, f3 = st.columns([1, 1, 1])
    with f1:
        f_status = st.selectbox("状态筛选", ["全部", "待审核", "已入库", "历史"], index=0)
    with f2:
        f_cat = st.text_input("分类筛选", value="", placeholder="如 活动")
    with f3:
        f_kw = st.text_input("关键词（文件名）", value="", placeholder="搜索文档名")
    status_map = {"待审核": "pending", "已入库": "active", "历史": "other"}
    params = {}
    if f_status != "全部":
        params["status"] = status_map[f_status]
    if f_cat:
        params["category"] = f_cat
    if f_kw:
        params["keyword"] = f_kw

    try:
        docs = httpx.get(f"{API}/api/kb/docs", params=params, headers=_admin_headers(), timeout=10).json().get("docs", [])
    except Exception:  # noqa: BLE001
        st.error("无法连接后端服务（或管理员令牌已失效）")
        return
    st.caption(f"共 {len(docs)} 个文档（按当前筛选）")
    doc_listing(docs)


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
