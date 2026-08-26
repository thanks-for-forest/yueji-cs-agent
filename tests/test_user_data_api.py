"""用户数据接口测试（/api/user/sessions、/api/orders/me）。"""
import json
import urllib.request


def _call(path, method="GET", data=None, headers=None, timeout=30):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=body, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.request.HTTPError as e:
        return e.code, json.loads(e.read())


def test_orders_me_requires_login():
    status, _ = _call("/api/orders/me")
    assert status == 401


def test_user_sessions_and_orders_bound_to_account():
    status, d = _call("/api/auth/login", method="POST", data={"username": "demo1", "password": "demo123"})
    assert status == 200
    token = d["token"]
    headers = {"X-Auth-Token": token}

    status, data = _call("/api/user/sessions", headers=headers)
    assert status == 200 and data["user_id"] == "U001"
    assert isinstance(data["sessions"], list)

    status, data = _call("/api/orders/me", headers=headers)
    assert status == 200 and data["user_id"] == "U001"
    oids = {o["order_id"] for o in data["orders"]}
    assert "O202600001" in oids  # demo1 绑定 U001，只能看到 U001 的订单
    assert all(o["order_id"] not in ("O202600005",) for o in data["orders"])  # 无他人订单
