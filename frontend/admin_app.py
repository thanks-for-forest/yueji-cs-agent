"""「悦己 YUEJI」管理后台 —— 独立子应用（端口 8502）。

功能（参考 Langchain-Chatchat / Dify / RAGFlow 的 KB 管理）：
- 知识库统计面板（文档数/知识块/分类分布/基础库 vs KB 占比）
- 索引健康检查 + 强制重建 + 一键导出（json / md）
- 分块策略可视化配置（chunk_size / overlap，上传与重新分块共用）
- 多文件批量上传（.md/.txt/.docx/.pdf/.csv/.xlsx/.html）+ 分类管理
- 文档列表筛选（状态/分类/关键词）+ 批量审核/回滚/删除
- 分块预览与编辑（改文本 → 重新向量化 → 已入库自动重建索引）+ 按策略重新分块
- 检索命中测试（Dense/RRF/BM25/Dense优先 模式对照 + 检索历史命中率统计 + 一键问客服）
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


# ================= 分块策略配置（借鉴 Dify 分段设置） =================
def chunk_strategy_ui() -> tuple[int, int]:
    """分块策略调节面板：chunk_size / overlap，存 session_state 供上传与重分块复用。"""
    with st.expander("🧩 分块策略（Dify 式分段设置）", expanded=False):
        st.caption("字符窗口大小与重叠长度。窗口内优先在段落/句号处切断；重叠用于跨块上下文衔接。"
                   "调整后影响【新上传】与【重新分块】。")
        cs = st.slider("分块大小 (chunk_size)", 100, 1000, st.session_state.get("kb_cs", 400), 50)
        ov = st.slider("重叠长度 (overlap)", 0, 200, st.session_state.get("kb_ov", 60), 10)
        if ov >= cs:
            st.warning(f"重叠({ov})不能大于等于分块大小({cs})，已自动收敛为 {max(cs // 2, 0)}")
            ov = max(cs // 2, 0)
        st.session_state.kb_cs = cs
        st.session_state.kb_ov = ov
        return cs, ov


# ================= 索引健康 + 导出 =================
def index_status_ui() -> None:
    """索引健康卡片：一致性检查 + 强制重建 + 一键导出。"""
    try:
        sts = httpx.get(f"{API}/api/kb/index-status", headers=_admin_headers(), timeout=10).json()
    except Exception:  # noqa: BLE001
        st.error("索引状态获取失败（后端不可用？）")
        return
    healthy = sts.get("healthy")
    icon = "✅" if healthy else "⚠️"
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
        c1.metric("索引健康", f"{icon} {'正常' if healthy else '异常'}")
        c2.metric("总知识块", sts["counts"]["chunks_json"])
        c3.metric("基础库块", sts["counts"]["base_vectors"])
        c4.caption(f"最后重建：{sts.get('last_rebuild_at') or '-'}")
        if not healthy:
            for i in sts.get("issues", []):
                st.error(i)
        cc1, cc2, cc3 = st.columns([1, 1, 2])
        if cc1.button("♻️ 强制重建索引", use_container_width=True):
            try:
                r = httpx.post(f"{API}/api/kb/rebuild", headers=_admin_headers(), timeout=120)
                st.success(f"重建完成：{r.json().get('healthy') and '健康' or r.json().get('issues')}")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"重建失败：{e}")
        if cc2.button("📤 导出 JSON", use_container_width=True):
            try:
                r = httpx.get(f"{API}/api/kb/export", params={"fmt": "json"}, headers=_admin_headers(), timeout=30)
                data = r.json()
                st.download_button("⬇️ 下载 JSON 导出", data=data["content"].encode("utf-8"),
                                   file_name=data["filename"], mime="application/json",
                                   key="dl-json", use_container_width=True)
            except Exception as e:  # noqa: BLE001
                st.error(f"导出失败：{e}")
        if cc3.button("📄 导出 Markdown", use_container_width=True):
            try:
                r = httpx.get(f"{API}/api/kb/export", params={"fmt": "md"}, headers=_admin_headers(), timeout=30)
                data = r.json()
                st.download_button("⬇️ 下载 Markdown 导出", data=data["content"].encode("utf-8"),
                                   file_name=data["filename"], mime="text/markdown",
                                   key="dl-md", use_container_width=True)
            except Exception as e:  # noqa: BLE001
                st.error(f"导出失败：{e}")


# ================= 检索命中测试 =================
def query_test_tool() -> None:
    with st.expander("🔎 检索命中测试（输入问题看召回块，支持模式对照）", expanded=False):
        c1, c2, c3 = st.columns([4, 1, 1.4])
        with c1:
            q = st.text_input("测试问题", placeholder="如：烟酰胺精华适合敏感肌吗", label_visibility="collapsed")
        with c2:
            topk = st.selectbox("TopK", [3, 5, 10], index=1, label_visibility="collapsed")
        with c3:
            mode = st.selectbox("检索模式", ["dense_first", "rrf", "dense", "bm25"], index=0,
                                format_func=lambda m: {"dense_first": "Dense优先（主链路）",
                                                       "rrf": "RRF 融合", "dense": "纯向量",
                                                       "bm25": "纯关键词"}[m],
                                label_visibility="collapsed")
        st.caption("阈值参考：Dense 余弦门槛 0.55（相关 ≥0.71，无关 ≤0.50）；RRF 融合分门槛 0.02。"
                   "低于门槛的查询在客服侧会走澄清/拒答流程。")
        if q and st.button("🔎 测试检索", use_container_width=True):
            r = httpx.post(f"{API}/api/kb/query-test",
                           json={"query": q, "top_k": topk, "mode": mode},
                           headers=_admin_headers(), timeout=30)
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                if not hits:
                    st.warning("未召回到任何知识块（会走澄清/拒答流程）")
                for h in hits:
                    tag = "📚KB" if h["is_kb"] else f"{h['type']}"
                    score = (h["dense_score"] if mode in ("dense_first", "dense", "rrf") and h["dense_score"]
                             else h["bm25_score"])
                    with st.container(border=True):
                        st.markdown(f"**[{score:.3f}] {tag} · {h['name']}** (`{h['source']}`) "
                                    f"dense={h['dense_score']} bm25={h['bm25_score']} fusion={h['fusion_score']}")
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
    query_stats_tool()


def query_stats_tool() -> None:
    """检索历史命中率统计（借鉴 Dify 检索日志）。"""
    try:
        s = httpx.get(f"{API}/api/kb/query-stats", params={"limit": 15},
                      headers=_admin_headers(), timeout=10).json()
    except Exception:  # noqa: BLE001
        return
    if not s.get("total"):
        return
    with st.expander(f"📈 检索历史统计（共 {s['total']} 次测试 · 平均命中率 {s['avg_hit_rate']*100:.0f}%）", expanded=False):
        t1, t2 = st.columns([1, 1])
        with t1:
            st.markdown("**高频测试问题**")
            for q in s.get("top_queries", []):
                st.caption(f"「{q['query'][:28]}」×{q['times']} 次 · 平均命中 {q['avg_hits']} 块")
        with t2:
            st.markdown("**最近记录**")
            for r in s.get("recent", [])[:8]:
                st.caption(f"[{r['mode']}] {r['query'][:24]} → {r['hit_count']}块"
                           f" · top={r['top_score']:.2f} · {r['created_at'][11:19]}")


# ================= 分块编辑器 =================
def _chunk_editor(doc_id: str, chunks: list[dict], status: str = "pending") -> None:
    """分块预览 + 编辑（改文本→重新向量化→已入库自动重建索引）+ 按策略重新分块。"""
    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 1, 1.5])
        show_all = c1.toggle("显示全部分块", value=False,
                             help="默认只预览前 8 块，打开后全部可编辑")
        c2.caption(f"共 {len(chunks)} 块")
        cs = st.session_state.get("kb_cs", 400)
        ov = st.session_state.get("kb_ov", 60)
        if c3.button(f"🔄 按当前策略重新分块（{cs}/{ov}）", use_container_width=True,
                     disabled=len(chunks) == 0):
            r = httpx.post(f"{API}/api/kb/docs/{doc_id}/rechunk",
                           json={"chunk_size": cs, "overlap": ov},
                           headers=_admin_headers(), timeout=120)
            if r.status_code == 200:
                st.success(f"已按 {cs}/{ov} 重新分块为 {r.json()['chunk_count']} 块")
                st.rerun()
            else:
                st.error(r.json().get("detail", "重新分块失败"))
        limit = len(chunks) if show_all else min(len(chunks), 8)
        for c in chunks[:limit]:
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
        if not show_all and len(chunks) > 8:
            st.caption(f"… 共 {len(chunks)} 块，勾选「显示全部分块」查看与编辑其余块")


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
                _chunk_editor(d["doc_id"], chunks, status="pending")
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
                _chunk_editor(d["doc_id"], chunks, status="active")
                if st.button("↩️ 回滚（从知识库移除）", key=f"rb-{d['doc_id']}"):
                    httpx.post(f"{API}/api/kb/docs/{d['doc_id']}/rollback", headers=_admin_headers(), timeout=120)
                    st.rerun()

    if other:
        st.markdown(f"#### 🗂️ 历史（{len(other)}）· 可批量删除")
        sel_o = {d["doc_id"]: st.checkbox(f"📄 {d['filename']} · {d['status']} · {d['created_at'][:16]}",
                                          key=f"bd-{d['doc_id']}") for d in other}
        if st.button("🗑️ 批量删除（不可恢复）", use_container_width=True):
            ids = [k for k, v in sel_o.items() if v]
            if ids:
                r = httpx.post(f"{API}/api/kb/docs/batch-delete", json={"doc_ids": ids},
                               headers=_admin_headers(), timeout=30)
                st.success(f"已删除 {len(r.json().get('deleted', []))} 个文档")
                st.rerun()
        for d in other:
            st.caption(f"📄 {d['filename']} · {d['status']} · {d['created_at'][:16]}")


# ================= 主页面 =================
def kb_page() -> None:
    st.title("🛠️ 悦己管理后台 · 知识库")
    st.caption("上传 .md/.txt/.docx/.pdf/.csv/.xlsx/.html → 分块预览/编辑 → 审核入库 → 回滚（操作留痕）"
               "｜ 支持多模式检索命中测试与一键导出")

    try:
        stats = httpx.get(f"{API}/api/kb/stats", headers=_admin_headers(), timeout=10).json()
        stats_panel(stats)
    except Exception:  # noqa: BLE001
        st.error("无法连接后端服务（或管理员令牌已失效）")
        return

    index_status_ui()
    query_test_tool()

    st.divider()
    cs, ov = chunk_strategy_ui()

    st.divider()
    with st.container(border=True):
        st.markdown(f"**⬆️ 批量上传新文档**（当前分块策略 {cs}/{ov}，可多选）")
        c1, c2 = st.columns([3, 1])
        with c1:
            ups = st.file_uploader("选择文件（可多选）", type=["md", "txt", "docx", "pdf", "csv", "xlsx", "html"],
                                   accept_multiple_files=True, label_visibility="collapsed")
        with c2:
            try:
                cats = httpx.get(f"{API}/api/kb/categories", headers=_admin_headers(), timeout=10).json()["categories"]
            except Exception:  # noqa: BLE001
                cats = ["活动", "新品", "公告", "常见问题", "售后"]
            cat = st.selectbox("分类", [""] + cats, format_func=lambda c: c or "（不分类）", label_visibility="collapsed")
        if ups and st.button(f"⬆️ 上传并解析（{len(ups)} 个文件）", use_container_width=True):
            try:
                files = [("files", (u.name, u.getvalue(), u.type)) for u in ups]
                r = httpx.post(
                    f"{API}/api/kb/upload-batch",
                    files=files,
                    data={"category": cat, "chunk_size": cs, "overlap": ov},
                    headers=_admin_headers(),
                    timeout=300,
                )
                r.raise_for_status()
                res = r.json()
                if res.get("ok"):
                    st.success(f"✅ 上传成功 {res['ok']} 个文档（共 "
                               f"{sum(x['chunk_count'] for x in res['results'])} 分块，策略 {res['chunk_size']}/{res['overlap']}）")
                for e in res.get("errors", []):
                    st.error(f"❌ {e['filename']}：{e['error']}")
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
