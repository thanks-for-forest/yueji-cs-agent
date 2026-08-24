"""槽位状态机测试。"""
from src.session.slots import Slot, SlotFiller, is_order_id, is_phone_tail


def test_slot_filler_missing_question():
    f = SlotFiller({
        "order_id": Slot("order_id", "订单号", required=True, question="请提供订单号", validator=is_order_id),
        "phone_tail": Slot("phone_tail", "手机尾号", required=True, question="请提供手机尾号", validator=is_phone_tail),
    })
    assert not f.is_complete()
    assert f.next_question() == "请提供订单号"  # 一次只问一个
    assert f.missing()[0].name == "order_id"


def test_slot_filler_fill_and_extract():
    f = SlotFiller({
        "order_id": Slot("order_id", "订单号", required=True, question="q", validator=is_order_id),
        "phone_tail": Slot("phone_tail", "手机尾号", required=True, question="q", validator=is_phone_tail),
    })
    ok, err = f.fill("order_id", "O202600001")
    assert ok
    assert f.next_question() == "q"
    ok, err = f.fill("phone_tail", "1234")
    assert ok
    assert f.is_complete()
    assert f.extract() == {"order_id": "O202600001", "phone_tail": "1234"}


def test_validators():
    assert is_order_id("O202600001")[0]
    assert not is_order_id("abc123")[0]
    assert not is_order_id("O123")[0]  # 太短
    assert is_phone_tail("1234")[0]
    assert not is_phone_tail("12a4")[0]
    assert not is_phone_tail("12345")[0]


def test_reset():
    f = SlotFiller({"a": Slot("a", "A", required=True, question="q")})
    f.fill("a", "x")
    assert f.is_complete()
    f.reset()
    assert not f.is_complete()
