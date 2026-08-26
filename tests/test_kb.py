"""知识库管理（KB 上传/审核/回滚）测试。"""
import asyncio

import pytest

from src.kb.parser import chunk_text, parse_document
from src.kb.service import active_kb_chunks, approve_doc, rollback_doc, upload_document
from src.rag.retriever import retrieve_context
from src.session.db import close_db, init_db


@pytest.fixture(scope="module", autouse=True)
def _db():
    asyncio.run(init_db())
    yield
    asyncio.run(close_db())


def test_parse_md():
    text = parse_document("a.md", "# 标题\n正文内容".encode())
    assert "标题" in text and "正文" in text


def test_chunk_text_short():
    cs = chunk_text("悦己618大促全场八折。满300减100。")
    assert len(cs) == 1


def test_chunk_text_long_multiple():
    text = "第一段内容。" * 100  # 足够长
    cs = chunk_text(text, chunk_size=200, overlap=40)
    assert len(cs) > 1
    assert all(c for c in cs)


def test_parse_unsupported_ext():
    with pytest.raises(ValueError):
        parse_document("a.xlsx", b"x")


def test_kb_flow_upload_approve_rollback():
    """端到端：上传待审核 → 审核后可检索 → 回滚后失效。"""

    async def t():
        await init_db()
        md = "# 悦己 618 大促活动规则\n悦己美妆 618 大促期间全场 8 折起，满 300 减 100。"
        doc = await upload_document("618规则.md", md.encode(), category="活动")
        assert doc["status"] == "pending"
        assert doc["chunk_count"] >= 1

        # 审核前：不应命中 KB 块
        hits = await retrieve_context("618大促有满减吗")
        assert not any(h["id"].startswith("kb-") for h in hits)

        # 审核后：应命中 KB 块
        await approve_doc(doc["doc_id"])
        hits = await retrieve_context("618大促有满减吗")
        assert any(h["id"].startswith("kb-") for h in hits)

        # 回滚后：应失效
        await rollback_doc(doc["doc_id"])
        hits = await retrieve_context("618大促有满减吗")
        assert not any(h["id"].startswith("kb-") for h in hits)
        from src.llm.client import close_llm

        await close_llm()
        await close_db()

    asyncio.run(t())
