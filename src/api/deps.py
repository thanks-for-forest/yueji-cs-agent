"""API 依赖：会话校验、限流。"""
from __future__ import annotations

import time

from fastapi import HTTPException

from src.session.service import get_session_service

# 简易内存限流：每 session 每分钟 N 次
_limits: dict[str, list[float]] = {}


def check_rate_limit(session_id: str, limit: int = 20) -> None:
    now = time.monotonic()
    bucket = _limits.setdefault(session_id, [])
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    bucket.append(now)


async def require_session(session_id: str) -> dict:
    svc = get_session_service()
    session = await svc.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return session
