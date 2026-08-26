"""知识库管理服务：文档上传 → 解析 → 分块 → 向量化 → 审核入库 → 版本回滚。

设计（借鉴 Langchain-Chatchat / RAGFlow 的 KB 管理模式，轻量自研）：
- 上传后进入「待审核」，不立即生效；
- 审核通过后把该文档的分块并入活动索引（基础库 + 活动 KB 文档），检索即命中；
- 回滚/删除后重建合并索引，旧内容即时失效，可追溯版本。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from config import settings
from src.llm.client import get_llm
from src.session.db import get_conn

logger = logging.getLogger(__name__)

KB_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_docs (
  doc_id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  ext TEXT NOT NULL,
  category TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | active | rejected | rolled_back
  chunk_count INTEGER DEFAULT 0,
  chunks TEXT,                               -- JSON: [{text, vector:[...]}]
  raw_text TEXT DEFAULT '',                  -- 原始文本（重新分块用）
  created_by TEXT DEFAULT '',
  approved_by TEXT DEFAULT '',
  rejected_by TEXT DEFAULT '',
  rolled_back_by TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

# 检索命中测试历史（借鉴 Dify 的检索日志，用于命中率统计）
QUERY_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_query_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'dense_first',
  top_k INTEGER NOT NULL DEFAULT 5,
  hit_count INTEGER NOT NULL DEFAULT 0,
  top_score REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""


async def _ensure_kb_table() -> None:
    conn = await get_conn()
    await conn.execute(KB_SCHEMA)
    await conn.execute(QUERY_LOG_SCHEMA)
    # 幂等迁移：老库补审计字段
    cur = await conn.execute("PRAGMA table_info(kb_docs)")
    cols = {r["name"] for r in await cur.fetchall()}
    for col in ("created_by", "approved_by", "rejected_by", "rolled_back_by", "raw_text"):
        if col not in cols:
            await conn.execute(f"ALTER TABLE kb_docs ADD COLUMN {col} TEXT DEFAULT ''")
    await conn.commit()


def _resolve_chunk_params(chunk_size: int | None, overlap: int | None) -> tuple[int, int]:
    """分块策略参数：显式传入优先，否则用配置默认。"""
    cs = chunk_size or settings.KB_CHUNK_SIZE
    ov = overlap if overlap is not None else settings.KB_CHUNK_OVERLAP
    if cs < 50:
        cs = 50
    if ov < 0:
        ov = 0
    if ov >= cs:
        ov = max(cs // 2, 0)
    return cs, ov


async def upload_document(filename: str, data: bytes, category: str = "", created_by: str = "",
                          chunk_size: int | None = None, overlap: int | None = None) -> dict:
    """解析 + 分块 + 向量化，写入待审核记录（created_by 审计留痕）。返回 doc 摘要。"""
    await _ensure_kb_table()
    from src.kb.parser import chunk_text, parse_document

    cs, ov = _resolve_chunk_params(chunk_size, overlap)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "md"
    text = parse_document(filename, data)
    chunks = chunk_text(text, chunk_size=cs, overlap=ov)
    if not chunks:
        raise ValueError("文档解析后为空，请检查内容")

    # 向量化（bge-m3）
    llm = get_llm()
    vectors = await llm.embed(chunks)
    chunk_records = [{"text": c, "vector": v} for c, v in zip(chunks, vectors)]

    doc_id = f"KB-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4].upper()}"
    now = datetime.now().isoformat(timespec="seconds")
    conn = await get_conn()
    await conn.execute(
        "INSERT INTO kb_docs (doc_id, filename, ext, category, status, chunk_count, chunks, raw_text, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (doc_id, filename, ext, category, "pending", len(chunk_records),
         json.dumps(chunk_records, ensure_ascii=False), text, created_by, now, now),
    )
    await conn.commit()
    return {"doc_id": doc_id, "filename": filename, "chunk_count": len(chunk_records),
            "status": "pending", "chunk_size": cs, "overlap": ov}


async def upload_documents_batch(files: list[tuple[str, bytes]], category: str = "",
                                 created_by: str = "", chunk_size: int | None = None,
                                 overlap: int | None = None) -> dict:
    """批量上传多文档：解析所有文件 → 一次性向量化全部块 → 逐文档入库（待审核）。

    相比逐个上传减少多次 embed 往返。返回每文件结果 + 汇总。
    """
    await _ensure_kb_table()
    from src.kb.parser import chunk_text, parse_document

    cs, ov = _resolve_chunk_params(chunk_size, overlap)
    parsed: list[dict] = []  # {filename, ext, text, chunks}
    errors: list[dict] = []
    for filename, data in files:
        try:
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "md"
            text = parse_document(filename, data)
            chunks = chunk_text(text, chunk_size=cs, overlap=ov)
            if not chunks:
                raise ValueError("文档解析后为空，请检查内容")
            parsed.append({"filename": filename, "ext": ext, "text": text, "chunks": chunks})
        except Exception as e:  # noqa: BLE001
            errors.append({"filename": filename, "error": str(e)})

    # 一次性向量化所有块
    all_chunks = [c for p in parsed for c in p["chunks"]]
    llm = get_llm()
    vectors = await llm.embed(all_chunks) if all_chunks else []

    results: list[dict] = []
    vec_i = 0
    conn = await get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    for p in parsed:
        n = len(p["chunks"])
        chunk_records = [{"text": t, "vector": vectors[vec_i + j]} for j, t in enumerate(p["chunks"])]
        vec_i += n
        doc_id = f"KB-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4].upper()}"
        await conn.execute(
            "INSERT INTO kb_docs (doc_id, filename, ext, category, status, chunk_count, chunks, raw_text, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, p["filename"], p["ext"], category, "pending", n,
             json.dumps(chunk_records, ensure_ascii=False), p["text"], created_by, now, now),
        )
        results.append({"doc_id": doc_id, "filename": p["filename"], "chunk_count": n, "status": "pending"})
    await conn.commit()
    return {"results": results, "errors": errors, "ok": len(results), "failed": len(errors),
            "chunk_size": cs, "overlap": ov}


async def list_docs(status: str = "", category: str = "", keyword: str = "") -> list[dict]:
    """文档列表，支持状态/分类/关键词筛选。"""
    await _ensure_kb_table()
    conn = await get_conn()
    sql = ("SELECT doc_id, filename, ext, category, status, chunk_count, created_by, approved_by, "
           "rejected_by, rolled_back_by, created_at, updated_at FROM kb_docs WHERE 1=1")
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if category:
        sql += " AND category LIKE ?"
        params.append(f"%{category}%")
    if keyword:
        sql += " AND filename LIKE ?"
        params.append(f"%{keyword}%")
    sql += " ORDER BY created_at DESC"
    cur = await conn.execute(sql, params)
    return [dict(r) for r in await cur.fetchall()]


async def get_doc(doc_id: str) -> dict | None:
    await _ensure_kb_table()
    conn = await get_conn()
    cur = await conn.execute("SELECT * FROM kb_docs WHERE doc_id = ?", (doc_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["chunks"] = json.loads(d["chunks"] or "[]")
    return d


async def _set_status(doc_id: str, status: str, operator: str = "") -> None:
    """更新状态并记录操作人（审计留痕）。"""
    col = {"active": "approved_by", "rejected": "rejected_by", "rolled_back": "rolled_back_by"}.get(status)
    conn = await get_conn()
    if col:
        await conn.execute(f"UPDATE kb_docs SET status = ?, {col} = ?, updated_at = ? WHERE doc_id = ?",
                           (status, operator, datetime.now().isoformat(timespec="seconds"), doc_id))
    else:
        await conn.execute("UPDATE kb_docs SET status = ?, updated_at = ? WHERE doc_id = ?",
                           (status, datetime.now().isoformat(timespec="seconds"), doc_id))
    await conn.commit()


async def approve_doc(doc_id: str, operator: str = "") -> dict:
    """审核通过：先标记 active（记录操作人），再重建合并索引。"""
    doc = await get_doc(doc_id)
    if doc is None:
        raise ValueError(f"文档不存在: {doc_id}")
    await _set_status(doc_id, "active", operator)
    await rebuild_active_index()
    return {"doc_id": doc_id, "status": "active", "chunk_count": doc["chunk_count"]}


async def reject_doc(doc_id: str, operator: str = "") -> dict:
    await _set_status(doc_id, "rejected", operator)
    return {"doc_id": doc_id, "status": "rejected"}


async def rollback_doc(doc_id: str, operator: str = "") -> dict:
    """回滚：先标记 rolled_back（记录操作人），再重建索引。"""
    await _set_status(doc_id, "rolled_back", operator)
    await rebuild_active_index()
    return {"doc_id": doc_id, "status": "rolled_back"}


async def delete_doc(doc_id: str) -> dict:
    conn = await get_conn()
    cur = await conn.execute("SELECT status FROM kb_docs WHERE doc_id = ?", (doc_id,))
    row = await cur.fetchone()
    if row is None:
        raise ValueError(f"文档不存在: {doc_id}")
    was_active = row["status"] == "active"
    await conn.execute("DELETE FROM kb_docs WHERE doc_id = ?", (doc_id,))
    await conn.commit()
    if was_active:
        await rebuild_active_index()
    return {"doc_id": doc_id, "deleted": True}


async def active_kb_chunks() -> list[dict]:
    """活动 KB 文档的分块（含向量）。"""
    await _ensure_kb_table()
    conn = await get_conn()
    cur = await conn.execute("SELECT doc_id, filename, category, chunks FROM kb_docs WHERE status = 'active'")
    out = []
    for r in await cur.fetchall():
        for c in json.loads(r["chunks"] or "[]"):
            out.append({
                "id": f"kb-{r['doc_id']}-{len(out)}",
                "text": c["text"],
                "vector": c["vector"],
                "meta": {"type": "kb", "source": r["doc_id"], "name": r["filename"], "category": r["category"]},
            })
    return out


# ---------------- 索引重建（基础库 + 活动 KB 文档） ----------------
async def rebuild_active_index() -> None:
    """重建合并索引（基础库 + 活动 KB 文档），写入 vector_index.npz + chunks.json，并失效检索缓存。"""
    import numpy as np

    from src.rag import retriever

    # 1) 基础库（首次从当前索引快照，之后读快照）
    base_vec_path = settings.PROCESSED_DATA_DIR / "base_vectors.npz"
    base_chunks_path = settings.PROCESSED_DATA_DIR / "base_chunks.json"
    if not base_vec_path.exists() and settings.VECTOR_INDEX_PATH.exists():
        import shutil

        shutil.copy(settings.VECTOR_INDEX_PATH, base_vec_path)
        shutil.copy(settings.PROCESSED_DATA_DIR / "chunks.json", base_chunks_path)

    base_chunks = json.loads(base_chunks_path.read_text(encoding="utf-8")) if base_chunks_path.exists() else []
    base_vecs = None
    if base_vec_path.exists():
        base_vecs = np.load(str(base_vec_path))["vectors"]

    # 2) 活动 KB 文档
    kb = await active_kb_chunks()

    merged_chunks = base_chunks + [{"id": c["id"], "text": c["text"], "meta": c["meta"]} for c in kb]
    merged_vectors = None
    if base_vecs is not None:
        merged_vectors = base_vecs
    if kb:
        kb_vecs = np.asarray([c["vector"] for c in kb], dtype=np.float32)
        merged_vectors = np.vstack([merged_vectors, kb_vecs]) if merged_vectors is not None else kb_vecs

    # 3) 持久化（npz + chunks.json + meta.json 三者一致）
    settings.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if merged_vectors is not None:
        np.savez_compressed(str(settings.VECTOR_INDEX_PATH), vectors=merged_vectors)
    (settings.PROCESSED_DATA_DIR / "chunks.json").write_text(
        json.dumps(merged_chunks, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (settings.VECTOR_INDEX_PATH.with_suffix(".meta.json")).write_text(
        json.dumps({"ids": [c["id"] for c in merged_chunks],
                    "metas": [c["meta"] for c in merged_chunks]}, ensure_ascii=False), encoding="utf-8"
    )
    # 4) 失效检索缓存（重载 chunks/BM25/向量库）
    retriever.invalidate()
    _reset_vector_store()


def _reset_vector_store() -> None:
    import src.rag.vector_store as vs

    vs._product_store = None


def _kb_count() -> int:
    import asyncio

    return asyncio.run(_kb_count_async())


async def _kb_count_async() -> int:
    await _ensure_kb_table()
    conn = await get_conn()
    cur = await conn.execute("SELECT COUNT(*) c FROM kb_docs WHERE status = 'active'")
    return (await cur.fetchone())["c"]


# ---------------- 管理端增强功能（参考 Langchain-Chatchat/Dify 的 KB 管理） ----------------
async def stats() -> dict:
    """知识库统计：文档数、知识块、分类分布、基础库 vs KB 占比。"""

    docs = await list_docs()
    active = [d for d in docs if d["status"] == "active"]
    pending = [d for d in docs if d["status"] == "pending"]
    active_chunks = sum(d["chunk_count"] for d in active)
    # 基础库块数 = 总索引 - 活动 KB 块
    chunks_path = settings.PROCESSED_DATA_DIR / "chunks.json"
    total = len(json.loads(chunks_path.read_text(encoding="utf-8"))) if chunks_path.exists() else 0
    base_chunks = max(total - active_chunks, 0)
    # 分类分布（活动 + 待审核）
    cat_dist: dict[str, int] = {}
    for d in docs:
        if d["status"] in ("active", "pending"):
            cat = d["category"] or "未分类"
            cat_dist[cat] = cat_dist.get(cat, 0) + d["chunk_count"]
    return {
        "doc_total": len(docs),
        "pending": len(pending),
        "active": len(active),
        "active_chunks": active_chunks,
        "base_chunks": base_chunks,
        "category_dist": cat_dist,
    }


async def query_test(query: str, top_k: int = 5, mode: str = "dense_first", log: bool = True) -> list[dict]:
    """检索命中测试：给定问题返回召回的检索块（含相似度/来源/是否 KB），并记录检索日志。

    mode: dense_first（Dense优先融合，主链路）| rrf（RRF融合）| bm25（纯关键词）| dense（纯向量）。
    log=False 用于批量评估，避免污染检索历史。
    """
    from src.rag.retriever import bm25_search, catalog_context, dense_search, is_catalog_query, retrieve_context

    if mode == "bm25":
        hits = await bm25_search(query, top_k=top_k)
    elif mode == "dense":
        hits = await dense_search(query, top_k=top_k)
    else:
        hits = await retrieve_context(query, top_k=top_k, mode=mode)
        if not hits and is_catalog_query(query):
            hits = catalog_context(query, top_k=top_k)

    out = [
        {
            "id": h["id"],
            "type": h["meta"].get("type", ""),
            "source": h["meta"].get("source", ""),
            "name": h["meta"].get("name", "")[:40],
            "dense_score": round(h.get("dense_score", 0.0), 3),
            "bm25_score": round(h.get("bm25_score", 0.0), 3),
            "fusion_score": round(h.get("fusion_score", 0.0), 4),
            "text": h["text"][:220],
            "is_kb": str(h["id"]).startswith("kb-"),
        }
        for h in hits
    ]
    await _log_query_test(query, mode, top_k, out)
    return out


# ---------------- 检索评估报表（四模式 recall 对比，借鉴 Dify 检索评测） ----------------
_RETRIEVAL_MODES = ("dense_first", "rrf", "dense", "bm25")


async def retrieval_report(limit: int = 100, modes: tuple[str, ...] = _RETRIEVAL_MODES) -> dict:
    """对检索评估对跑各模式命中测试，输出 recall@3/recall@5、平均分、平均延迟。

    检索对来源：eval/retrieval_pairs.json（scripts/gen_retrieval_pairs.py 生成；
    缺失时现场生成）。expected 命中 = 任一召回块的 source ∈ expected。
    """
    import time

    from scripts.gen_retrieval_pairs import build_pairs

    pairs_path = settings.EVAL_DIR / "retrieval_pairs.json"
    if pairs_path.exists():
        pairs = json.loads(pairs_path.read_text(encoding="utf-8"))
    else:
        pairs = build_pairs()
    pairs = pairs[:limit] if limit else pairs
    if not pairs:
        return {"pairs": 0, "modes": {}}

    report: dict = {"pairs": len(pairs), "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "modes": {}}
    for mode in modes:
        hit3 = hit5 = 0
        score_sum = 0.0
        lat_sum = 0.0
        for p in pairs:
            t0 = time.perf_counter()
            hits = await query_test(p["query"], top_k=5, mode=mode, log=False)
            lat_sum += (time.perf_counter() - t0) * 1000
            sources = {h["source"] for h in hits}
            expected = set(p.get("expected", []))
            hit3 += bool(hits[:3] and (sources & expected))
            hit5 += bool(sources & expected)
            if hits:
                score_sum += max(h.get("dense_score") or 0.0 for h in hits)
        n = len(pairs)
        report["modes"][mode] = {
            "recall_at_3": round(hit3 / n, 3),
            "recall_at_5": round(hit5 / n, 3),
            "avg_top_dense_score": round(score_sum / n, 3),
            "avg_latency_ms": round(lat_sum / n, 1),
        }
    return report


async def _log_query_test(query: str, mode: str, top_k: int, hits: list[dict]) -> None:
    """检索历史落库（命中率统计用），失败不影响检索本身。"""
    try:
        await _ensure_kb_table()
        conn = await get_conn()
        await conn.execute(
            "INSERT INTO kb_query_log (query, mode, top_k, hit_count, top_score, created_at) VALUES (?,?,?,?,?,?)",
            (query[:200], mode, top_k, len(hits),
             max((h.get("dense_score") or 0.0) for h in hits) if hits else 0.0,
             datetime.now().isoformat(timespec="seconds")),
        )
        await conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("检索日志写入失败: %s", e)


async def query_stats(limit: int = 20) -> dict:
    """检索历史统计：最近 N 条 + 平均命中率/命中分布（借鉴 Dify 检索日志）。"""
    await _ensure_kb_table()
    conn = await get_conn()
    cur = await conn.execute("SELECT COUNT(*) c, SUM(hit_count) hits FROM kb_query_log")
    row = await cur.fetchone()
    total, hits = row["c"] or 0, row["hits"] or 0
    cur = await conn.execute(
        "SELECT query, mode, top_k, hit_count, top_score, created_at FROM kb_query_log "
        "ORDER BY id DESC LIMIT ?", (limit,))
    recent = [dict(r) for r in await cur.fetchall()]
    # 按查询聚合：出现次数 + 平均命中数
    agg: dict[str, dict] = {}
    for r in recent:
        k = r["query"]
        a = agg.setdefault(k, {"times": 0, "hits": 0})
        a["times"] += 1
        a["hits"] += r["hit_count"]
    top_queries = sorted(agg.items(), key=lambda kv: -kv[1]["times"])[:10]
    return {
        "total": total,
        "avg_hit_rate": round(hits / total, 3) if total else 0.0,
        "recent": recent,
        "top_queries": [{"query": q, "times": v["times"], "avg_hits": round(v["hits"] / v["times"], 2)}
                        for q, v in top_queries],
    }


async def delete_docs_batch(doc_ids: list[str]) -> dict:
    """批量删除文档（含已入库的），全部删除后统一重建一次索引。"""
    deleted, skipped = [], []
    was_active = False
    for did in doc_ids:
        conn = await get_conn()
        cur = await conn.execute("SELECT status FROM kb_docs WHERE doc_id = ?", (did,))
        row = await cur.fetchone()
        if row is None:
            skipped.append(did)
            continue
        if row["status"] == "active":
            was_active = True
        await conn.execute("DELETE FROM kb_docs WHERE doc_id = ?", (did,))
        await conn.commit()
        deleted.append(did)
    if was_active:
        await rebuild_active_index()
    return {"deleted": deleted, "skipped": skipped}


async def get_categories() -> list[str]:
    """分类清单：预置分类 ∪ 文档中出现的分类，按使用频次降序。"""
    await _ensure_kb_table()
    conn = await get_conn()
    cur = await conn.execute(
        "SELECT category, COUNT(*) c FROM kb_docs WHERE category != '' GROUP BY category ORDER BY c DESC")
    used = [(r["category"], r["c"]) for r in await cur.fetchall()]
    seen: set[str] = set()
    out: list[str] = []
    for cat, _cnt in sorted(used, key=lambda kv: -kv[1]):
        if cat not in seen:
            out.append(cat)
            seen.add(cat)
    for cat in settings.KB_PRESET_CATEGORIES:
        if cat not in seen:
            out.append(cat)
            seen.add(cat)
    return out


async def rechunk_doc(doc_id: str, chunk_size: int | None = None, overlap: int | None = None) -> dict:
    """按新分块策略重新切分文档并重新向量化（原始文本重新分块），已入库则重建索引。"""
    doc = await get_doc(doc_id)
    if doc is None:
        raise ValueError(f"文档不存在: {doc_id}")
    from src.kb.parser import chunk_text

    cs, ov = _resolve_chunk_params(chunk_size, overlap)
    raw = (doc.get("raw_text") or "").strip()
    if not raw:
        # 老数据无 raw_text：用现有分块文本拼接兜底
        raw = "\n\n".join(c["text"] for c in doc["chunks"])
    chunks = chunk_text(raw, chunk_size=cs, overlap=ov)
    if not chunks:
        raise ValueError("重新分块后为空，请检查文档内容")
    vectors = await get_llm().embed(chunks)
    chunk_records = [{"text": c, "vector": v} for c, v in zip(chunks, vectors)]
    conn = await get_conn()
    await conn.execute("UPDATE kb_docs SET chunks = ?, chunk_count = ?, updated_at = ? WHERE doc_id = ?",
                       (json.dumps(chunk_records, ensure_ascii=False), len(chunk_records),
                        datetime.now().isoformat(timespec="seconds"), doc_id))
    await conn.commit()
    if doc["status"] == "active":
        await rebuild_active_index()
    return {"doc_id": doc_id, "chunk_count": len(chunk_records), "chunk_size": cs, "overlap": ov}


async def export_kb(fmt: str = "json") -> dict:
    """导出知识库：json（结构化全量）或 md（人类可读），含基础库块 + KB 文档块。"""
    fmt = fmt.lower()
    if fmt not in ("json", "md"):
        raise ValueError("导出格式仅支持 json / md")
    docs = await list_docs()
    base_chunks_path = settings.PROCESSED_DATA_DIR / "base_chunks.json"
    base_chunks = json.loads(base_chunks_path.read_text(encoding="utf-8")) if base_chunks_path.exists() else []
    # list_docs 不含 chunks，逐个补齐
    doc_full = []
    for d in docs:
        full = await get_doc(d["doc_id"])
        if full:
            doc_full.append(full)
    if fmt == "json":
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "stats": await stats(),
            "base_chunks": [{"id": c["id"], "text": c["text"], "meta": c["meta"]} for c in base_chunks],
            "docs": [
                {
                    "doc_id": d["doc_id"], "filename": d["filename"], "category": d["category"],
                    "status": d["status"], "chunk_count": d["chunk_count"],
                    "chunks": [{"index": i, "text": c["text"]} for i, c in enumerate(d["chunks"])],
                }
                for d in doc_full
            ],
        }
        return {"filename": f"yueji_kb_export_{datetime.now():%Y%m%d_%H%M%S}.json",
                "content": json.dumps(payload, ensure_ascii=False, indent=1)}
    lines = [f"# 悦己 YUEJI 知识库导出（{datetime.now():%Y-%m-%d %H:%M}）", ""]
    for d in doc_full:
        lines += [f"## {d['filename']}（{d['doc_id']}）",
                  f"- 状态：{d['status']} ｜ 分类：{d['category'] or '-'} ｜ 分块：{d['chunk_count']}", ""]
        for i, c in enumerate(d["chunks"]):
            lines += [f"### 块 {i}", c["text"], ""]
    return {"filename": f"yueji_kb_export_{datetime.now():%Y%m%d_%H%M%S}.md",
            "content": "\n".join(lines)}


async def get_index_status() -> dict:
    """索引健康检查：文件存在性、块数一致性、组成与最后重建时间。"""
    import numpy as np

    chunks_path = settings.PROCESSED_DATA_DIR / "chunks.json"
    meta_path = settings.VECTOR_INDEX_PATH.with_suffix(".meta.json")
    base_vec_path = settings.PROCESSED_DATA_DIR / "base_vectors.npz"
    issues: list[str] = []
    info: dict = {"files": {}, "consistency": {}, "healthy": False}

    def _exists(p) -> bool:
        ok = p.exists()
        info["files"][p.name] = ok
        return ok

    npz_ok = _exists(settings.VECTOR_INDEX_PATH)
    chunks_ok = _exists(chunks_path)
    meta_ok = _exists(meta_path)
    base_ok = _exists(base_vec_path)

    n_chunks = n_vec = n_meta = n_base = 0
    if chunks_ok:
        n_chunks = len(json.loads(chunks_path.read_text(encoding="utf-8")))
    if npz_ok:
        n_vec = int(np.load(str(settings.VECTOR_INDEX_PATH))["vectors"].shape[0])
    if meta_ok:
        n_meta = len(json.loads(meta_path.read_text(encoding="utf-8"))["ids"])
    if base_ok:
        n_base = int(np.load(str(base_vec_path))["vectors"].shape[0])

    info["counts"] = {"chunks_json": n_chunks, "vectors_npz": n_vec, "meta_ids": n_meta,
                      "base_vectors": n_base}
    if not (npz_ok and chunks_ok and meta_ok):
        issues.append("索引文件缺失（请运行 scripts/ingest.py 或强制重建）")
    else:
        if n_vec != n_chunks:
            issues.append(f"向量矩阵({n_vec})与分块列表({n_chunks})不一致")
        if n_meta != n_chunks:
            issues.append(f"meta ids({n_meta})与分块列表({n_chunks})不一致")
    info["consistency"] = {"chunks_vs_vectors": n_chunks == n_vec and n_chunks > 0,
                           "chunks_vs_meta": n_chunks == n_meta and n_chunks > 0}
    info["issues"] = issues
    info["healthy"] = not issues
    info["last_rebuild_at"] = (
        datetime.fromtimestamp(settings.VECTOR_INDEX_PATH.stat().st_mtime).isoformat(timespec="seconds")
        if npz_ok else None
    )
    return info


async def rebuild_index() -> dict:
    """强制重建合并索引（基础库 + 活动 KB 文档）。"""
    await rebuild_active_index()
    return await get_index_status()


async def update_chunk(doc_id: str, index: int, text: str) -> dict:
    """编辑单个分块文本并重新向量化；已入库文档则重建索引。"""
    doc = await get_doc(doc_id)
    if doc is None:
        raise ValueError(f"文档不存在: {doc_id}")
    chunks = doc["chunks"]
    if not 0 <= index < len(chunks):
        raise ValueError(f"分块索引越界（0-{len(chunks)-1}）")
    text = text.strip()
    if not text:
        raise ValueError("分块内容不能为空")
    from src.llm.client import get_llm

    new_vec = (await get_llm().embed([text]))[0]
    chunks[index] = {"text": text, "vector": new_vec}
    conn = await get_conn()
    await conn.execute("UPDATE kb_docs SET chunks = ?, updated_at = ? WHERE doc_id = ?",
                       (json.dumps(chunks, ensure_ascii=False),
                        datetime.now().isoformat(timespec="seconds"), doc_id))
    await conn.commit()
    if doc["status"] == "active":
        await rebuild_active_index()
    return {"doc_id": doc_id, "index": index, "updated": True}


async def batch_approve(doc_ids: list[str], operator: str = "") -> dict:
    """批量审核通过（先统一改状态，再重建一次索引）。"""
    ok, skipped = [], []
    for did in doc_ids:
        doc = await get_doc(did)
        if doc is None or doc["status"] != "pending":
            skipped.append(did)
        else:
            await _set_status(did, "active", operator)
            ok.append(did)
    if ok:
        await rebuild_active_index()
    return {"approved": ok, "skipped": skipped}


async def batch_rollback(doc_ids: list[str], operator: str = "") -> dict:
    """批量回滚。"""
    ok, skipped = [], []
    for did in doc_ids:
        doc = await get_doc(did)
        if doc is None or doc["status"] != "active":
            skipped.append(did)
        else:
            await _set_status(did, "rolled_back", operator)
            ok.append(did)
    if ok:
        await rebuild_active_index()
    return {"rolled_back": ok, "skipped": skipped}
