#!/usr/bin/env python3
"""并发压测：50 并发对话（验证发布门槛）。

运行：python -m scripts.stress_test [--concurrency 50] [--per 1]
前置：API 服务已启动（uvicorn）。
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx

from config import settings

API = f"http://127.0.0.1:{settings.API_PORT}"


async def one_call(client: httpx.AsyncClient, session_id: str, msg: str) -> dict:
    t0 = time.monotonic()
    resp = await client.post(f"{API}/api/chat", json={"session_id": session_id, "message": msg}, timeout=120)
    latency = time.monotonic() - t0
    return {"ok": resp.status_code == 200, "status": resp.status_code, "latency": latency}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--per", type=int, default=1, help="每会话请求数")
    args = parser.parse_args()

    # 预建会话
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{API}/api/session", json={})
        base = resp.json()["session_id"]

    msg = "玻尿酸保湿面霜多少钱"
    tasks = []
    async with httpx.AsyncClient(timeout=120) as client:
        for i in range(args.concurrency):
            sid = f"{base}{i:03d}" if len(base) < 60 else base[:50] + f"{i:03d}"
            for j in range(args.per):
                tasks.append(one_call(client, sid, msg))
        print(f"发起 {len(tasks)} 个并发请求…", flush=True)
        t0 = time.monotonic()
        results = await asyncio.gather(*tasks)
        total = time.monotonic() - t0

    ok = [r for r in results if r["ok"]]
    lat = sorted(r["latency"] for r in ok)
    p95 = lat[int(len(lat) * 0.95) - 1] if lat else 0
    print(f"✅ 成功 {len(ok)}/{len(results)}（成功率 {len(ok)/len(results)*100:.1f}%）")
    print(f"  总耗时 {total:.1f}s，平均 {statistics.mean(lat) if lat else 0:.2f}s，P95 {p95:.2f}s")
    if len(ok) < len(results):
        print("  ⚠️ 失败详情:", [r["status"] for r in results if not r["ok"]][:10])
        return
    print("  🎉 无 5xx，通过并发门槛（≥50 并发无 5xx）")


if __name__ == "__main__":
    asyncio.run(main())
