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
async def create_session(req: CreateSessionReq):
    svc = get_session_service()
    session = await svc.create_session(user_id=req.user_id)
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


# ---------------- 调试/工具 ----------------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/order/{order_id}")
async def order_detail(order_id: str, phone_tail: str):
    """调试用：直接查询订单。"""
    result = await query_order(order_id, phone_tail)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=result.get("message", "订单未找到"))
    return result
