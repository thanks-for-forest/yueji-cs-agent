"""混合检索器：Dense（向量）+ BM25（关键词）→ RRF 融合 → 可选 LLM 重排。

语料：数据构建阶段（scripts/ingest.py）把产品/FAQ/政策转为检索块并入库。
每个块形如：
{
  "id": "prod-P001-main",
  "text": "产品名：...；成分：...；功效：...",
  "meta": {"type": "product|faq|policy", "source": "P001", "product_id": "...", "faq_id": "..."}
}
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from rank_bm25 import BM25Okapi

from config import settings
from src.llm.client import get_llm
from src.rag.vector_store import get_product_store

logger = logging.getLogger(__name__)

_bm25: BM25Okapi | None = None
_tokenized: list[list[str]] = []
_chunks: list[dict] = []


def _tokenize(text: str) -> list[str]:
    """中文按字二元组 + 英文/数字词元。"""
    text = text.lower()
    tokens: list[str] = []
    # 英数词
    for m in re.finditer(r"[a-z0-9]+", text):
        tokens.append(m.group())
    # 中文二元组
    cn = re.sub(r"[^一-鿿]", "", text)
    tokens.extend(cn[i : i + 2] for i in range(len(cn) - 1))
    return tokens


def load_chunks() -> list[dict]:
    """从数据目录加载全部检索块（内存缓存）。"""
    global _chunks, _bm25, _tokenized
    if _chunks:
        return _chunks
    path = settings.PROCESSED_DATA_DIR / "chunks.json"
    if not path.exists():
        logger.error("检索块不存在：%s（请先运行 scripts/ingest.py）", path)
        return []
    _chunks = json.loads(path.read_text(encoding="utf-8"))
    _tokenized = [_tokenize(c["text"]) for c in _chunks]
    _bm25 = BM25Okapi(_tokenized)
    return _chunks


async def hybrid_search(query: str, top_k: int | None = None) -> list[dict]:
    """异步混合检索：Dense + BM25 → RRF 融合 → 返回带 meta 的结果（含融合分）。"""
    chunks = load_chunks()
    if not chunks:
        return []
    top_k = top_k or settings.RETRIEVE_FUSION_TOP_K

    # 1) Dense
    llm = get_llm()
    emb = (await llm.embed([query]))[0]
    dense_hits = get_product_store().query(emb, top_k=settings.RETRIEVE_DENSE_TOP_K)
    dense_ids = [h["id"] for h in dense_hits]

    # 2) BM25
    assert _bm25 is not None
    bm25_scores = _bm25.get_scores(_tokenize(query))
    bm25_rank = sorted(range(len(bm25_scores)), key=lambda i: -bm25_scores[i])[: settings.RETRIEVE_BM25_TOP_K]
    bm25_ids = [chunks[i]["id"] for i in bm25_rank]

    # 3) RRF 融合
    k = settings.RETRIEVE_RRF_K
    rrf: dict[str, float] = {}
    for rank, cid in enumerate(dense_ids):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (k + rank + 1)
    for rank, cid in enumerate(bm25_ids):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (k + rank + 1)

    ranked = sorted(rrf.items(), key=lambda kv: -kv[1])[:top_k]
    id2chunk = {c["id"]: c for c in chunks}
    results = []
    for cid, score in ranked:
        chunk = id2chunk.get(cid)
        if chunk:
            results.append({"id": cid, "fusion_score": score, "text": chunk["text"], "meta": chunk["meta"]})
    return results


async def retrieve_context(
    query: str,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[dict]:
    """面向 Agent 的检索入口：混合检索 + 可选 LLM 重排 + 阈值过滤。

    返回：按相关性排序的块列表（含 text/meta/fusion_score）。
    """
    results = await hybrid_search(query, top_k=top_k or settings.RETRIEVE_RERANK_TOP_K)
    min_score = min_score if min_score is not None else settings.RETRIEVE_MIN_SCORE

    if settings.RERANK_ENABLED and results:
        results = await _llm_rerank(query, results)

    # 阈值过滤：融合分低于阈值的视为"无可信答案"
    if not results:
        return []
    results = [r for r in results if r.get("fusion_score", 0) >= min_score]
    return results


async def _llm_rerank(query: str, results: list[dict]) -> list[dict]:
    """LLM 重排：让模型从候选中挑出最相关的 TopK（本地无专用 reranker 时的降级方案）。"""
    try:
        candidate_lines = "\n".join(
            f"[{i}] {r['meta'].get('source', r['id'])}: {r['text'][:100]}" for i, r in enumerate(results)
        )
        llm = get_llm()
        resp = await llm.chat(
            [
                {"role": "system", "content": "你是检索重排器。根据用户问题，从候选中选出最相关的条目，输出JSON数组格式：[序号]（如 [2,0,4]）。只输出JSON。"},
                {"role": "user", "content": f"问题：{query}\n候选：\n{candidate_lines}"},
            ],
            json_mode=True,
            max_tokens=200,
        )
        import json as _json

        order = _json.loads(resp.content.strip())
        if isinstance(order, list):
            ranked = [results[i] for i in order if isinstance(i, int) and 0 <= i < len(results)]
            if ranked:
                return ranked
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 重排失败，使用 RRF 结果：%s", e)
    return results
