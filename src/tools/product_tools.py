"""产品数据访问与查询工具。"""
from __future__ import annotations

import json
import logging

from config import settings
from src.tools.registry import Tool

logger = logging.getLogger(__name__)

_products: list[dict] | None = None


def load_products() -> list[dict]:
    global _products
    if _products is None:
        path = settings.RAW_DATA_DIR / "products.json"
        if not path.exists():
            logger.error("产品数据不存在：%s（请先运行 scripts/gen_data.py）", path)
            _products = []
        else:
            with open(path, encoding="utf-8") as f:
                _products = json.load(f)
    return _products


def _score_product(p: dict, kw: str) -> int:
    """简单的关键词打分：名称命中2分，标签/成分/品类命中1分。"""
    kw_l = kw.lower()
    haystack = " ".join(
        [p.get("name", ""), p.get("category", ""), p.get("brand", "")]
        + p.get("tags", [])
        + p.get("ingredients", [])
        + p.get("efficacy", [])
        + p.get("skin_types", [])
    ).lower()
    if kw_l in haystack:
        return 2 if kw_l in p.get("name", "").lower() else 1
    return 0


async def search_product(keyword: str, top_k: int = 3) -> dict:
    """按名称/标签/成分检索产品，返回 TopN。"""
    products = load_products()
    scored = [(p, _score_product(p, keyword)) for p in products]
    scored = [s for s in scored if s[1] > 0]
    scored.sort(key=lambda s: (-s[1], -s[0].get("monthly_sales", 0)))
    results = []
    for p, score in scored[:top_k]:
        results.append(
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "category": p["category"],
                "spec": p.get("spec", ""),
                "price": p.get("price"),
                "efficacy": p.get("efficacy", []),
                "skin_types": p.get("skin_types", []),
                "ingredients": p.get("ingredients", [])[:4],
                "rating": p.get("rating"),
                "monthly_sales": p.get("monthly_sales"),
            }
        )
    return {"found": bool(results), "keyword": keyword, "results": results}


async def get_product(product_id: str) -> dict:
    """按 ID 获取完整产品信息。"""
    products = load_products()
    for p in products:
        if p["product_id"] == product_id.strip().upper():
            return {"found": True, "product": p}
    return {"found": False, "message": f"未找到产品 {product_id}"}


def build_product_tools() -> list[Tool]:
    return [
        Tool(
            name="search_product",
            description="按名称/成分/功效/肤质关键词检索产品，返回 Top3 概要。商品咨询与护肤推荐场景使用。",
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "检索关键词，如 烟酰胺/控油/敏感肌"},
                    "top_k": {"type": "integer", "description": "返回条数，默认3"},
                },
                "required": ["keyword"],
            },
            func=search_product,
        ),
        Tool(
            name="get_product",
            description="按产品ID获取完整产品详情（成分/用法/注意事项/库存）。",
            parameters={
                "type": "object",
                "properties": {"product_id": {"type": "string", "description": "如 P001"}},
                "required": ["product_id"],
            },
            func=get_product,
        ),
    ]
