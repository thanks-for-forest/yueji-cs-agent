"""知识库管理权限门禁测试（X-Admin-Token + 审计留痕）。"""
import asyncio
import json

import httpx


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
