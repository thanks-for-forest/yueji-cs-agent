"""FastAPI 主入口：会话管理、聊天、历史、健康检查。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from src.agents.orchestrator import get_orchestrator
from src.auth import service as auth_service
from src.llm.client import close_llm
from src.session.db import close_db, get_conn, init_db
from src.session.service import get_session_service
from src.tools.order_tools import query_order

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    await init_db()
    await auth_service.seed_demo_users()
    logger.info("DB 就绪: %s", settings.DB_PATH)
    yield
    await close_db()
    await close_llm()


app = FastAPI(title="悦己美妆智能客服 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateSessionReq(BaseModel):
    user_id: str = ""


class ChatReq(BaseModel):
    session_id: str = Field(min_length=4, max_length=64)
    message: str = Field(min_length=1, max_length=1000)
    user_id: str = ""  # 会话归属校验用：非空时须与会话绑定的 user_id 一致


def _check_ownership(session: dict | None, user_id: str) -> None:
    """会话归属校验：会话绑定了用户时，调用方必须声明同一用户。"""
    if session and session.get("user_id") and user_id and session["user_id"] != user_id:
        raise HTTPException(status_code=403, detail=f"无权访问该会话（归属用户 {session['user_id']}）")


# ---------------- 会话 ----------------
@app.post("/api/session")
async def create_session(req: CreateSessionReq | None = None, x_auth_token: str = Header(default="")):
    """创建会话：登录用户自动绑定账号，否则用请求体 user_id（可缺省=游客）。"""
    svc = get_session_service()
    user = await auth_service.get_user_by_token(x_auth_token)
    uid = (user or {}).get("user_id") or (req.user_id if req else "") or "guest"
    session = await svc.create_session(user_id=uid)
    return {"session_id": session["session_id"], "user_id": session.get("user_id", ""), "created_at": session["created_at"]}


@app.get("/api/session/{session_id}/history")
async def session_history(session_id: str, user_id: str = "", x_auth_token: str = Header(default="")):
    svc = get_session_service()
    session = await svc.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    user = await auth_service.get_user_by_token(x_auth_token)
    eff_user = (user or {}).get("user_id") or user_id
    _check_ownership(session, eff_user)
    msgs = await svc.get_messages(session_id)
    return {
        "session_id": session_id,
        "user_id": session.get("user_id", ""),
        "emotion": session.get("emotion", "normal"),
        "status": session.get("status", "active"),
        "meta": session.get("meta", {}),
        "messages": msgs,
    }


@app.get("/api/sessions")
async def list_sessions(limit: int = 20, user_id: str = ""):
    svc = get_session_service()
    sessions = await svc.list_sessions(limit=limit)
    if user_id:
        sessions = [s for s in sessions if s.get("user_id") == user_id]
    return {"sessions": sessions}


# ---------------- 聊天 ----------------
@app.post("/api/chat")
async def chat(req: ChatReq, x_auth_token: str = Header(default="")):
    from src.api.deps import check_rate_limit

    check_rate_limit(req.session_id, settings.RATE_LIMIT_PER_MIN)
    orchestrator = get_orchestrator()
    # 用户身份：登录 token 优先，其次请求体 user_id，兜底游客
    user = await auth_service.get_user_by_token(x_auth_token)
    sid_user = (user or {}).get("user_id") or req.user_id or "guest"
    _check_ownership(await get_session_service().get_session(req.session_id), sid_user)
    try:
        result = await orchestrator.handle(req.session_id, req.message)
        result["user_id"] = sid_user
    except Exception as e:  # noqa: BLE001
        logger.exception("聊天处理异常")
        raise HTTPException(status_code=500, detail=f"服务内部错误: {e}")
    return result


@app.post("/api/chat/stream")
async def chat_stream(req: ChatReq, x_auth_token: str = Header(default="")):
    """SSE 流式对话：data: {"type":"delta","text":"..."} ... data: {"type":"done","result":{...}}"""
    import json as _json

    from fastapi.responses import StreamingResponse

    from src.api.deps import check_rate_limit

    check_rate_limit(req.session_id, settings.RATE_LIMIT_PER_MIN)
    user = await auth_service.get_user_by_token(x_auth_token)
    sid_user = (user or {}).get("user_id") or req.user_id or "guest"
    _check_ownership(await get_session_service().get_session(req.session_id), sid_user)
    orchestrator = get_orchestrator()

    async def gen():
        try:
            async for event in orchestrator.handle_stream(req.session_id, req.message):
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            logger.exception("流式聊天异常")
            yield f"data: {_json.dumps({'type': 'error', 'text': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------- 用户认证（登录/注册/token） ----------------
class RegisterReq(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class LoginReq(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=1, max_length=64)


async def current_user(x_auth_token: str = Header(default="")) -> Optional[dict]:
    """从 X-Auth-Token 解析当前用户；未登录返回 None（游客）。"""
    return await auth_service.get_user_by_token(x_auth_token)


@app.post("/api/auth/register")
async def auth_register(req: RegisterReq):
    try:
        return {"ok": True, **await auth_service.register(req.username, req.password)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login")
async def auth_login(req: LoginReq):
    result = await auth_service.login(req.username, req.password)
    if result is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return result


@app.post("/api/auth/logout")
async def auth_logout(x_auth_token: str = Header(default="")):
    if x_auth_token:
        await auth_service.logout(x_auth_token)
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(user: Optional[dict] = Depends(current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


@app.get("/api/user/sessions")
async def user_sessions(x_auth_token: str = Header(default="")):
    """当前用户的会话列表（含消息数与最近活动）。"""
    user = await auth_service.get_user_by_token(x_auth_token)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT s.session_id, s.created_at, s.updated_at, s.emotion, "
        "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id) AS msg_count "
        "FROM sessions s WHERE s.user_id = ? ORDER BY s.updated_at DESC LIMIT 20",
        (user["user_id"],),
    )
    return {"user_id": user["user_id"], "sessions": [dict(r) for r in await cur.fetchall()]}


@app.get("/api/orders/me")
async def orders_me(x_auth_token: str = Header(default="")):
    """当前用户的订单列表（本人数据隔离）。"""
    user = await auth_service.get_user_by_token(x_auth_token)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT order_id, status, total_amount, created_at, aftersale_status "
        "FROM orders WHERE user_id = ? ORDER BY created_at DESC",
        (user["user_id"],),
    )
    return {"user_id": user["user_id"], "orders": [dict(r) for r in await cur.fetchall()]}


# ---------------- 知识库管理（KB 上传/审核/回滚，需管理员令牌） ----------------
from src.kb import service as kb_service


async def require_admin(x_admin_token: str = Header(default=""),
                        x_admin_name: str = Header(default="admin")):
    """管理员门禁：X-Admin-Token 须等于配置的 ADMIN_TOKEN，操作人取 X-Admin-Name。"""
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="需要管理员权限（X-Admin-Token）")
    return x_admin_name


@app.post("/api/kb/verify")
async def kb_verify(admin: str = Depends(require_admin)):
    """管理员口令验证（前端门禁用）。"""
    return {"ok": True, "admin": admin}


@app.post("/api/kb/upload")
async def kb_upload(file: UploadFile, category: str = "", admin: str = Depends(require_admin)):
    """上传知识库文档（.md/.docx/.pdf），解析后进入待审核。"""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        doc = await kb_service.upload_document(file.filename or "unnamed.md", data, category, created_by=admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return doc


@app.get("/api/kb/docs")
async def kb_docs(admin: str = Depends(require_admin)):
    return {"docs": await kb_service.list_docs()}


@app.get("/api/kb/docs/{doc_id}/chunks")
async def kb_doc_chunks(doc_id: str, admin: str = Depends(require_admin)):
    doc = await kb_service.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"doc_id": doc_id, "chunks": [{"index": i, "text": c["text"]} for i, c in enumerate(doc["chunks"])]}


@app.post("/api/kb/docs/{doc_id}/approve")
async def kb_approve(doc_id: str, admin: str = Depends(require_admin)):
    try:
        return await kb_service.approve_doc(doc_id, operator=admin)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/kb/docs/{doc_id}/reject")
async def kb_reject(doc_id: str, admin: str = Depends(require_admin)):
    return await kb_service.reject_doc(doc_id, operator=admin)


@app.post("/api/kb/docs/{doc_id}/rollback")
async def kb_rollback(doc_id: str, admin: str = Depends(require_admin)):
    try:
        return await kb_service.rollback_doc(doc_id, operator=admin)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/kb/docs/{doc_id}")
async def kb_delete(doc_id: str, admin: str = Depends(require_admin)):
    try:
        return await kb_service.delete_doc(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------- 调试/工具 ----------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------- 来源详情（引用溯源可点击） ----------------
import json as _json2
import re as _re
from urllib.parse import quote as _url_quote

_SRC_ID_RE = _re.compile(r"(P\d{3}|F\d{3}|POL-\d+|KB-\d+)", _re.I)
_chunks_cache: list[dict] | None = None


def _chunks() -> list[dict]:
    global _chunks_cache
    if _chunks_cache is None:
        p = settings.PROCESSED_DATA_DIR / "chunks.json"
        _chunks_cache = _json2.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    return _chunks_cache


def _resolve_sources(label: str) -> list[dict]:
    """把来源标签解析为检索块。

    支持三种形态：① 带编号标签 "烟酰胺焕亮精华液(P011)"；② 纯编号 "P011/F020/POL-1"；
    ③ 纯名称 "烟酰胺焕亮精华液"（按产品名/FAQ问题/政策类型名匹配）。
    """
    chunks = _chunks()
    if not chunks:
        return []
    label = (label or "").strip()
    m = _SRC_ID_RE.search(label)
    if m:
        sid = m.group(1).upper()
        hits = [c for c in chunks if c["meta"].get("source", "").upper() == sid]
        if hits:
            return hits
        hits = [c for c in chunks if sid in c["id"].upper()]
        if hits:
            return hits
    # 按名称匹配（产品名 / FAQ 问题 / 政策类型名）
    name = label.upper()
    hits = [c for c in chunks if name and c["meta"].get("name", "").upper() == name]
    if not hits:
        hits = [c for c in chunks if name and name in c["meta"].get("name", "").upper()]
    return hits


_SOURCE_PAGE_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{title} · 来源详情</title>
<style>
body {{ background:#0b1020; color:#e8ecf5; font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
      margin:0; padding:32px; line-height:1.7; }}
h1 {{ font-size:1.4rem; margin:0 0 6px; }}
.meta {{ color:#8892b0; font-size:.85rem; margin-bottom:20px; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem;
          border:1px solid rgba(100,255,218,.3); color:#64ffda; margin-right:8px; }}
.card {{ background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1); border-radius:12px;
        padding:18px 22px; margin:14px 0; }}
.card h3 {{ margin:0 0 8px; font-size:.95rem; color:#7c9cff; }}
pre {{ background:#0d1526; border:1px solid rgba(255,255,255,.08); border-radius:8px; padding:14px;
      white-space:pre-wrap; word-break:break-all; font-size:.85rem; color:#c8d3f0; }}
a {{ color:#64ffda; }}
.back {{ position:fixed; top:16px; right:20px; font-size:.8rem; opacity:.8; }}
</style></head><body>
<div class="back"><a href="javascript:history.back()">← 返回</a></div>
<h1>📄 {title}</h1>
<div class="meta">{badges} 共 {n} 个检索块</div>
{cards}
<p style="color:#8892b0;font-size:.8rem;margin-top:24px">
  <a href="{raw_url}" target="_blank">查看原始 JSON 数据</a> · 悦己美妆智能客服 · 引用溯源
</p>
</body></html>"""


