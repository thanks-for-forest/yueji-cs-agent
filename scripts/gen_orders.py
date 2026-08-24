#!/usr/bin/env python3
"""生成 20 条模拟订单（覆盖 6 种状态），写入 SQLite。

运行：python scripts/gen_orders.py
状态分布：待付款2 / 待发货3 / 已发货4 / 已完成6 / 已取消2 / 退款中3
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta

from config import settings
from src.session.db import close_db, get_conn

random.seed(2026)

PHONES = ["13800001234", "13911112222", "15022223333", "13633334444", "18844445555",
          "15555556666", "13766667777", "18677778888", "13388889999", "15999990000"]


def _items(rng: random.Random, products: list[dict], n: int) -> list[dict]:
    picked = rng.sample(products, min(n, len(products)))
    return [{"product_id": p["product_id"], "name": p["name"], "qty": rng.randint(1, 3),
             "price": p["price"]} for p in picked]


def _tracking(rng: random.Random, status: str, created: datetime) -> dict | None:
    if status not in ("已发货", "已完成", "退款中"):
        return None
    company = rng.choice(["顺丰速运", "中通快递"])
    no = f"{'SF' if company == '顺丰速运' else 'ZT'}{rng.randint(1000000000, 9999999999)}"
    events = [{"time": (created + timedelta(hours=6)).isoformat(timespec="minutes"), "desc": "商家已发货，快件已揽收"},
              {"time": (created + timedelta(hours=26)).isoformat(timespec="minutes"), "desc": "快件已到达【城市】转运中心"},
              {"time": (created + timedelta(hours=40)).isoformat(timespec="minutes"), "desc": "快件派送中，请保持电话畅通"}]
    if status in ("已完成", "退款中"):
        events.append({"time": (created + timedelta(hours=52)).isoformat(timespec="minutes"), "desc": "快件已签收，签收人：本人"})
    return {"company": company, "tracking_no": no, "events": events}


def build_orders() -> list[dict]:
    products = json.loads((settings.RAW_DATA_DIR / "products.json").read_text(encoding="utf-8"))
    rng = random.Random(2026)
    now = datetime.now()
    statuses = ["待付款"] * 2 + ["待发货"] * 3 + ["已发货"] * 4 + ["已完成"] * 6 + ["已取消"] * 2 + ["退款中"] * 3
    rng.shuffle(statuses)
    orders = []
    for i, status in enumerate(statuses, start=1):
        user_idx = (i - 1) % len(PHONES)
        created = now - timedelta(days=rng.randint(1, 25), hours=rng.randint(0, 23))
        items = _items(rng, products, rng.randint(1, 3))
        total = round(sum(it["price"] * it["qty"] for it in items), 2)
        orders.append({
            "order_id": f"O2026{i:05d}",
            "user_id": f"U{user_idx + 1:03d}",
            "phone": PHONES[user_idx],
            "status": status,
            "total_amount": total,
            "created_at": created.isoformat(timespec="seconds"),
            "items": items,
            "tracking": _tracking(rng, status, created),
            "aftersale_status": "质量问题-退货退款" if status == "退款中" else None,
        })
    return orders


async def main() -> None:
    orders = build_orders()
    conn = await get_conn()
    await conn.execute("DELETE FROM orders")
    for o in orders:
        await conn.execute(
            "INSERT INTO orders (order_id, user_id, phone, status, total_amount, created_at, items, tracking, aftersale_status) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (o["order_id"], o["user_id"], o["phone"], o["status"], o["total_amount"],
             o["created_at"], json.dumps(o["items"], ensure_ascii=False),
             json.dumps(o["tracking"], ensure_ascii=False) if o["tracking"] else None,
             o["aftersale_status"]),
        )
    await conn.commit()
    await close_db()
    print(f"✅ 生成订单 {len(orders)} 条 -> {settings.DB_PATH}")
    from collections import Counter
    print(f"✅ 状态分布: {dict(Counter(o['status'] for o in orders))}")


if __name__ == "__main__":
    asyncio.run(main())
