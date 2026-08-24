"""售后规则引擎测试。"""
from src.tools.aftersale_rules import evaluate_eligibility


def test_7days_returns_eligible():
    r = evaluate_eligibility("退货退款", days_since_receipt=3, order_status="已完成", resaleable=True)
    assert r["eligible"] is True


def test_7days_overdue():
    r = evaluate_eligibility("退货退款", days_since_receipt=10, order_status="已完成", resaleable=True)
    assert r["eligible"] is False
    assert any("受理期" in s for s in r["reasons"])
    assert r["alternative"]  # 换货替代


def test_used_product_not_eligible():
    r = evaluate_eligibility("退货退款", days_since_receipt=2, order_status="已完成", resaleable=False)
    assert r["eligible"] is False
    assert any("二次销售" in s for s in r["reasons"])


def test_quality_issue_needs_evidence():
    r = evaluate_eligibility("质量问题", days_since_receipt=10, order_status="已完成", has_evidence=False)
    assert r["eligible"] is False
    assert any("凭证" in s for s in r["reasons"])
    r2 = evaluate_eligibility("质量问题", days_since_receipt=10, order_status="已完成", has_evidence=True)
    assert r2["eligible"] is True


def test_only_refund_unpaid_order():
    r = evaluate_eligibility("仅退款", days_since_receipt=0, order_status="待付款")
    assert r["eligible"] is False
    r2 = evaluate_eligibility("仅退款", days_since_receipt=0, order_status="待发货")
    assert r2["eligible"] is True


def test_mistake_reship_requires_confirmation():
    r = evaluate_eligibility("补发", days_since_receipt=2, order_status="已完成", mismatch_confirmed=False)
    assert r["eligible"] is False
    r2 = evaluate_eligibility("补发", days_since_receipt=2, order_status="已完成", mismatch_confirmed=True)
    assert r2["eligible"] is True


def test_invalid_type():
    r = evaluate_eligibility("未知类型", days_since_receipt=1, order_status="已完成")
    assert r["eligible"] is False
