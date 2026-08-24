"""售后工具：check_aftersale_eligibility（规则判定） / create_ticket（生成工单）。"""
from __future__ import annotations

import json
from datetime import datetime

from src.session.db import get_conn
from src.tools.aftersale_rules import VALID_TYPES, days_since, evaluate_eligibility
from src.tools.order_tools import _fetch_order
from src.tools.registry import Tool


async def check_aftersale_eligibility(
    order_id: str,
    phone_tail: str,
    issue_type: str,
    description: str = "",
    resaleable: bool = True,
    has_evidence: bool = False,
    mismatch_confirmed: bool = False,
) -> dict:
    """按订单与售后类型做规则判定。"""
    if issue_type not in VALID_TYPES:
        return {"eligible": False, "message": f"不支持的售后类型：{issue_type}", "reasons": [], "alternative": "请选择：退货退款 / 质量问题 / 换货 / 仅退款 / 补发"}
    order = await _fetch_order(order_id.strip(), phone_tail.strip())
    if order is None:
        return {"found": False, "eligible": False, "message": "未找到匹配订单，请核对订单号与手机尾号"}
    # 签收天数：以物流最后事件时间近似，缺失则按下单时间
    tracking = json.loads(order.get("tracking") or "{}")
    events = tracking.get("events", [])
    receipt_date = events[-1].get("time") if events else order["created_at"]
    result = evaluate_eligibility(
        issue_type=issue_type,
        days_since_receipt=days_since(receipt_date),
        order_status=order["status"],
        resaleable=resaleable,
        has_evidence=has_evidence,
        mismatch_confirmed=mismatch_confirmed,
    )
    result["found"] = True
    result["order_id"] = order["order_id"]
    result["order_status"] = order["status"]
    return result


async def create_ticket(
    order_id: str,
    phone_tail: str,
    type: str,
    reason: str,
    description: str,
    evidence: list[str] | None = None,
) -> dict:
    """校验订单与资格后生成售后工单。"""
    if type not in VALID_TYPES:
        return {"created": False, "message": f"不支持的售后类型：{type}"}
    order = await _fetch_order(order_id.strip(), phone_tail.strip())
    if order is None:
        return {"created": False, "message": "未找到匹配订单，请核对订单号与手机尾号"}

    tracking = json.loads(order.get("tracking") or "{}")
    events = tracking.get("events", [])
    receipt_date = events[-1].get("time") if events else order["created_at"]
    # 二次校验资格（服务端兜底，防止绕过规则）
    check = evaluate_eligibility(
        issue_type=type,
        days_since_receipt=days_since(receipt_date),
        order_status=order["status"],
        resaleable=True,
        has_evidence=bool(evidence),
        mismatch_confirmed=(type == "补发"),
    )
    if not check["eligible"]:
        return {"created": False, "message": "不符合售后条件", "reasons": check["reasons"], "alternative": check["alternative"]}

    ticket_id = f"AS{datetime.now():%Y%m%d}-{datetime.now():%H%M%S}"
    condition_check = {
        "days_since_receipt": days_since(receipt_date),
        "order_status": order["status"],
        "type": type,
        "eligible": True,
    }
    conn = await get_conn()
    await conn.execute(
        "INSERT INTO tickets (ticket_id, order_id, user_id, type, reason, description, evidence, condition_check, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ticket_id,
            order["order_id"],
            order["user_id"],
            type,
            reason,
            description,
            json.dumps(evidence or [], ensure_ascii=False),
            json.dumps(condition_check, ensure_ascii=False),
            "待审核",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    await conn.execute(
        "UPDATE orders SET aftersale_status = ? WHERE order_id = ?", (type, order["order_id"])
    )
    await conn.commit()
    return {
        "created": True,
        "ticket_id": ticket_id,
        "type": type,
        "status": "待审核",
        "message": "工单已生成，审核1-3个工作日，退款原路返回3-7个工作日",
        "next_steps": check["next_steps"],
    }


def build_aftersale_tools() -> list[Tool]:
    return [
        Tool(
            name="check_aftersale_eligibility",
            description=(
                "售后资格判定：根据订单与售后类型（退货退款/质量问题/换货/仅退款/补发）判断是否符合条件，"
                "并给出处理建议。用户申请售后时先调用本工具。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "phone_tail": {"type": "string", "description": "下单手机号后四位"},
                    "issue_type": {"type": "string", "enum": VALID_TYPES, "description": "售后类型"},
                    "description": {"type": "string", "description": "问题描述"},
                    "resaleable": {"type": "boolean", "description": "商品是否未使用、不影响二次销售"},
                    "has_evidence": {"type": "boolean", "description": "是否已有凭证（照片/视频）"},
                    "mismatch_confirmed": {"type": "boolean", "description": "是否确认错发/漏发（补发场景）"},
                },
                "required": ["order_id", "phone_tail", "issue_type"],
            },
            func=check_aftersale_eligibility,
        ),
        Tool(
            name="create_ticket",
            description="生成售后工单（服务端会二次校验资格）。仅在资格判定通过且用户确认申请后调用。",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "phone_tail": {"type": "string"},
                    "type": {"type": "string", "enum": VALID_TYPES},
                    "reason": {"type": "string", "description": "售后原因，如 质量问题/不想要了"},
                    "description": {"type": "string", "description": "详细描述"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "description": "凭证描述列表"},
                },
                "required": ["order_id", "phone_tail", "type", "reason", "description"],
            },
            func=create_ticket,
        ),
    ]
