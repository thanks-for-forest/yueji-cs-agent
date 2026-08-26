"""生成检索评估对（query → 期望来源 source）：从基础库分块自动派生。

规则：
- 产品主块：query = 产品名 + 价格功效询问（期望 Pxxx）
- FAQ：query = 问题原文（期望 Fxxx）
- 政策：query = 政策名 + 规则询问（期望 POL-x）

输出：eval/retrieval_pairs.json
用法：python -m scripts.gen_retrieval_pairs [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def _policy_title(text: str) -> str:
    m = re.search(r"【售后政策·([^】]+)】", text)
    return m.group(1) if m else "售后政策"


def build_pairs(limit: int | None = None) -> list[dict]:
    """从 base_chunks.json 派生检索对。"""
    base_path = settings.PROCESSED_DATA_DIR / "base_chunks.json"
    if not base_path.exists():
        raise FileNotFoundError("缺少 base_chunks.json，请先运行 scripts/ingest.py")
    chunks = json.loads(base_path.read_text(encoding="utf-8"))

    pairs: list[dict] = []
    for c in chunks:
        meta = c.get("meta", {})
        t = meta.get("type")
        src = meta.get("source", "")
        if t == "product" and c["id"].endswith("-main"):
            name = meta.get("name", "")
            if name:
                pairs.append({"query": f"{name}多少钱，功效怎么样", "expected": [src],
                              "category": "product", "id": c["id"]})
        elif t == "faq":
            q = meta.get("name", "")
            if q:
                pairs.append({"query": q, "expected": [src], "category": "faq", "id": c["id"]})
        elif t == "policy":
            title = _policy_title(c["text"])
            pairs.append({"query": f"{title}怎么规定的", "expected": [src],
                          "category": "policy", "id": c["id"]})
    if limit:
        pairs = pairs[:limit]
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description="生成检索评估对")
    ap.add_argument("--limit", type=int, default=0, help="限制对数（默认全部）")
    args = ap.parse_args()

    pairs = build_pairs(args.limit or None)
    out = settings.EVAL_DIR / "retrieval_pairs.json"
    out.write_text(json.dumps(pairs, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter

    dist = Counter(p["category"] for p in pairs)
    print(f"已生成 {len(pairs)} 条检索对 → {out}（分布：{dict(dist)}）")


if __name__ == "__main__":
    main()
