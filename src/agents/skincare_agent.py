"""护肤推荐 Agent：肤质标签提取 → 标签匹配打分 → Top3 + 搭配建议。"""
from __future__ import annotations

import json
import logging

from src.agents.base_agent import AgentResult, BaseAgent
from src.llm.client import get_llm
from src.tools.product_tools import load_products

logger = logging.getLogger(__name__)

SKIN_TYPES = ["干性", "油性", "混合性", "敏感性", "中性"]
SKIN_ISSUES = ["痘痘", "敏感泛红", "暗沉", "干燥起皮", "毛孔粗大", "细纹", "黑头", "出油"]
AGE_GROUPS = ["<18", "18-25", "26-35", "36+"]

WEIGHTS = {"skin_types": 0.5, "skin_issues": 0.3, "age": 0.2}

SYSTEM_PROMPT_RECOMMEND = """你是「悦己 YUEJI 美妆」护肤顾问「小悦」。

【规则】
1. 根据系统提供的产品推荐列表（含匹配理由）生成推荐话术，推荐3款并说明**为什么适合用户**（引用肤质/问题标签）；
2. 附上「搭配建议」：洁面→水乳→面霜的完整护肤步骤搭配（基于推荐产品）；
3. 敏感肌/孕妇用户必须加一句温和提示（先测试/遵医嘱）；
4. 推荐理由简洁具体（如"含烟酰胺，针对你的暗沉和痘印"），不堆砌术语；
5. 标注每款产品的价格。

【输出格式】
推荐话术（150字内）+ 搭配建议
"""


async def extract_tags(text: str) -> dict:
    """LLM 提取肤质/问题/年龄标签；失败返回空（走兜底规则）。"""
    default = {"skin_types": [], "skin_issues": [], "age_group": ""}
    try:
        llm = get_llm()
        resp = await llm.chat(
            [
                {"role": "system", "content": (
                    "从用户护肤咨询中提取标签，输出JSON："
                    f'{{"skin_types": 取值[{",".join(SKIN_TYPES)}]的数组, "skin_issues": 取值[{",".join(SKIN_ISSUES)}]的数组, "age_group": 取值[{",".join(AGE_GROUPS)}]}}。'
                    "不确定的字段给空数组/空串。只输出JSON。"
                )},
                {"role": "user", "content": text},
            ],
            json_mode=True,
            max_tokens=150,
            temperature=0,
        )
        data = json.loads(resp.content.strip())
        data["skin_types"] = [t for t in data.get("skin_types", []) if t in SKIN_TYPES]
        data["skin_issues"] = [t for t in data.get("skin_issues", []) if t in SKIN_ISSUES]
        if data.get("age_group") not in AGE_GROUPS:
            data["age_group"] = ""
        return data
    except Exception as e:  # noqa: BLE001
        logger.warning("标签提取失败，走关键词兜底：%s", e)
        return _keyword_tags(text)


def _keyword_tags(text: str) -> dict:
    skin_types, issues = [], []
    for t in SKIN_TYPES:
        if t in text:
            skin_types.append(t)
    for it in SKIN_ISSUES:
        if it in text:
            issues.append(it)
    return {"skin_types": skin_types, "skin_issues": issues, "age_group": ""}


CATEGORY_KEYWORDS = {"洗面奶": "洁面", "洁面": "洁面", "精华": "精华", "水乳": "水乳", "面霜": "面霜", "晚霜": "面霜", "凝霜": "面霜"}


def _fallback_tags(text: str, memory: list[dict] | None) -> dict:
    """标签为空时的兜底：从当前消息+历史记忆提取肤质关键词（跨轮指代）。"""
    ctx = text + " " + " ".join(m.get("content", "") for m in (memory or [])[-4:])
    tags = _keyword_tags(ctx)
    if "男士" in ctx and not tags["skin_types"]:
        tags["skin_types"].append("油性")
        if "出油" not in tags["skin_issues"]:
            tags["skin_issues"].append("出油")
    return tags


def _detect_category(text: str) -> str | None:
    for kw, cat in CATEGORY_KEYWORDS.items():
        if kw in text:
            return cat
    return None