@app.get("/api/source/{label}")
async def source_detail(label: str):
    """来源详情页：点击〔来源〕在新窗口打开对应知识库原文。"""
    from fastapi.responses import HTMLResponse

    hits = _resolve_sources(label)
    if not hits:
        raise HTTPException(status_code=404, detail=f"未找到来源: {label}")
    first = hits[0]["meta"]
    title = first.get("name", first.get("source", label))
    type_cn = {"product": "产品", "faq": "FAQ", "policy": "政策", "kb": "知识库文档"}.get(first.get("type", ""), first.get("type", ""))
    badges = "".join(
        f'<span class="badge">{b}</span>'
        for b in [type_cn, first.get("source", ""), first.get("category", "")] if b
    )
    cards = []
    for c in hits:
        meta = c["meta"]
        sub = " · ".join(str(meta.get(k, "")) for k in ("category", "product_id", "faq_id", "policy_id", "name") if meta.get(k))
        cards.append(f'<div class="card"><h3>{c["id"]}</h3><p style="color:#8892b0;font-size:.8rem">{sub}</p><pre>{_html_escape(c["text"])}</pre></div>')
    raw_url = f"/api/source/{_url_quote(label)}/raw"
    return HTMLResponse(
        _SOURCE_PAGE_TMPL.format(title=_html_escape(title), badges=badges, n=len(hits), cards="\n".join(cards), raw_url=raw_url)
    )


@app.get("/api/source/{label}/raw")
async def source_raw(label: str):
    """来源原始数据（JSON）。"""
    hits = _resolve_sources(label)
    if not hits:
        raise HTTPException(status_code=404, detail=f"未找到来源: {label}")
    return {"label": label, "records": hits}


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@app.get("/api/order/{order_id}")
async def order_detail(order_id: str, phone_tail: str):
    """调试用：直接查询订单。"""
    result = await query_order(order_id, phone_tail)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=result.get("message", "订单未找到"))
    return result
