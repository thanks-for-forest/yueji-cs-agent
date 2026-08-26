"""运维清理脚本：检索日志 / 过期登录令牌 / 追踪文件 / 评测报告 的保留期管理。

用法：
  python -m scripts.cleanup                    # 按默认保留期清理
  python -m scripts.cleanup --dry-run          # 只统计不删除
  python -m scripts.cleanup --kb-days 7 --traces-keep 10 --reports-keep 5
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402

DEFAULT_KB_LOG_DAYS = 30     # 检索命中测试日志保留天数
DEFAULT_TRACES_KEEP = 30     # data/traces/*.jsonl 保留最新 N 个
DEFAULT_REPORTS_KEEP = 10    # eval/reports/* 保留最新 N 份


async def _clean_db(kb_days: int, dry_run: bool) -> dict:
    """清理 kb_query_log（按创建时间）与已过期 auth_tokens（表缺失时忽略）。"""
    from src.session.db import close_db, get_conn, init_db

    out: dict[str, int] = {"kb_query_log": 0, "expired_auth_tokens": 0}
    await init_db()
    conn = await get_conn()
    # 1) 检索日志
    cutoff = (datetime.now() - timedelta(days=kb_days)).isoformat(timespec="seconds")
    try:
        cur = await conn.execute("SELECT COUNT(*) c FROM kb_query_log WHERE created_at < ?", (cutoff,))
        n = (await cur.fetchone())["c"]
        out["kb_query_log"] = n
        if n and not dry_run:
            await conn.execute("DELETE FROM kb_query_log WHERE created_at < ?", (cutoff,))
            await conn.commit()
    except Exception:  # noqa: BLE001  （kb_query_log 表不存在时忽略）
        pass
    # 2) 过期令牌
    now = datetime.now().isoformat(timespec="seconds")
    try:
        cur = await conn.execute("SELECT COUNT(*) c FROM auth_tokens WHERE expires_at < ?", (now,))
        m = (await cur.fetchone())["c"]
        out["expired_auth_tokens"] = m
        if m and not dry_run:
            await conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now,))
            await conn.commit()
    except Exception:  # noqa: BLE001  （auth_tokens 表不存在时忽略）
        pass
    await close_db()
    return out


def _clean_files(directory: Path, keep: int, dry_run: bool, pattern: str) -> int:
    """按修改时间保留最新 keep 个文件，其余删除。返回处理数量。"""
    if not directory.exists():
        return 0
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    stale = files[keep:]
    if stale and not dry_run:
        for p in stale:
            p.unlink(missing_ok=True)
    return len(stale)


async def run_cleanup(dry_run: bool = False, kb_days: int = DEFAULT_KB_LOG_DAYS,
                      traces_keep: int = DEFAULT_TRACES_KEEP,
                      reports_keep: int = DEFAULT_REPORTS_KEEP) -> dict:
    """执行全部清理，返回各分区清理数量。"""
    db = await _clean_db(kb_days, dry_run)
    traces = _clean_files(settings.DATA_DIR / "traces", traces_keep, dry_run, "*.jsonl")
    reports = _clean_files(settings.EVAL_DIR / "reports", reports_keep, dry_run, "*")
    return {**db, "traces_files": traces, "eval_reports": reports, "dry_run": dry_run}


def main() -> None:
    ap = argparse.ArgumentParser(description="运维清理：检索日志/过期令牌/追踪/评测报告")
    ap.add_argument("--dry-run", action="store_true", help="只统计不删除")
    ap.add_argument("--kb-days", type=int, default=DEFAULT_KB_LOG_DAYS, help="检索日志保留天数")
    ap.add_argument("--traces-keep", type=int, default=DEFAULT_TRACES_KEEP, help="追踪文件保留数")
    ap.add_argument("--reports-keep", type=int, default=DEFAULT_REPORTS_KEEP, help="评测报告保留数")
    args = ap.parse_args()

    result = asyncio.run(run_cleanup(args.dry_run, args.kb_days, args.traces_keep, args.reports_keep))
    tag = "（dry-run，未删除）" if result["dry_run"] else ""
    print("清理汇总%s：" % tag)
    for k, v in result.items():
        if k != "dry_run":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
