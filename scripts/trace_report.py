#!/usr/bin/env python3
"""自研可观测性：追踪报告生成器。

读取 data/traces/traces.jsonl（自研 JSONL 追踪器产出），生成：
- docs/可观测性报告.md：请求量/延迟分布/意图/情绪/动作分布/最慢 span 分析
- data/traces/traces.html：可视化查看器（浏览器打开）

运行：python -m scripts.trace_report [--last N] [--html]
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from config import settings


def load_traces(path: Path, last: int | None = None) -> list[dict]:
    traces = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if last:
        traces = traces[-last:]
    return traces


def _p95(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[int(len(s) * 0.95) - 1]


def build_markdown(traces: list[dict]) -> str:
    n = len(traces)
    if n == 0:
        return "# 可观测性报告\n\n暂无追踪数据。先运行一次对话（`python -m scripts.trace_report` 前请先调用 API）。"
    durs = [t["duration_ms"] for t in traces]
    llms = [t.get("llm_calls", 0) for t in traces]
    intent_c = Counter(t.get("intent", "-") for t in traces)
    emotion_c = Counter(t.get("emotion", "-") for t in traces)
    action_c = Counter(t.get("action", "-") for t in traces)
    # span 分析：各 span 平均耗时（聚合跨 trace）
    span_stats: dict[str, list[float]] = {}
    for t in traces:
        for s in t.get("spans", []):
            span_stats.setdefault(s["name"], []).append(s.get("duration_ms", 0))
    span_rows = sorted(
        ((name, statistics.mean(v), max(v)) for name, v in span_stats.items()),
        key=lambda x: -x[1],
    )

    lines = [
        f"# 可观测性报告（自研 JSONL 追踪）",
        "",
        f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S} ｜ 样本 {n} 条 ｜ 数据源 `data/traces/traces.jsonl`",
        "",
        "## 总览",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 请求数 | {n} |",
        f"| 平均耗时 | {statistics.mean(durs)/1000:.2f}s |",
        f"| 中位耗时 | {statistics.median(durs)/1000:.2f}s |",
        f"| P95 耗时 | {_p95(durs)/1000:.2f}s |",
        f"| 平均 LLM 调用/请求 | {statistics.mean(llms):.1f} |",
        "",
        "## 意图分布",
        "| 意图 | 次数 | 占比 |",
        "|------|------|------|",
    ]
    for k, v in intent_c.most_common():
        lines.append(f"| {k} | {v} | {v/n*100:.1f}% |")
    lines += ["", "## 情绪分布"]
    for k, v in emotion_c.most_common():
        lines.append(f"- {k}: {v}（{v/n*100:.1f}%）")
    lines += ["", "## 动作分布"]
    for k, v in action_c.most_common():
        lines.append(f"- {k}: {v}（{v/n*100:.1f}%）")
    lines += ["", "## 节点耗时分析（平均 / 峰值）", "| 节点 | 平均 ms | 峰值 ms |", "|------|--------|--------|"]
    for name, avg, mx in span_rows:
        lines.append(f"| {name} | {avg:.0f} | {mx:.0f} |")
    lines += ["", "## 最慢请求 Top5"]
    for t in sorted(traces, key=lambda x: -x["duration_ms"])[:5]:
        lines.append(
            f"- `{t['trace_id']}` {t['duration_ms']/1000:.2f}s｜{t.get('intent','-')}/{t.get('action','-')}｜"
            f"LLM×{t.get('llm_calls',0)}｜{t.get('message','')[:30]}"
        )
    lines += ["", "_复现：`python -m scripts.trace_report`_", ""]
    return "\n".join(lines)


def build_html(traces: list[dict]) -> str:
    rows = []
    for t in reversed(traces[-200:]):  # 最新 200 条
        spans = " → ".join(f"{s['name']}({s['duration_ms']:.0f}ms)" for s in t.get("spans", []))
        rows.append(
            f"<tr><td>{t.get('ts','')}</td><td>{t.get('session_id','')[:8]}</td>"
            f"<td>{t.get('intent','-')}</td><td>{t.get('emotion','-')}</td>"
            f"<td>{t.get('action','-')}</td><td>{t['duration_ms']/1000:.2f}s</td>"
            f"<td>×{t.get('llm_calls',0)}</td><td style='font-size:.75rem;color:#8892b0'>{spans}</td>"
            f"<td style='font-size:.75rem'>{t.get('message','')[:40]}</td></tr>"
        )
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>悦己客服 · 可观测性看板</title>
<style>
body{{background:#0b1020;color:#e8ecf5;font-family:-apple-system,'Microsoft YaHei',sans-serif;padding:24px;}}
h1{{font-size:1.3rem}} table{{border-collapse:collapse;width:100%;font-size:.85rem}}
th,td{{border:1px solid rgba(255,255,255,.12);padding:6px 10px;text-align:left}}
th{{background:rgba(100,255,218,.12);color:#64ffda}} tr:nth-child(even){{background:rgba(255,255,255,.03)}}
</style></head><body><h1>💄 悦己美妆客服 · 请求追踪看板（{len(traces)} 条）</h1>
<table><tr><th>时间</th><th>会话</th><th>意图</th><th>情绪</th><th>动作</th><th>耗时</th><th>LLM</th><th>节点链路</th><th>消息</th></tr>
{''.join(rows)}</table></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=None, help="只分析最近 N 条")
    parser.add_argument("--html", action="store_true", help="同时生成 HTML 看板")
    args = parser.parse_args()

    traces = load_traces(settings.BASE_DIR / "data" / "traces" / "traces.jsonl", args.last)
    md = build_markdown(traces)
    md_path = settings.BASE_DIR / "docs" / "可观测性报告.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    print(md)
    print(f"✅ 报告已保存：{md_path}")
    if args.html:
        html_path = settings.BASE_DIR / "data" / "traces" / "traces.html"
        html_path.write_text(build_html(traces), encoding="utf-8")
        print(f"✅ HTML 看板：{html_path}")


if __name__ == "__main__":
    main()
