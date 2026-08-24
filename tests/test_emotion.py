"""情绪检测测试。"""
from src.emotion.detector import classify_rule, needs_transfer


def test_normal():
    assert classify_rule("请问这款精华怎么用？")[0] == "normal"


def test_negative():
    level, hits = classify_rule("等三天还不发货，太慢了，差评")
    assert level == "negative"
    assert "差评" in hits


def test_negative_strong_punct():
    assert classify_rule("你们怎么回事？？")[0] == "negative"
    assert classify_rule("气死我了！！")[0] == "negative"


def test_angry():
    assert classify_rule("你们就是骗子！我要投诉！")[0] == "angry"
    assert classify_rule("我要曝光你们315")[0] == "angry"
    assert classify_rule("垃圾产品，再也不买了！")[0] == "angry"


def test_needs_transfer():
    assert needs_transfer("angry", [])
    assert not needs_transfer("negative", ["negative"])
    assert needs_transfer("negative", ["negative", "negative"])
    assert not needs_transfer("normal", ["negative"])
