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
from typing import Any

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
  created_by TEXT DEFAULT '',
  approved_by TEXT DEFAULT '',
  rejected_by TEXT DEFAULT '',
  rolled_back_by TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


async def _ensure_kb_table() -> None:
    conn = await get_conn()
    await conn.execute(KB_SCHEMA)
    # 幂等迁移：老库补审计字段
    cur = await conn.execute("PRAGMA table_info(kb_docs)")
    cols = {r["name"] for r in await cur.fetchall()}
    for col in ("created_by", "approved_by", "rejected_by", "rolled_back_by"):
        if col not in cols:
            await conn.execute(f"ALTER TABLE kb_docs ADD COLUMN {col} TEXT DEFAULT ''")
    await conn.commit()


async def upload_document(filename: str, data: bytes, category: str = "", created_by: str = "") -> dict:
    """解析 + 分块 + 向量化，写入待审核记录（created_by 审计留痕）。返回 doc 摘要。"""
    await _ensure_kb_table()
    from src.kb.parser import chunk_text, parse_document

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "md"
    text = parse_document(filename, data)
    chunks = chunk_text(text)
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
        "INSERT INTO kb_docs (doc_id, filename, ext, category, status, chunk_count, chunks, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (doc_id, filename, ext, category, "pending", len(chunk_records),
         json.dumps(chunk_records, ensure_ascii=False), created_by, now, now),
    )
    await conn.commit()
    return {"doc_id": doc_id, "filename": filename, "chunk_count": len(chunk_records), "status": "pending"}


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
    from src.rag.vector_store import VectorStore

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
    import numpy as np

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


async def query_test(query: str, top_k: int = 5) -> list[dict]:
    """检索命中测试：给定问题返回召回的检索块（含相似度/来源/是否 KB）。"""
    from src.rag.retriever import catalog_context, is_catalog_query, retrieve_context

    hits = await retrieve_context(query, top_k=top_k)
    if not hits and is_catalog_query(query):
        hits = catalog_context(query, top_k=top_k)
    return [
        {
            "id": h["id"],
            "type": h["meta"].get("type", ""),
            "source": h["meta"].get("source", ""),
            "name": h["meta"].get("name", "")[:40],
            "dense_score": round(h.get("dense_score", 0.0), 3),
            "text": h["text"][:220],
            "is_kb": str(h["id"]).startswith("kb-"),
        }
        for h in hits
    ]


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
