"""订单工具：query_order / query_logistics。

安全约束：订单号 + 手机尾号双校验，防止越权查询他人订单。
"""
from __future__ import annotations

import json
from typing import Any

from src.session.db import get_conn
from src.tools.registry import Tool


def _mask_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else "****"


def _parse_tracking(tracking: str | None) -> dict:
    if not tracking:
        return {}
    try:
        return json.loads(tracking)
    except json.JSONDecodeError:
        return {}


def _order_public_view(row: dict[str, Any]) -> dict[str, Any]:
    """构造可展示的订单视图（脱敏）。"""
    tracking = _parse_tracking(row.get("tracking"))
    events = tracking.get("events", [])
    return {
        "order_id": row["order_id"],
        "status": row["status"],
        "total_amount": row["total_amount"],
        "created_at": row["created_at"],
        "items": json.loads(row["items"]),
        "phone_tail": row["phone"][-4:],
        "tracking_company": tracking.get("company", ""),
        "tracking_no": tracking.get("tracking_no", ""),
        "latest_event": events[-1] if events else None,
        "events": events[-3:],  # 最近3条物流动态
    }


async def _fetch_order(order_id: str, phone_tail: str, user_id: str = "") -> dict | None:
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    )
    row = await cur.fetchone()
    if row is None:
        return None
    data = dict(row)
    if data["phone"][-4:] != phone_tail:
        return None  # 手机尾号不匹配视为未找到（避免泄露存在性）
    if user_id and data["user_id"] != user_id:
        return None  # 归属校验：绑定用户时仅返回本人订单（防越权）
    return data


async def query_order(order_id: str, phone_tail: str, user_id: str = "") -> dict:
    """按订单号+手机尾号查询订单（绑定用户时仅查本人订单）。"""
    order = await _fetch_order(order_id.strip(), phone_tail.strip(), user_id)
    if order is None:
        return {"found": False, "message": "未找到匹配订单，请核对订单号与手机尾号"}
    view = _order_public_view(order)
    view["found"] = True
    return view


async def query_logistics(order_id: str, phone_tail: str, user_id: str = "") -> dict:
    """查询物流动态（绑定用户时仅查本人订单）。"""
    order = await _fetch_order(order_id.strip(), phone_tail.strip(), user_id)
    if order is None:
        return {"found": False, "message": "未找到匹配订单，请核对订单号与手机尾号"}
    tracking = _parse_tracking(order.get("tracking"))
    events = tracking.get("events", [])
    if order["status"] in ("待付款", "待发货"):
        return {
            "found": True,
            "order_id": order["order_id"],
            "status": order["status"],
            "message": "订单尚未发货，暂无物流信息",
            "events": [],
        }
    return {
        "found": True,
        "order_id": order["order_id"],
        "status": order["status"],
        "company": tracking.get("company", ""),
        "tracking_no": tracking.get("tracking_no", ""),
        "events": events,
    }


def build_order_tools() -> list[Tool]:
    return [
        Tool(
            name="query_order",
            description=(
                "按订单号+下单手机号后四位查询订单详情（状态/商品/金额/物流摘要）。"
                "用户查询订单时必须先收集这两个信息。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "完整订单号，如 O20260301001"},
                    "phone_tail": {"type": "string", "description": "下单手机号后四位"},
                },
                "required": ["order_id", "phone_tail"],
            },
            func=query_order,
            user_context=True,
        ),
        Tool(
            name="query_logistics",
            description="按订单号+手机尾号查询物流轨迹（快递公司/单号/最新动态）。",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "完整订单号"},
                    "phone_tail": {"type": "string", "description": "下单手机号后四位"},
                },
                "required": ["order_id", "phone_tail"],
            },
            func=query_logistics,
            user_context=True,
        ),
    ]
