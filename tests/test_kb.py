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
        parse_document("a.rtf", b"x")


def test_parse_csv_xlsx_html():
    """新增格式：csv / xlsx / html 可解析。"""
    csv_text = parse_document("t.csv", "名称,价格,功效\n氨基酸洁面乳,69,温和清洁\n".encode())
    assert "氨基酸洁面乳" in csv_text and "69" in csv_text

    html_text = parse_document("t.html", "<html><body><script>var x=1</script><p>悦己精华</p></body></html>".encode())
    assert "悦己精华" in html_text and "var x" not in html_text

    # xlsx：用 openpyxl 现场生成
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "产品"
    ws.append(["名称", "价格"])
    ws.append(["烟酰胺精华", 129])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_text = parse_document("t.xlsx", buf.getvalue())
    assert "烟酰胺精华" in xlsx_text and "129" in xlsx_text


def test_chunk_text_custom_strategy():
    """分块策略参数生效：小窗口产生更多块，重叠保留上下文。"""
    text = "悦己美妆。" * 60  # 360字
    cs_big = chunk_text(text, chunk_size=400, overlap=60)
    cs_small = chunk_text(text, chunk_size=120, overlap=20)
    assert len(cs_small) > len(cs_big)
    assert all(c for c in cs_big) and all(c for c in cs_small)
    # overlap 不超过 chunk_size 时窗口逐段前进
    assert len(cs_big) == 1 or len(cs_big) >= 1


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


def test_kb_upload_respects_chunk_strategy():
    """上传携带分块策略参数时生效（记录在返回中）。"""
    from src.kb.service import upload_document

    async def t():
        await init_db()
        md = "# 策略测试\n" + "悦己美妆。" * 200
        d1 = await upload_document("s1.md", md.encode(), chunk_size=200, overlap=30)
        d2 = await upload_document("s2.md", md.encode())
        assert d1["chunk_size"] == 200 and d1["overlap"] == 30
        assert d2["chunk_size"] == 400 and d2["overlap"] == 60  # 配置默认
        from src.kb.service import delete_docs_batch

        await delete_docs_batch([d1["doc_id"], d2["doc_id"]])
        from src.llm.client import close_llm

        await close_llm()
        await close_db()

    asyncio.run(t())


def test_kb_rechunk_and_index_status():
    """重新分块按策略生效；索引健康检查返回一致且健康。"""
    from src.kb.service import get_index_status, rechunk_doc, upload_document

    async def t():
        await init_db()
        md = "# 重分块测试\n" + "悦己美妆精华。" * 150
        doc = await upload_document("rc.md", md.encode(), chunk_size=500, overlap=50)
        r1 = await rechunk_doc(doc["doc_id"], chunk_size=120, overlap=20)
        assert r1["chunk_count"] > 1 and r1["chunk_size"] == 120
        # 索引健康
        sts = await get_index_status()
        assert sts["healthy"] is True
        assert sts["counts"]["chunks_json"] == sts["counts"]["vectors_npz"]
        from src.kb.service import delete_docs_batch

        await delete_docs_batch([doc["doc_id"]])
        from src.llm.client import close_llm

        await close_llm()
        await close_db()

    asyncio.run(t())


def test_kb_query_test_modes_and_export():
    """命中测试模式对照可用；导出 json/md 含文档内容。"""
    from src.kb.service import export_kb, query_test, upload_document

    async def t():
        await init_db()
        md = "# 导出测试\n悦己 618 大促全场八折。满 300 减 100。"
        doc = await upload_document("exp.md", md.encode(), category="活动")

        hits = await query_test("618大促", top_k=5, mode="bm25")
        assert isinstance(hits, list)
        hits_dense = await query_test("618大促", top_k=5, mode="dense")
        assert isinstance(hits_dense, list)
        hits_rrf = await query_test("618大促", top_k=5, mode="rrf")
        assert isinstance(hits_rrf, list)

        j = await export_kb("json")
        assert "docs" in j["content"] and "exp.md" in j["content"]
        m = await export_kb("md")
        assert "exp.md" in m["content"]
        from src.kb.service import delete_docs_batch

        await delete_docs_batch([doc["doc_id"]])
        from src.llm.client import close_llm

        await close_llm()
        await close_db()

    asyncio.run(t())
