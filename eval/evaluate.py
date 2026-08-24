#!/usr/bin/env python3
"""双轨评测：确定性检查（意图/情绪/动作/断言）+ LLM-as-Judge（质量/幻觉）。

运行：python -m eval.evaluate [--quick N]
输出：eval/reports/<时间戳>_report.json 与 .md
指标：问题解决率、意图准确率、情绪准确率、转人工P/R、幻觉率、延迟、检索 recall/MRR/NDCG。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from config import settings

logging.basicConfig(level=logging.WARNING)

JUDGE_SYSTEM = """你是电商客服质量评测员。请严格评估客服回复质量。

评分标准（1-5分）：
5 = 回答完全正确、完整、有依据（引用了知识来源），礼貌专业
4 = 正确且基本完整，可能缺少个别细节
3 = 部分正确或缺少关键信息
2 = 有明显错误、答非所问或未解决用户问题
1 = 严重错误或编造信息

同时判定：回复中是否存在【无依据的编造内容】（幻觉，如虚构产品/价格/政策/事实）。

只输出JSON：{"score": int, "hallucination": bool, "reason": "一句话理由"}"""


def load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------- 用例执行 ----------------
RUN_ID = datetime.now().strftime("%H%M%S")


async def run_case(orch, case: dict) -> dict:
    """重放一轮/多轮对话，返回最后一次结果（每轮独立会话，避免跨轮污染）。"""
    last = None
    for msg in case["turns"]:
        t0 = time.monotonic()
        last = await orch.handle(f"eval-{RUN_ID}-{case['id']}", msg)
        last["latency"] = time.monotonic() - t0
    return last


def check_case(case: dict, result: dict) -> tuple[bool, list[str]]:
    """确定性检查：intent / action / emotion / must / must_not。"""
    fails: list[str] = []
    reply = result.get("reply", "")

    if case.get("expected_intent") and result.get("intent") != case["expected_intent"]:
        fails.append(f"intent={result.get('intent')} != {case['expected_intent']}")
    if case.get("expected_action") and result.get("action") != case["expected_action"]:
        fails.append(f"action={result.get('action')} != {case['expected_action']}")
    if case.get("expected_emotion") and result.get("emotion") != case["expected_emotion"]:
        fails.append(f"emotion={result.get('emotion')} != {case['expected_emotion']}")
    for s in case.get("must", []):
        if s not in reply:
            fails.append(f"缺少关键词: {s}")
    for s in case.get("must_not", []):
        if s in reply:
            fails.append(f"不应出现: {s}")
    return not fails, fails


async def judge_case(case: dict, result: dict) -> dict:
    """LLM-as-Judge：打分 + 幻觉判定。"""
    from src.llm.client import get_llm

    llm = get_llm()
    user_question = " | ".join(case["turns"])
    resp = await llm.chat(
        [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f"用户问题：{user_question}\n\n客服回复：{result.get('reply', '')}"},
        ],
        json_mode=True,
        max_tokens=300,
        temperature=0,
    )
    try:
        data = json.loads(resp.content.strip())
        return {
            "score": int(data.get("score", 0)),
            "hallucination": bool(data.get("hallucination", False)),
            "reason": data.get("reason", "")[:120],
        }
    except Exception:  # noqa: BLE001
        return {"score": 0, "hallucination": True, "reason": "judge解析失败"}


# ---------------- 检索评测 ----------------
async def retrieval_metrics() -> dict:
    from src.rag.retriever import hybrid_search

    cases = load_json(settings.EVAL_DIR / "retrieval_set.json")
    results = {"hybrid": [], "recall_all": 0, "mrr_all": 0.0, "ndcg_all": 0.0, "n": 0}
    for c in cases:
        hits = await hybrid_search(c["query"], top_k=10)
        hit_ids = [h["id"] for h in hits]
        relevant = set(c["relevant"])
        recall = len(relevant & set(hit_ids)) / len(relevant)
        mrr = 0.0
        for i, hid in enumerate(hit_ids):
            if hid in relevant:
                mrr = 1.0 / (i + 1)
                break
        dcg = 0.0
        for i, hid in enumerate(hit_ids[:5]):
            if hid in relevant:
                dcg += 1.0 / (i + 1)
        idcg = sum(1.0 / (i + 1) for i in range(min(len(relevant), 5)))
        ndcg = dcg / idcg if idcg else 0.0
        results["hybrid"].append({"id": c["id"], "recall@10": recall, "mrr": mrr, "ndcg@5": ndcg})
        results["n"] += 1
    results["recall_all"] = sum(r["recall@10"] for r in results["hybrid"]) / results["n"]
    results["mrr_all"] = sum(r["mrr"] for r in results["hybrid"]) / results["n"]
    results["ndcg_all"] = sum(r["ndcg@5"] for r in results["hybrid"]) / results["n"]
    return results


# ---------------- 情绪评测 ----------------
def emotion_metrics() -> dict:
    from src.emotion.detector import classify_rule

    cases = load_json(settings.EVAL_DIR / "emotion_set.json")
    correct = 0
    by_level = {"normal": [0, 0], "negative": [0, 0], "angry": [0, 0]}  # [correct, total]
    for c in cases:
        pred, _ = classify_rule(c["text"])
        by_level[c["expected"]][1] += 1
        if pred == c["expected"]:
            correct += 1
            by_level[c["expected"]][0] += 1
    return {
        "accuracy": correct / len(cases),
        "by_level": {k: {"correct": v[0], "total": v[1], "acc": v[0] / v[1] if v[1] else 0} for k, v in by_level.items()},
        "total": len(cases),
    }


# ---------------- 主流程 ----------------
async def run_eval(quick: int | None = None) -> dict:
    from src.agents.orchestrator import get_orchestrator
    from src.llm.client import close_llm
    from src.session.db import close_db

    orch = get_orchestrator()
    cases = load_json(settings.EVAL_DIR / "test_set.json")
    if quick:
        cases = cases[:quick]

    results = []
    for idx, case in enumerate(cases, 1):
        result = await run_case(orch, case)
        passed, fails = check_case(case, result)
        item = {
            "id": case["id"],
            "category": case["category"],
            "grade": case.get("grade", "auto"),
            "passed": passed,
            "fails": fails,
            "intent": result.get("intent"),
            "action": result.get("action"),
            "emotion": result.get("emotion"),
            "transferred": result.get("transferred"),
            "latency": round(result.get("latency", 0), 2),
            "sources": len(result.get("sources", [])),
        }
        if case.get("grade") == "judge":
            judge = await judge_case(case, result)
            item["judge_score"] = judge["score"]
            item["hallucination"] = judge["hallucination"]
            item["judge_reason"] = judge["reason"]
            if judge["score"] >= 4:
                item["passed"] = item["passed"] and True
            else:
                item["passed"] = False
                item["fails"].append(f"judge_score={judge['score']}")
        results.append(item)
        if idx % 10 == 0:
            print(f"  进度 {idx}/{len(cases)}", flush=True)

    await close_llm()
    await close_db()

    # ---------------- 汇总 ----------------
    total = len(results)
    passed_n = sum(1 for r in results if r["passed"])
    by_cat: dict[str, dict] = {}
    for r in results:
        cat = r["category"]
        d = by_cat.setdefault(cat, {"pass": 0, "total": 0})
        d["total"] += 1
        d["pass"] += 1 if r["passed"] else 0

    intent_ok = sum(1 for r in results if r["grade"] == "auto")
    judge_cases = [r for r in results if r["grade"] == "judge"]
    halluc_n = sum(1 for r in judge_cases if r.get("hallucination"))
    latencies = [r["latency"] for r in results if r["latency"] > 0]
    latencies.sort()

    # 转人工 P/R（emotion_transfer 类别）
    transfer_cases = [r for r in results if r["category"] == "emotion_transfer"]
    transfer_expected = {c["id"] for c in cases if c.get("expected_action") == "transfer"}
    tp = sum(1 for r in transfer_cases if r["transferred"] and r["id"] in transfer_expected)
    fp = sum(1 for r in transfer_cases if r["transferred"] and r["id"] not in transfer_expected)
    fn = sum(1 for r in transfer_cases if not r["transferred"] and r["id"] in transfer_expected)
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_cases": total,
        "problem_solved_rate": round(passed_n / total, 4) if total else 0,
        "passed": passed_n,
        "by_category": {k: {"pass": v["pass"], "total": v["total"], "rate": round(v["pass"] / v["total"], 4)} for k, v in by_cat.items()},
        "intent_auto_cases": intent_ok,
        "judge_cases": len(judge_cases),
        "hallucination_rate": round(halluc_n / len(judge_cases), 4) if judge_cases else 0,
        "transfer_precision": round(precision, 4),
        "transfer_recall": round(recall, 4),
        "latency_median_s": round(latencies[len(latencies) // 2], 2) if latencies else 0,
        "latency_p95_s": round(latencies[int(len(latencies) * 0.95) - 1], 2) if latencies else 0,
        "emotion": emotion_metrics(),
        "retrieval": await retrieval_metrics(),
        "cases": results,
    }
    return report


def render_markdown(report: dict) -> str:
    lines = [
        f"# 评测报告 {report['generated_at']}",
        "",
        "## 总览",
        f"| 指标 | 值 | 目标 |",
        f"|---|---|---|",
        f"| 问题解决率 | **{report['problem_solved_rate']*100:.1f}%** ({report['passed']}/{report['total_cases']}) | ≥75% |",
        f"| 幻觉率 (Judge) | **{report['hallucination_rate']*100:.1f}%** | ≤5% |",
        f"| 转人工 Precision | **{report['transfer_precision']*100:.1f}%** | ≥85% |",
        f"| 转人工 Recall | **{report['transfer_recall']*100:.1f}%** | ≥90% |",
        f"| 中位延迟 | **{report['latency_median_s']}s** | <3s |",
        f"| P95 延迟 | **{report['latency_p95_s']}s** | <8s |",
        "",
        "## 分场景",
        "| 场景 | 通过 | 通过率 |",
        "|---|---|---|",
    ]
    for cat, v in report["by_category"].items():
        lines.append(f"| {cat} | {v['pass']}/{v['total']} | {v['rate']*100:.1f}% |")
    emo = report["emotion"]
    lines += [
        "",
        "## 情绪识别",
        f"| 等级 | 准确率 |",
        f"|---|---|",
    ]
    for k, v in emo["by_level"].items():
        lines.append(f"| {k} | {v['acc']*100:.1f}% ({v['correct']}/{v['total']}) |")
    lines.append(f"| **总体** | **{emo['accuracy']*100:.1f}%** |")
    ret = report["retrieval"]
    lines += [
        "",
        "## 检索质量（混合检索）",
        f"| 指标 | 值 | 目标 |",
        f"|---|---|---|",
        f"| Recall@10 | {ret['recall_all']*100:.1f}% | ≥85% |",
        f"| MRR@10 | {ret['mrr_all']:.3f} | ≥0.7 |",
        f"| NDCG@5 | {ret['ndcg_all']:.3f} | ≥0.75 |",
        "",
        "## 未通过用例",
    ]
    fails = [c for c in report["cases"] if not c["passed"]]
    if not fails:
        lines.append("无 🎉")
    for c in fails:
        lines.append(f"- **{c['id']}** ({c['category']}) intent={c['intent']} action={c['action']}: {'; '.join(c['fails'])}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", type=int, default=None, help="只跑前 N 条")
    args = parser.parse_args()

    settings.ensure_dirs()
    report = asyncio.run(run_eval(args.quick))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = settings.REPORTS_DIR / f"{ts}_report.json"
    md_path = settings.REPORTS_DIR / f"{ts}_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"✅ 评测完成，报告已保存：\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
