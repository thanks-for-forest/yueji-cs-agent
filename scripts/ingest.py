#!/usr/bin/env python3
"""知识库构建流水线：产品/FAQ/政策 → 结构化分块 → 向量化（Ollama bge-m3）→ 入库 + BM25 语料。

运行：python scripts/ingest.py
输出：
  data/processed/chunks.json        # 检索块（text + meta），供 BM25/上下文使用
  data/processed/vector_index.npz   # 向量索引（VectorStore 持久化）
"""
from __future__ import annotations

import asyncio
import json

from config import settings
from src.llm.client import get_llm, close_llm
from src.rag.vector_store import VectorStore

BATCH = 32


def build_chunks() -> list[dict]:
    """构造检索块。"""
    chunks: list[dict] = []

    # ---- 产品：主条目 + 成分块 + 用法块 ----
    products = json.loads((settings.RAW_DATA_DIR / "products.json").read_text(encoding="utf-8"))
    for p in products:
        pid = p["product_id"]
        chunks.append({
            "id": f"prod-{pid}-main",
            "text": (
                f"【产品】{p['name']}（{p['brand']}，{p['category']}，规格{p['spec']}）\n"
                f"价格：¥{p['price']}（原价¥{p['original_price']}）\n"
                f"功效：{'、'.join(p['efficacy'])}\n"
                f"适用肤质：{'、'.join(p['skin_types'])}；适用肌肤问题：{'、'.join(p['skin_issues'])}\n"
                f"适用年龄：{'、'.join(p['age_groups'])}；保质期：{p['shelf_life']}\n"
                f"用户评分：{p['rating']} 分，月销 {p['monthly_sales']} 件"
            ),
            "meta": {"type": "product", "source": pid, "product_id": pid, "name": p["name"], "category": p["category"]},
        })
        chunks.append({
            "id": f"prod-{pid}-ingredients",
            "text": f"【{p['name']} 成分】{'、'.join(p['ingredients'])}；核心成分对应功效：{p['name']}主打{'、'.join(p['efficacy'])}。",
            "meta": {"type": "product", "source": pid, "product_id": pid, "name": p["name"], "category": p["category"]},
        })
        chunks.append({
            "id": f"prod-{pid}-usage",
            "text": f"【{p['name']} 使用方法】{p['usage']}。\n注意事项：{p['cautions']}。库存{p['stock']}件。",
            "meta": {"type": "product", "source": pid, "product_id": pid, "name": p["name"], "category": p["category"]},
        })

    # ---- FAQ：一问一答成块 ----
    faqs = []
    with open(settings.RAW_DATA_DIR / "faq.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                faqs.append(json.loads(line))
    for faq in faqs:
        chunks.append({
            "id": f"faq-{faq['faq_id']}",
            "text": f"【FAQ】问：{faq['question']}\n答：{faq['answer']}",
            "meta": {"type": "faq", "source": faq["faq_id"], "faq_id": faq["faq_id"],
                     "category": faq["category"], "name": faq["question"]},
        })

    # ---- 政策：按条成块 ----
    policies = json.loads((settings.RAW_DATA_DIR / "policies.json").read_text(encoding="utf-8"))
    for pol in policies:
        chunks.append({
            "id": f"policy-{pol['policy_id']}",
            "text": (
                f"【售后政策·{pol['type']}】{pol['summary']}\n"
                f"规则：{json.dumps(pol['rules'], ensure_ascii=False)}\n"
                f"流程：{pol['process']}；时效：{pol['duration']}；运费：{pol['freight']}"
            ),
            "meta": {"type": "policy", "source": pol["policy_id"], "policy_id": pol["policy_id"], "name": pol["type"]},
        })

    return chunks


async def main() -> None:
    settings.ensure_dirs()
    chunks = build_chunks()
    print(f"✅ 检索块 {len(chunks)} 个（产品 {sum(1 for c in chunks if c['meta']['type']=='product')} / "
          f"FAQ {sum(1 for c in chunks if c['meta']['type']=='faq')} / "
          f"政策 {sum(1 for c in chunks if c['meta']['type']=='policy')}）")

    llm = get_llm()
    texts = [c["text"] for c in chunks]
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]
        embs = await llm.embed(batch)
        vectors.extend(embs)
        print(f"  已向量化 {min(i + BATCH, len(texts))}/{len(texts)}")
    await close_llm()

    store = VectorStore(dim=settings.EMBED_DIM, persist_dir=settings.PROCESSED_DATA_DIR)
    store.add([c["id"] for c in chunks], vectors, [c["meta"] for c in chunks])
    store.persist(settings.VECTOR_INDEX_PATH)

    (settings.PROCESSED_DATA_DIR / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"✅ 向量库入库 {store.count} 条 -> {settings.VECTOR_INDEX_PATH}")
    print(f"✅ 检索语料 -> {settings.PROCESSED_DATA_DIR / 'chunks.json'}")


if __name__ == "__main__":
    asyncio.run(main())
