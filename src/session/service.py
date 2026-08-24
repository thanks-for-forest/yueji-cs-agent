"""会话服务：会话/消息持久化、记忆组装、情绪与元数据维护。"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from config import settings
from src.memory.buffer import trim_to_window
from src.session.db import get_conn

logger = logging.getLogger(__name__)

DEFAULT_META: dict = {
    "intent": "",
    "slots": {},          # 槽位状态机持久化（订单/售后）
    "last_product": "",   # 最近讨论的产品（澄清策略用）
    "emotion_history": [],  # 最近情绪序列
    "step": "",           # 多轮流程步骤（售后等）
    "ticket": "",         # 最近工单号
}


def _load_meta(raw: str | None) -> dict:
    if not raw:
        return dict(DEFAULT_META)
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        meta = {}
    merged = dict(DEFAULT_META)
    merged.update(meta)
    return merged


class SessionService:
    # ---------------- 会话生命周期 ----------------
    async def create_session(self, user_id: str = "", session_id: str = "") -> dict:
        conn = await get_conn()
        if not session_id:
            session_id = uuid.uuid4().hex[:16]
        now = datetime.now().isoformat(timespec="seconds")
        await conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, user_id, created_at, updated_at, status, emotion, meta) VALUES (?,?,?,?,?,?,?)",
            (session_id, user_id, now, now, "active", "normal", json.dumps(DEFAULT_META, ensure_ascii=False)),
        )
        await conn.commit()
        return await self.get_session(session_id)

    async def get_session(self, session_id: str) -> Optional[dict]:
        conn = await get_conn()
        cur = await conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["meta"] = _load_meta(d.get("meta"))
        return d

    async def touch(self, session_id: str) -> None:
        conn = await get_conn()
        await conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (datetime.now().isoformat(timespec="seconds"), session_id),
        )
        await conn.commit()

    async def list_sessions(self, limit: int = 20) -> list[dict]:
        conn = await get_conn()
        cur = await conn.execute("SELECT session_id, user_id, created_at, status, emotion FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ---------------- 消息 ----------------
    async def save_message(self, session_id: str, role: str, content: str) -> None:
        conn = await get_conn()
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, ts) VALUES (?,?,?,?)",
            (session_id, role, content, datetime.now().isoformat(timespec="seconds")),
        )
        await conn.commit()

    async def get_messages(self, session_id: str, limit: Optional[int] = None) -> list[dict]:
        conn = await get_conn()
        cur = await conn.execute(
            "SELECT role, content, ts FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
        )
        rows = await cur.fetchall()
        msgs = [dict(r) for r in rows]
        if limit:
            msgs = msgs[-limit:]
        return msgs

    async def count_messages(self, session_id: str) -> int:
        conn = await get_conn()
        cur = await conn.execute("SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (session_id,))
        row = await cur.fetchone()
        return row["c"]

    # ---------------- 记忆组装 ----------------
    async def build_memory_messages(self, session: dict) -> list[dict]:
        """返回 LLM 可用的历史消息（摘要 + 最近窗口），不含本轮用户消息。"""
        session_id = session["session_id"]
        msgs = await self.get_messages(session_id)
        out: list[dict] = []
        summary = session.get("summary") or ""
        if summary:
            out.append({"role": "system", "content": f"【更早的对话摘要】{summary}"})
        # 去掉已进入摘要的部分（摘要生成后 messages 会被清理到窗口内，见 maybe_summarize）
        trimmed = trim_to_window(msgs)
        out.extend({"role": m["role"], "content": m["content"]} for m in trimmed)
        return out

    async def maybe_summarize(self, session: dict) -> None:
        """消息过多时压缩早期对话为摘要，并删除已压缩的消息。"""
        session_id = session["session_id"]
        total = await self.count_messages(session_id)
        if total <= settings.SUMMARY_THRESHOLD * 2:
            return
        msgs = await self.get_messages(session_id)
        to_sum = [{"role": m["role"], "content": m["content"]} for m in msgs[:- settings.MEMORY_WINDOW * 2]]
        from src.memory.buffer import summarize

        new_summary = await summarize(to_sum)
        old = session.get("summary") or ""
        combined = f"{old} | {new_summary}" if old and new_summary else (old or new_summary)
        conn = await get_conn()
        # 删除已压缩消息，只保留最近窗口
        keep_ids = [m for m in msgs[-settings.MEMORY_WINDOW * 2:]]
        await conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for m in keep_ids:
            await conn.execute(
                "INSERT INTO messages (session_id, role, content, ts) VALUES (?,?,?,?)",
                (session_id, m["role"], m["content"], m["ts"]),
            )
        await conn.execute("UPDATE sessions SET summary = ? WHERE session_id = ?", (combined, session_id))
        await conn.commit()
        logger.info("会话 %s 已压缩，摘要长度 %d", session_id, len(combined))

    # ---------------- 元数据 / 情绪 ----------------
    async def update_meta(self, session_id: str, **fields: Any) -> dict:
        conn = await get_conn()
        cur = await conn.execute("SELECT meta FROM sessions WHERE session_id = ?", (session_id,))
        row = await cur.fetchone()
        meta = _load_meta(dict(row)["meta"]) if row else dict(DEFAULT_META)
        for k, v in fields.items():
            meta[k] = v
        await conn.execute("UPDATE sessions SET meta = ?, updated_at = ? WHERE session_id = ?",
                           (json.dumps(meta, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), session_id))
        await conn.commit()
        return meta

    async def push_emotion(self, session_id: str, emotion: str) -> bool:
        """记录情绪并返回是否需要转人工。"""
        conn = await get_conn()
        cur = await conn.execute("SELECT meta, emotion FROM sessions WHERE session_id = ?", (session_id,))
        row = await cur.fetchone()
        if row is None:
            return False
        meta = _load_meta(dict(row)["meta"])
        hist = meta.get("emotion_history", [])[-5:]
        hist.append(emotion)
        meta["emotion_history"] = hist
        await conn.execute("UPDATE sessions SET meta = ?, emotion = ? WHERE session_id = ?",
                           (json.dumps(meta, ensure_ascii=False), emotion, session_id))
        await conn.commit()
        from src.emotion.detector import needs_transfer

        return needs_transfer(emotion, hist)


# 单例
_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    global _service
    if _service is None:
        _service = SessionService()
    return _service