def score_products(products: list[dict], tags: dict, top_k: int = 3) -> list[tuple[dict, float, list[str]]]:
    """标签匹配打分，返回 [(product, score, reasons)]。"""
    scored = []
    for p in products:
        score = 0.0
        reasons: list[str] = []
        st = tags.get("skin_types") or []
        if st:
            hit = [s for s in st if s in p.get("skin_types", [])]
            if hit:
                score += WEIGHTS["skin_types"] * (len(hit) / len(st))
                reasons.append(f"适合{'/'.join(hit)}肤质")
        it = tags.get("skin_issues") or []
        if it:
            hit = [s for s in it if s in p.get("skin_issues", [])]
            if hit:
                score += WEIGHTS["skin_issues"] * (len(hit) / len(it))
                reasons.append(f"针对{'/'.join(hit)}")
        age = tags.get("age_group") or ""
        if age and age in p.get("age_groups", []):
            score += WEIGHTS["age"]
            reasons.append(f"适合{age}年龄段")
        if score > 0:
            scored.append((p, score, reasons))
    # 分数相同按销量排序
    scored.sort(key=lambda x: (-x[1], -x[0].get("monthly_sales", 0)))
    return scored[:top_k]


def build_routine(products: list[dict], tags: dict, top3: list[dict]) -> list[dict]:
    """搭配建议：在推荐Top3基础上补足 洁面/水乳/面霜 各一，构成完整routine。"""
    cats = {p["category"] for p in top3}
    need = [c for c in ["洁面", "水乳", "面霜"] if c not in cats]
    routine = list(top3)
    for cat in need:
        candidates = [p for p in products if p["category"] == cat]
        best = score_products(candidates, tags, top_k=1)
        if best:
            routine.append(best[0][0])
    return routine[:4]


class SkincareAgent(BaseAgent):
    name = "skincare"
    system_prompt = SYSTEM_PROMPT_RECOMMEND
    tool_names = ["search_product"]

    async def run(self, user_message, session, memory_messages, retrieved=None, **kw):
        tags = await extract_tags(user_message)
        if not tags["skin_types"] and not tags["skin_issues"]:
            tags = _fallback_tags(user_message, memory_messages)
        products = load_products()
        top = score_products(products, tags, top_k=3)

        # 兜底：仍无命中 → 按品类/热门推荐
        if not top:
            cat = _detect_category(user_message)
            candidates = [p for p in products if p["category"] == cat] if cat else products
            picks = sorted(candidates, key=lambda p: -p.get("monthly_sales", 0))[:3]
            top = [(p, 0.0, ["热门推荐"]) for p in picks]

        if not top:
            return AgentResult(
                reply="为了给您更精准的推荐，可以告诉我更多信息吗？比如：**您的肤质**（干性/油性/混合/敏感）、**想解决的肌肤问题**（痘痘/暗沉/干燥/出油等）？",
                sources=[], intent="skincare_recommend", action="clarify",
                meta_updates={"step": "skincare_ask"},
            )

        top3 = [t[0] for t in top]
        routine = build_routine(products, tags, top3)
        rec_data = {
            "tags": tags,
            "top3": [
                {"name": p["name"], "price": p["price"], "category": p["category"],
                 "efficacy": p["efficacy"][:3], "reasons": reasons, "product_id": p["product_id"]}
                for p, score, reasons in top
            ],
            "routine": [
                {"name": p["name"], "category": p["category"], "price": p["price"]} for p in routine
            ],
        }
        ask_more = "如果想获得更精准的推荐，可以告诉我您的肤质和肌肤问题哦～" if not tags.get("skin_types") else ""

        try:
            llm = get_llm()
            resp = await llm.chat(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"用户描述：{user_message}\n\n【推荐数据】\n{json.dumps(rec_data, ensure_ascii=False)}"},
                ],
                max_tokens=500,
            )
            reply = resp.content.strip()
            if ask_more and ask_more not in reply:
                reply = reply + "\n\n" + ask_more
        except Exception as e:  # noqa: BLE001
            logger.warning("推荐话术生成失败：%s", e)
            reply = "根据您的需求，为您推荐：" + "、".join(f"{p['name']}（¥{p['price']}）" for p in top3)

        return AgentResult(
            reply=reply,
            sources=[{"name": p["name"], "type": "product", "source_id": p["product_id"]} for p in top3],
            intent="skincare_recommend",
            action="recommend",
            extra={"tags": tags, "recommendations": rec_data["top3"], "routine": rec_data["routine"]},
            meta_updates={"last_product": top3[0]["name"]},
        )
