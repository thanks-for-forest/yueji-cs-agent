"""知识库管理权限门禁测试（X-Admin-Token + 审计留痕）。

依赖运行中的后端服务（127.0.0.1:8000），整体标记 integration，CI 中跳过。
"""
import asyncio
import json

import httpx
import pytest

pytestmark = pytest.mark.integration


def _post(path, data=None, token="", headers=None):
    import urllib.request

    body = json.dumps(data).encode() if data is not None else b"{}"
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Admin-Token"] = token
    if headers:
        h.update(headers)
    req = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=body, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read())
    except urllib.request.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(path, token="admin123456"):
    import urllib.request

    req = urllib.request.Request(f"http://127.0.0.1:8000{path}",
                                 headers={"X-Admin-Token": token})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read())
    except urllib.request.HTTPError as e:
        return e.code, json.loads(e.read())


def test_kb_endpoints_require_admin_token():
    """无令牌/错误令牌 → 403。"""
    status, _ = _post("/api/kb/verify", token="")
    assert status == 403
    status, _ = _post("/api/kb/verify", token="wrong-token")
    assert status == 403
    status, body = _post("/api/kb/verify", token="admin123456")
    assert status == 200 and body["ok"] is True


def test_kb_upload_records_operator():
    """上传记录操作人（审计留痕）。"""
    import urllib.request

    # multipart 上传带管理员头
    boundary = "----kb-test"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audit.md\"\r\n"
        "Content-Type: text/markdown\r\n\r\n# 审计测试文档\n这是一段测试内容。\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"category\"\r\n\r\n测试\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/kb/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "X-Admin-Token": "admin123456", "X-Admin-Name": "U001"},
    )
    r = urllib.request.urlopen(req, timeout=60)
    doc = json.loads(r.read())
    assert doc["status"] == "pending"

    # 列表接口应含 created_by=U001（GET）
    import urllib.request as ur

    req = ur.Request("http://127.0.0.1:8000/api/kb/docs", headers={"X-Admin-Token": "admin123456"})
    data = json.loads(ur.urlopen(req, timeout=30).read())
    mine = [d for d in data["docs"] if d["doc_id"] == doc["doc_id"]]
    assert mine and mine[0]["created_by"] == "U001"
    # 清理
    _delete(doc["doc_id"])


def _delete(doc_id: str) -> None:
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:8000/api/kb/docs/{doc_id}",
        method="DELETE",
        headers={"X-Admin-Token": "admin123456"},
    )
    urllib.request.urlopen(req, timeout=30)


def _upload(files: list[tuple[str, str]], category: str = "", chunk_size: int = 0, overlap: int = -1) -> dict:
    """multipart 上传（单/多文件），返回响应 json。"""
    import urllib.request

    boundary = "----kb-multi"
    parts = []
    for fn, content in files:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{fn}\"\r\n"
            "Content-Type: text/plain\r\n\r\n".encode() + content.encode() + b"\r\n"
        )
    for k, v in (("category", category), ("chunk_size", str(chunk_size)), ("overlap", str(overlap))):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/kb/upload-batch",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "X-Admin-Token": "admin123456"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def test_kb_batch_upload_and_strategy():
    """批量上传多文件：分类与分块策略（Form 字段）生效，错误文件被隔离。"""
    res = _upload(
        [("a.md", "# A 文档\n悦己测试内容。" * 20), ("bad.rtf", "不支持的格式")],
        category="集成测试", chunk_size=180, overlap=25,
    )
    assert res["ok"] == 1 and res["failed"] == 1
    assert res["chunk_size"] == 180 and res["overlap"] == 25
    assert res["results"][0]["filename"] == "a.md"
    assert "bad.rtf" in res["errors"][0]["filename"]
    # 分类落库
    status, body = _get("/api/kb/docs")
    mine = [d for d in body["docs"] if d["filename"] == "a.md"]
    assert mine and mine[0]["category"] == "集成测试"
    # 清理
    _cleanup([d["doc_id"] for d in body["docs"] if d["category"] == "集成测试"])


def _cleanup(doc_ids: list[str]) -> None:
    if not doc_ids:
        return
    status, _ = _post("/api/kb/docs/batch-delete", data={"doc_ids": doc_ids}, token="admin123456")
    assert status == 200


def test_kb_index_status_and_rechunk():
    """索引健康 + 重新分块（按策略重切）。"""
    status, body = _get("/api/kb/index-status")
    assert status == 200
    assert body["healthy"] is True
    assert body["counts"]["chunks_json"] == body["counts"]["vectors_npz"] == 347

    res = _upload([("rc.md", "# 重分块\n" + "悦己美妆精华。" * 150)], category="")
    doc_id = res["results"][0]["doc_id"]
    status, body = _post(f"/api/kb/docs/{doc_id}/rechunk", data={"chunk_size": 120, "overlap": 20},
                         token="admin123456")
    assert status == 200
    assert body["chunk_count"] > 1 and body["chunk_size"] == 120
    _cleanup([doc_id])


def test_kb_query_test_modes_and_stats():
    """命中测试四种模式 + 检索日志统计。"""
    for mode in ("dense_first", "rrf", "dense", "bm25"):
        status, body = _post("/api/kb/query-test",
                             data={"query": "氨基酸洗面奶多少钱", "top_k": 3, "mode": mode},
                             token="admin123456")
        assert status == 200
        assert isinstance(body["hits"], list)
    status, stats = _get("/api/kb/query-stats?limit=10")
    assert status == 200
    assert stats["total"] >= 4
    assert any(r["mode"] == "bm25" for r in stats["recent"])


def test_kb_export_and_categories():
    """导出 json/md + 分类清单。"""
    status, body = _get("/api/kb/export?fmt=json")
    assert status == 200 and body["filename"].endswith(".json")
    assert "base_chunks" in body["content"]
    status, body = _get("/api/kb/export?fmt=md")
    assert status == 200 and body["filename"].endswith(".md")
    assert "悦己" in body["content"]
    status, body = _get("/api/kb/categories")
    assert status == 200
    assert "活动" in body["categories"]  # 预置分类
