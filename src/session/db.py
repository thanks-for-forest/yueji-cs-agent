"""SQLite 数据访问（aiosqlite）：建表、连接管理。

表：orders（模拟订单）、sessions / messages（会话）、tickets（售后工单）。
"""
from __future__ import annotations

import asyncio
from typing import Optional

import aiosqlite

from config import settings

_conn: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  order_id   TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  phone      TEXT NOT NULL,
  status     TEXT NOT NULL,
  total_amount REAL NOT NULL,
  created_at TEXT NOT NULL,
  items      TEXT NOT NULL,
  tracking   TEXT,
  aftersale_status TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(phone);

CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  user_id    TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status     TEXT DEFAULT 'active',
  emotion    TEXT DEFAULT 'normal',
  summary    TEXT,
  meta       TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  session_id TEXT,
  order_id TEXT,
  user_id TEXT,
  type TEXT NOT NULL,
  reason TEXT,
  description TEXT,
  evidence TEXT,
  condition_check TEXT,
  status TEXT DEFAULT '待审核',
  emotion TEXT,
  summary TEXT,
  created_at TEXT NOT NULL
);
"""


async def get_conn() -> aiosqlite.Connection:
    global _conn
    settings.ensure_dirs()
    if _conn is None:
        _conn = await aiosqlite.connect(settings.DB_PATH)
        _conn.row_factory = aiosqlite.Row
        async with _lock:
            await _conn.executescript(SCHEMA)
            await _conn.commit()
    return _conn


async def init_db() -> None:
    await get_conn()


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
