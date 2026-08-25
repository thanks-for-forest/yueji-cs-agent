"""FastAPI 主入口：会话管理、聊天、历史、健康检查。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from src.agents.orchestrator import get_orchestrator
from src.llm.client import close_llm
from src.session.db import close_db, init_db
from src.session.service import get_session_service
from src.tools.order_tools import query_order

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    await init_db()
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


# ---------------- 会话 ----------------
@app.post("/api/session")
async def create_session(req: CreateSessionReq | None = None):
    """创建会话。body 可缺省（兼容无 body 的客户端）。"""
    svc = get_session_service()
    session = await svc.create_session(user_id=req.user_id if req else "")
    return {"session_id": session["session_id"], "created_at": session["created_at"]}


@app.get("/api/session/{session_id}/history")
async def session_history(session_id: str):
    svc = get_session_service()
    session = await svc.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = await svc.get_messages(session_id)
    return {
        "session_id": session_id,
        "emotion": session.get("emotion", "normal"),
        "status": session.get("status", "active"),
        "meta": session.get("meta", {}),
        "messages": msgs,
    }


@app.get("/api/sessions")
async def list_sessions(limit: int = 20):
    svc = get_session_service()
    return {"sessions": await svc.list_sessions(limit=limit)}


# ---------------- 聊天 ----------------
@app.post("/api/chat")
async def chat(req: ChatReq):
    from src.api.deps import check_rate_limit

    check_rate_limit(req.session_id, settings.RATE_LIMIT_PER_MIN)
    orchestrator = get_orchestrator()
    try:
        result = await orchestrator.handle(req.session_id, req.message)
    except Exception as e:  # noqa: BLE001
        logger.exception("聊天处理异常")
        raise HTTPException(status_code=500, detail=f"服务内部错误: {e}")
    return result


@app.post("/api/chat/stream")
async def chat_stream(req: ChatReq):
    """SSE 流式对话：data: {"type":"delta","text":"..."} ... data: {"type":"done","result":{...}}"""
    import json as _json

    from fastapi.responses import StreamingResponse

    from src.api.deps import check_rate_limit

    check_rate_limit(req.session_id, settings.RATE_LIMIT_PER_MIN)
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


# ---------------- 调试/工具 ----------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------- 来源详情（引用溯源可点击） ----------------
import json as _json2
import re as _re
from urllib.parse import quote as _url_quote

_SRC_ID_RE = _re.compile(r"(P\d{3}|F\d{3}|POL-\d+)", _re.I)
_chunks_cache: list[dict] | None = None


def _chunks() -> list[dict]:
    global _chunks_cache
    if _chunks_cache is None:
        p = settings.PROCESSED_DATA_DIR / "chunks.json"
        _chunks_cache = _json2.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    return _chunks_cache


def _resolve_sources(label: str) -> list[dict]:
    """把来源标签（如 '烟酰胺焕亮精华液(P011)' 或 'P011'）解析为检索块。"""
    m = _SRC_ID_RE.search(label or "")
    sid = m.group(1).upper() if m else (label or "").strip().upper()
    if not sid:
        return []
    hits = [c for c in _chunks() if c["meta"].get("source", "").upper() == sid]
    if not hits:
        hits = [c for c in _chunks() if sid in c["id"].upper()]
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
    type_cn = {"product": "产品", "faq": "FAQ", "policy": "政策"}.get(first.get("type", ""), first.get("type", ""))
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
