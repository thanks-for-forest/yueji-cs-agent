"""槽位状态机：订单查询/售后表单共用的多轮信息收集器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Slot:
    name: str
    label: str  # 追问时的称呼
    required: bool = True
    value: Any = None
    question: str = ""  # 缺省时的追问话术
    validator: Optional[callable] = None  # 返回 (ok, error_msg)

    @property
    def filled(self) -> bool:
        return self.value is not None and str(self.value).strip() != ""


@dataclass
class SlotFiller:
    """管理一组槽位，提供：缺失槽位追问、填充、完成判断。"""

    slots: dict[str, Slot] = field(default_factory=dict)

    def missing(self) -> list[Slot]:
        return [s for s in self.slots.values() if s.required and not s.filled]

    def is_complete(self) -> bool:
        return not self.missing()

    def next_question(self) -> str | None:
        m = self.missing()
        return m[0].question if m else None

    def fill(self, name: str, value: Any) -> tuple[bool, str]:
        """填充一个槽位，返回 (是否成功, 错误信息)。"""
        slot = self.slots.get(name)
        if slot is None:
            return False, f"未知槽位: {name}"
        if slot.validator:
            ok, msg = slot.validator(value)
            if not ok:
                return False, msg
        slot.value = value
        return True, ""

    def extract(self) -> dict:
        return {name: slot.value for name, slot in self.slots.items() if slot.filled}

    def reset(self) -> None:
        for s in self.slots.values():
            s.value = None


def is_order_id(v: Any) -> tuple[bool, str]:
    s = str(v or "").strip().upper()
    if not re_match_order(s):
        return False, "订单号格式不对，请提供类似 O202600001 的完整订单号"
    return True, ""


def re_match_order(s: str) -> bool:
    import re

    return bool(re.fullmatch(r"O\d{9,12}", s))


def is_phone_tail(v: Any) -> tuple[bool, str]:
    s = str(v or "").strip()
    if not s.isdigit() or len(s) != 4:
        return False, "请提供下单手机号的**后四位数字**，例如 1234"
    return True, ""


def is_choice(options: list[str]):
    def _v(v: Any) -> tuple[bool, str]:
        s = str(v or "").strip()
        for o in options:
            if o in s or s in o:
                return True, ""
        return False, f"请从以下选项中选择：{'、'.join(options)}"
    return _v
