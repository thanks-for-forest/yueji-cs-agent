#!/usr/bin/env python3
"""环境自检（W1）：依赖、模型、DeepSeek 连通性、数据与索引。

运行：python -m scripts.check_env
"""
from __future__ import annotations

import asyncio
import sys

from config import settings

CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok))
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))


async def main() -> None:
    settings.ensure_dirs()
    print("== 1. 依赖 ==")
    for pkg in ["fastapi", "streamlit", "httpx", "numpy", "rank_bm25", "aiosqlite", "pydantic", "langchain"]:
        try:
            __import__(pkg)
            check(f"python 包 {pkg}", True)
        except ImportError:
            check(f"python 包 {pkg}", False, "未安装")

    print("== 2. LLM（DeepSeek）==")
    from src.llm.client import close_llm, get_llm

    llm = get_llm()
    try:
        resp = await llm.chat([{"role": "user", "content": "回复OK两个字"}], max_tokens=10, temperature=0)
        check("DeepSeek chat", True, f"provider={resp.provider}")
    except Exception as e:  # noqa: BLE001
        check("DeepSeek chat", False, str(e)[:100])

    print("== 3. Embedding（Ollama bge-m3）==")
    try:
        embs = await llm.embed(["测试向量"])
        check("bge-m3 嵌入", True, f"维度={len(embs[0])}")
    except Exception as e:  # noqa: BLE001
        check("bge-m3 嵌入", False, str(e)[:100])
    await close_llm()

    print("== 4. 数据与索引 ==")
    check("产品数据", (settings.RAW_DATA_DIR / "products.json").exists())
    check("FAQ 数据", (settings.RAW_DATA_DIR / "faq.jsonl").exists())
    check("政策数据", (settings.RAW_DATA_DIR / "policies.json").exists())
    check("检索语料", (settings.PROCESSED_DATA_DIR / "chunks.json").exists())
    check("向量索引", settings.VECTOR_INDEX_PATH.exists())
    check("订单库", settings.DB_PATH.exists())

    print("== 5. 服务 ==")
    import httpx

    try:
        r = httpx.get(f"http://127.0.0.1:{settings.API_PORT}/health", timeout=3)
        check("API 服务", r.status_code == 200, f"http:{r.status_code}")
    except Exception:  # noqa: BLE001
        check("API 服务", False, "未启动（python -m uvicorn src.api.main:app）")

    failed = [n for n, ok in CHECKS if not ok]
    print()
    if failed:
        print(f"❌ {len(failed)} 项未通过：{', '.join(failed)}")
        sys.exit(1)
    print("✅ 全部通过，环境就绪！")


if __name__ == "__main__":
    asyncio.run(main())
