"""向量存储：基于 numpy 的轻量实现（语料规模 ~几百块，无需外部向量库）。

对外接口与 Chroma/Milvus 对齐（add / query / count / persist / load），
后续如需平滑迁移到集群版向量库，仅需替换本模块实现。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from config import settings


class VectorStore:
    def __init__(self, dim: int = 1024, persist_dir: Optional[Path] = None):
        self.dim = dim
        self.persist_dir = persist_dir
        self._ids: list[str] = []
        self._metas: list[dict] = []
        self._vectors: np.ndarray | None = None

    # ---------- 写入 ----------
    def add(self, ids: list[str], vectors: list[list[float]], metas: list[dict]) -> None:
        arr = np.asarray(vectors, dtype=np.float32)
        if self._vectors is None:
            self._vectors = arr
        else:
            self._vectors = np.vstack([self._vectors, arr])
        self._ids.extend(ids)
        self._metas.extend(metas)

    # ---------- 查询 ----------
    def query(self, vector: list[float], top_k: int = 10) -> list[dict]:
        """余弦相似度 TopK。"""
        if self._vectors is None or len(self._ids) == 0:
            return []
        q = np.asarray(vector, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        scores = (self._vectors @ q) / (np.linalg.norm(self._vectors, axis=1) * qn + 1e-9)
        top_idx = np.argsort(-scores)[:top_k]
        return [
            {
                "id": self._ids[i],
                "score": float(scores[i]),
                "meta": self._metas[i],
            }
            for i in top_idx
            if scores[i] > -1.0
        ]

    @property
    def count(self) -> int:
        return len(self._ids)

    # ---------- 持久化 ----------
    def persist(self, path: Optional[Path] = None) -> None:
        path = path or self.persist_dir
        if path is None or self._vectors is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(path), vectors=self._vectors)
        meta_path = path.with_suffix(".meta.json")
        meta_path.write_text(
            json.dumps({"ids": self._ids, "metas": self._metas}, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path, dim: int = 1024) -> "VectorStore":
        store = cls(dim=dim, persist_dir=path.parent)
        data = np.load(str(path))
        store._vectors = data["vectors"]
        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        store._ids = meta["ids"]
        store._metas = meta["metas"]
        return store


def get_product_store() -> VectorStore:
    """商品/FAQ 合并向量库（进程级单例）。"""
    global _product_store
    if _product_store is None:
        idx_path = settings.VECTOR_INDEX_PATH
        if idx_path.exists():
            _product_store = VectorStore.load(idx_path, settings.EMBED_DIM)
        else:
            _product_store = VectorStore(dim=settings.EMBED_DIM, persist_dir=idx_path.parent)
    return _product_store


_product_store: VectorStore | None = None
