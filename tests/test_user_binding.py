"""用户绑定与订单归属隔离测试。"""
import asyncio

import pytest

from src.session.db import close_db, init_db
from src.tools.aftersale_tools import check_aftersale_eligibility
from src.tools.order_tools import query_logistics, query_order


@pytest.fixture(scope="module", autouse=True)
def _db():
    asyncio.run(init_db())
    yield
    asyncio.run(close_db())


def _run(coro):
    return asyncio.run(coro)


def test_own_order_visible_with_binding():
    """绑定 U001 时能查到本人订单。"""
    r = _run(query_order("O202600001", "1234", user_id="U001"))
    assert r["found"] is True
    assert r["order_id"] == "O202600001"


def test_other_user_order_hidden_with_binding():
    """绑定 U001 时查 U005 的订单 → 归属校验拦截（即使手机尾号正确）。"""
    r = _run(query_order("O202600005", "5555", user_id="U001"))
    assert r["found"] is False  # 不泄露存在性


def test_other_user_logistics_hidden():
    r = _run(query_logistics("O202600005", "5555", user_id="U001"))
    assert r["found"] is False


def test_other_user_aftersale_hidden():
    r = _run(check_aftersale_eligibility("O202600005", "5555", "退货退款", user_id="U001"))
    assert r.get("found") is False


def test_no_binding_keeps_phone_tail_check():
    """未绑定用户（user_id=""）保持原行为：尾号正确即可查。"""
    r = _run(query_order("O202600001", "1234"))
    assert r["found"] is True
    r2 = _run(query_order("O202600001", "0000"))
    assert r2["found"] is False  # 尾号不符仍拒绝
