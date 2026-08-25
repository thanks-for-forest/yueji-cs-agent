"""售后规则引擎（纯函数，便于单测）。

规则（参考主流电商售后政策，简化）：
- 退货退款：签收 7 天内（含）、未使用、不影响二次销售 → 通过；否则提示换货/质量问题凭证路径
- 质量问题：30 天内，需凭证（照片/视频）→ 通过
- 换货：15 天内、未使用 → 通过
- 仅退款：仅"未发货"或"质量问题待复核"场景
- 错发漏发（补发）：30 天内，需核对订单商品与实际收货 → 免费补发
"""
from __future__ import annotations

from datetime import datetime

# 各售后类型规则
RULES: dict[str, dict] = {
    "退货退款": {"max_days": 7, "need_resaleable": True, "need_evidence": False},
    "质量问题": {"max_days": 30, "need_resaleable": False, "need_evidence": True},
    "换货": {"max_days": 15, "need_resaleable": True, "need_evidence": False},
    "仅退款": {"max_days": 7, "need_resaleable": False, "need_evidence": True},
    "补发": {"max_days": 30, "need_resaleable": False, "need_evidence": True},
}
VALID_TYPES = list(RULES.keys())


def days_since(date_str: str, now: datetime | None = None) -> int:
    """计算从 date_str 到参考时间的天数（向下取整，最少0）。

    评测时可用 settings.REFERENCE_NOW 固定基准，避免结果随真实日期漂移。
    """
    if now is None:
        from config import settings

        if settings.REFERENCE_NOW:
            try:
                now = datetime.fromisoformat(settings.REFERENCE_NOW)
            except ValueError:
                now = datetime.now()
        else:
            now = datetime.now()
    try:
        dt = datetime.fromisoformat(date_str)
    except ValueError:
        return 0
    return max(0, (now - dt).days)


def evaluate_eligibility(
    issue_type: str,
    days_since_receipt: int,
    order_status: str,
    resaleable: bool = True,
    has_evidence: bool = False,
    mismatch_confirmed: bool = False,
) -> dict:
    """返回 {eligible, reasons, alternative, next_steps}。"""
    if issue_type not in VALID_TYPES:
        return {
            "eligible": False,
            "reasons": [f"暂不支持该售后类型：{issue_type}"],
            "alternative": "请选择：退货退款 / 质量问题 / 换货 / 仅退款 / 补发",
            "next_steps": [],
        }

    rule = RULES[issue_type]
    reasons: list[str] = []
    ok = True

    if issue_type == "仅退款":
        if order_status == "待付款":
            ok, reasons = False, ["订单未付款，无需售后"]
        elif order_status == "未发货" or order_status == "待发货":
            ok, reasons = True, ["订单未发货，可申请仅退款"]
        else:
            ok = False
            reasons = ["订单已发货，不支持直接仅退款；请选择退货退款或质量问题流程"]
        if ok:
            return {
                "eligible": True,
                "reasons": reasons,
                "alternative": "",
                "next_steps": ["确认申请仅退款 → 款项原路退回"],
            }
        return {
            "eligible": False,
            "reasons": reasons,
            "alternative": "可尝试退货退款（签收7天内）或质量问题流程（30天内）",
            "next_steps": [],
        }

    if issue_type == "补发":
        if not mismatch_confirmed:
            ok = False
            reasons = ["补发需先核对：实际收到的商品与订单不一致（错发/漏发）"]
        elif days_since_receipt > rule["max_days"]:
            ok = False
            reasons = [f"已超出补发受理期（{rule['max_days']}天）"]
        else:
            reasons = ["错发/漏发核实后可免费补发"]
        if ok:
            return {
                "eligible": True,
                "reasons": reasons,
                "alternative": "",
                "next_steps": ["核实错发/漏发 → 提交凭证 → 当天顺丰补发"],
            }
        return {
            "eligible": False,
            "reasons": reasons,
            "alternative": "若非错发漏发，可考虑质量问题流程",
            "next_steps": [],
        }

    if days_since_receipt > rule["max_days"]:
        ok = False
        reasons.append(f"已超出{issue_type}受理期（签收后{rule['max_days']}天内）")
    if rule["need_resaleable"] and not resaleable:
        ok = False
        reasons.append("商品已使用/影响二次销售，不符合退货条件")
    if rule["need_evidence"] and not has_evidence:
        ok = False
        reasons.append("需要提供凭证（照片/视频）以便核实")

    if ok:
        return {
            "eligible": True,
            "reasons": reasons or ["符合售后条件"],
            "alternative": "",
            "next_steps": ["填写申请信息 → 提交凭证 → 审核（1-3个工作日）"],
        }
    alternative = "可申请换货" if issue_type == "退货退款" and days_since_receipt <= RULES["换货"]["max_days"] else ""
    return {
        "eligible": False,
        "reasons": reasons,
        "alternative": alternative,
        "next_steps": [],
    }
