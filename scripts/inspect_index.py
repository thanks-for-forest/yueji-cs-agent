#!/usr/bin/env python3
"""查看后端向量库：索引统计、分块清单、按类型/品类过滤、可选相似度检索。

用法:
  python scripts/inspect_index.py                     # 索引总览（条数/类型分布/品类分布）
  python scripts/inspect_index.py --type faq          # 只看 FAQ 分块
  python scripts/inspect_index.py --category 精华     # 只看某品类产品分块
  python scripts/inspect_index.py --id prod-P001-*    # 按 id 前缀过滤
  python scripts/inspect_index.py --keyword 退货      # 按文本关键字过滤
  python scripts/inspect_index.py --query "氨基酸洗面奶多少钱"   # 真实向量检索 TopK
  python scripts/inspect_index.py --top 20 --limit 5  # 显示条数/每块预览长度调整
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.vector_store import VectorStore  # noqa: E402


def load_index() -> tuple[VectorStore, list[dict], dict]:
    idx_path = Path("data/processed/vector_index.npz")
    if not idx_path.exists():
        sys.exit(f"[X] 找不到索引文件: {idx_path.resolve()}（请先运行 scripts/ingest.py 生成）")
    store = VectorStore.load(idx_path)
    chunks = json.loads(Path("data/processed/chunks.json").read_text(encoding="utf-8"))
    meta = json.loads(Path("data/processed/vector_index.meta.json").read_text(encoding="utf-8"))
    return store, chunks, meta


def show_overview(store: VectorStore, chunks: list[dict]) -> None:
    from collections import Counter

    types = Counter(c.get("meta", {}).get("type", "?") for c in chunks)
    cats = Counter(c.get("meta", {}).get("category", "—") for c in chunks)
    print(f"向量维度: {store.dim}  总块数: {store.count}  文件: data/processed/vector_index.npz")
    print(f"\n按类型分布: {dict(types)}")
    print(f"\n按品类分布(产品): {dict(cats)}")
    # base 快照对比
    base_p = Path("data/processed/base_chunks.json")
    if base_p.exists():
        n_base = len(json.loads(base_p.read_text(encoding="utf-8")))
        n_kb = store.count - n_base
        print(f"\n组成: 基础快照 {n_base} 块（40产品+217FAQ+10政策） + 已审核KB文档 {n_kb} 块")


def show_chunks(chunks: list[dict], args) -> None:
    rows = chunks
    if args.type:
        rows = [c for c in rows if c.get("meta", {}).get("type") == args.type]
    if args.category:
        rows = [c for c in rows if c.get("meta", {}).get("category") == args.category]
    if args.id:
        rows = [c for c in rows if c["id"].startswith(args.id)]
    if args.keyword:
        rows = [c for c in rows if args.keyword in c["text"]]
    print(f"\n共 {len(rows)} 块（过滤: type={args.type} category={args.category} id={args.id} keyword={args.keyword}）")
    for c in rows[: args.top]:
        m = c.get("meta", {})
        tag = f"[{m.get('type')}]" + (f"({m.get('category')})" if m.get("category") else "")
        preview = c["text"].replace("\n", " ")[: args.limit]
        print(f"  {c['id']:32s} {tag:14s} {preview}…")


def similarity_query(store: VectorStore, chunks: list[dict], q: str, top_k: int) -> None:
    import asyncio

    from src.llm.client import get_llm

    async def _run() -> None:
        print(f"\n检索: “{q}”  TopK={top_k}")
        try:
            vec = (await get_llm().embed([q]))[0]
        except Exception as e:  # noqa: BLE001
            sys.exit(f"[X] embedding 失败（Ollama 是否启动？ollama serve）: {e}")
        id2chunk = {c["id"]: c for c in chunks}
        for hit in store.query(vec, top_k=top_k):
            c = id2chunk.get(hit["id"], {})
            m = c.get("meta", {})
            print(f"\n  [{hit['score']:.4f}] {hit['id']}")
            print(f"      {c.get('text','(无)').replace(chr(10),' ')[:150]}…")

    asyncio.run(_run())


def main() -> None:
    ap = argparse.ArgumentParser(description="查看后端向量库")
    ap.add_argument("--type", help="按类型过滤: product|faq|policy|kb")
    ap.add_argument("--category", help="按品类过滤: 洁面|精华|水乳|面霜 等")
    ap.add_argument("--id", help="按 chunk id 前缀过滤")
    ap.add_argument("--keyword", help="按文本关键字过滤")
    ap.add_argument("--query", help="真实向量相似度检索（需 Ollama bge-m3 在线）")
    ap.add_argument("--top", type=int, default=15, help="最多显示条数")
    ap.add_argument("--limit", type=int, default=80, help="每条预览字符数")
    args = ap.parse_args()

    store, chunks, _meta = load_index()
    show_overview(store, chunks)
    if args.query:
        similarity_query(store, chunks, args.query, top_k=min(args.top, 10))
    else:
        show_chunks(chunks, args)


if __name__ == "__main__":
    main()
