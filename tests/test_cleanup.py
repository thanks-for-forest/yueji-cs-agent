"""scripts/cleanup 清理脚本测试（离线：临时 DB 与临时目录，全部 DB 操作在单个事件循环内）。"""
import asyncio
from datetime import datetime, timedelta

from config import settings

_KB_LOG_TABLE = (
    "CREATE TABLE IF NOT EXISTS kb_query_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "query TEXT, mode TEXT, top_k INTEGER, hit_count INTEGER, top_score REAL, created_at TEXT)"
)
_TOKEN_TABLE = (
    "CREATE TABLE IF NOT EXISTS auth_tokens "
    "(token TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, expires_at TEXT)"
)


def test_cleanup_removes_old_log_and_keeps_recent(tmp_path, monkeypatch):
    """过期检索日志被清理，近期日志保留；dry-run 不删除。"""
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "test.db")
    from scripts import cleanup

    from src.session.db import close_db, get_conn, init_db

    async def t():
        await init_db()
        conn = await get_conn()
        await conn.execute(_KB_LOG_TABLE)
        old = (datetime.now() - timedelta(days=60)).isoformat(timespec="seconds")
        recent = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
        for ts in (old, recent):
            await conn.execute(
                "INSERT INTO kb_query_log (query, mode, top_k, hit_count, top_score, created_at) "
                "VALUES (?,?,?,?,?,?)", ("旧日志" if ts == old else "近期日志", "bm25", 5, 1, 0.5, ts))
        await conn.commit()
        await close_db()

        r = await cleanup.run_cleanup(dry_run=True, kb_days=30)
        assert r["kb_query_log"] == 1 and r["dry_run"] is True
        r2 = await cleanup.run_cleanup(dry_run=False, kb_days=30)
        assert r2["kb_query_log"] == 1

        await init_db()
        conn = await get_conn()
        cur = await conn.execute("SELECT COUNT(*) c FROM kb_query_log")
        assert (await cur.fetchone())["c"] == 1
        await close_db()

    asyncio.run(t())


def test_cleanup_keeps_latest_files(tmp_path, monkeypatch):
    """traces/reports 按保留数清理。"""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "EVAL_DIR", tmp_path / "eval")
    traces = settings.DATA_DIR / "traces"
    reports = settings.EVAL_DIR / "reports"
    traces.mkdir(parents=True)
    reports.mkdir(parents=True)
    for i in range(5):
        (traces / f"t{i}.jsonl").write_text("{}", encoding="utf-8")
        (reports / f"r{i}.json").write_text("{}", encoding="utf-8")
    from scripts import cleanup

    r = asyncio.run(cleanup.run_cleanup(dry_run=False, traces_keep=2, reports_keep=3))
    assert r["traces_files"] == 3 and r["eval_reports"] == 2
    assert len(list(traces.glob("*.jsonl"))) == 2
    assert len(list(reports.glob("*"))) == 3


def test_cleanup_expired_tokens(tmp_path, monkeypatch):
    """过期 auth_tokens 被清理，有效 token 保留。"""
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "test.db")
    from scripts import cleanup

    from src.session.db import close_db, get_conn, init_db

    async def t():
        await init_db()
        conn = await get_conn()
        await conn.execute(_TOKEN_TABLE)
        now = datetime.now().isoformat(timespec="seconds")
        old = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        await conn.execute("INSERT INTO auth_tokens VALUES ('expired', 'U1', ?, ?)", (old, old))
        await conn.execute("INSERT INTO auth_tokens VALUES ('valid', 'U1', ?, ?)", (now, now))
        await conn.commit()
        await close_db()

        r = await cleanup.run_cleanup(dry_run=False)
        assert r["expired_auth_tokens"] == 1

        await init_db()
        conn = await get_conn()
        cur = await conn.execute("SELECT COUNT(*) c FROM auth_tokens")
        assert (await cur.fetchone())["c"] == 1
        await close_db()

    asyncio.run(t())
