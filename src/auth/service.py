"""用户认证服务：注册/登录/登出/token 管理（演示级，pbkdf2 哈希 + 24h token）。

- 演示账号（首次启动播种，密码 demo123）：demo1 → U001（有订单），demo2 → U005（有订单）
- 新注册用户获得独立 user_id（无预置订单，订单查询为空属正常行为）
- token 存 auth_tokens 表，接口通过 X-Auth-Token 头解析当前用户
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from src.session.db import get_conn

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
"""

TOKEN_TTL_HOURS = 24
DEMO_PASSWORD = "demo123"


async def _ensure_auth_tables() -> None:
    conn = await get_conn()
    await conn.executescript(AUTH_SCHEMA)
    await conn.commit()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def _new_salt() -> str:
    return secrets.token_bytes(16).hex()


async def seed_demo_users() -> None:
    """首次启动播种演示账号（demo1→U001 / demo2→U005，密码 demo123）。"""
    await _ensure_auth_tables()
    conn = await get_conn()
    cur = await conn.execute("SELECT COUNT(*) c FROM users")
    if (await cur.fetchone())["c"] > 0:
        return
    now = datetime.now().isoformat(timespec="seconds")
    for username, uid in (("demo1", "U001"), ("demo2", "U005")):
        salt = _new_salt()
        await conn.execute(
            "INSERT INTO users (user_id, username, password_hash, salt, created_at) VALUES (?,?,?,?,?)",
            (uid, username, _hash_password(DEMO_PASSWORD, salt), salt, now),
        )
    await conn.commit()


async def register(username: str, password: str) -> dict:
    """注册新用户，返回用户信息。用户名冲突抛 ValueError。"""
    await _ensure_auth_tables()
    username = username.strip()
    if len(username) < 2 or len(password) < 6:
        raise ValueError("用户名至少2位、密码至少6位")
    user_id = f"U{datetime.now():%Y%m%d%H%M%S}"
    salt = _new_salt()
    now = datetime.now().isoformat(timespec="seconds")
    conn = await get_conn()
    try:
        await conn.execute(
            "INSERT INTO users (user_id, username, password_hash, salt, created_at) VALUES (?,?,?,?,?)",
            (user_id, username, _hash_password(password, salt), salt, now),
        )
        await conn.commit()
    except Exception:  # noqa: BLE001  (UNIQUE 冲突)
        raise ValueError("用户名已存在")
    return {"user_id": user_id, "username": username}


async def login(username: str, password: str) -> Optional[dict]:
    """登录成功返回 {token, user_id, username}；失败返回 None。"""
    await _ensure_auth_tables()
    conn = await get_conn()
    cur = await conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
    row = await cur.fetchone()
    if row is None:
        return None
    user = dict(row)
    if not hmac.compare_digest(user["password_hash"], _hash_password(password, user["salt"])):
        return None
    token = uuid.uuid4().hex
    now = datetime.now()
    await conn.execute(
        "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user["user_id"], now.isoformat(timespec="seconds"),
         (now + timedelta(hours=TOKEN_TTL_HOURS)).isoformat(timespec="seconds")),
    )
    await conn.commit()
    return {"token": token, "user_id": user["user_id"], "username": user["username"]}


async def get_user_by_token(token: str) -> Optional[dict]:
    """按 token 解析用户；无效/过期返回 None。"""
    if not token:
        return None
    await _ensure_auth_tables()
    conn = await get_conn()
    cur = await conn.execute("SELECT * FROM auth_tokens WHERE token = ?", (token,))
    row = await cur.fetchone()
    if row is None:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return None
    except ValueError:
        return None
    cur = await conn.execute("SELECT user_id, username FROM users WHERE user_id = ?", (row["user_id"],))
    u = await cur.fetchone()
    return dict(u) if u else None


async def logout(token: str) -> None:
    await _ensure_auth_tables()
    conn = await get_conn()
    await conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    await conn.commit()
