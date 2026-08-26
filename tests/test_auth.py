"""用户认证与账号绑定测试。"""
import asyncio

from src.auth import service as auth
from src.session.db import close_db, init_db


def _run(coro):
    return asyncio.run(coro)


def test_seed_demo_users():
    async def t():
        await init_db()
        await auth.seed_demo_users()
        r = await auth.login("demo1", "demo123")
        assert r is not None and r["user_id"] == "U001"

    _run(t())


def test_login_wrong_password():
    async def t():
        assert await auth.login("demo1", "wrongpass") is None

    _run(t())


def test_register_and_duplicate():
    async def t():
        r = await auth.register("test_user_001", "secret123")
        assert r["user_id"].startswith("U")
        try:
            await auth.register("test_user_001", "secret123")
            assert False, "应抛 ValueError"
        except ValueError:
            pass

    _run(t())


def test_token_roundtrip_and_expiry_logic():
    async def t():
        r = await auth.login("demo1", "demo123")
        token = r["token"]
        user = await auth.get_user_by_token(token)
        assert user and user["user_id"] == "U001"
        # 无效 token
        assert await auth.get_user_by_token("no-such-token") is None
        # 登出后失效
        await auth.logout(token)
        assert await auth.get_user_by_token(token) is None

    _run(t())


def test_cleanup_test_users():
    """清理测试注册的账号，保持仓库演示状态干净。"""

    async def t():
        from src.session.db import get_conn

        conn = await get_conn()
        await conn.execute("DELETE FROM users WHERE username IN ('test_user_001','tester2026')")
        await conn.commit()
        await close_db()

    _run(t())
