"""存取歷史：使用者透過 /auth/*（user_session）、/mcp（oauth/pat）、/api/*（mask_key）
存取時都要留一筆 access_logs 紀錄，管理員能在 /api/admin/access-logs 查詢／匯出。"""

import asyncio
import csv
import io

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _user_login(client, email, password):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_user_session_access_is_logged(client, admin_token, active_user):
    email, password = active_user
    user_token = _user_login(client, email, password)
    res = client.get("/auth/me", headers={"Authorization": f"Bearer {user_token}"})
    assert res.status_code == 200

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    logs = client.get("/api/admin/access-logs", headers=admin_headers, params={"email": email}).json()
    assert any(l["path"] == "/auth/me" and l["auth_method"] == "user_session" for l in logs)


def test_mask_key_access_is_logged(client, admin_token, active_user):
    email, password = active_user
    user_token = _user_login(client, email, password)
    res = client.post("/auth/mask-key", headers={"Authorization": f"Bearer {user_token}"})
    mask_key = res.json()["mask_key"]

    res = client.get("/api/models", headers={"Authorization": f"Bearer {mask_key}"})
    assert res.status_code == 200

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    logs = client.get("/api/admin/access-logs", headers=admin_headers, params={"email": email}).json()
    assert any(l["path"] == "/api/models" and l["auth_method"] == "mask_key" for l in logs)


async def _mcp_call(live_server, token):
    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.list_tools()


def test_mcp_oauth_access_is_logged(client, admin_token, mcp_access_token, live_server):
    access_token, _pbi_config_id, user_id = mcp_access_token
    asyncio.run(_mcp_call(live_server, access_token))

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    users_res = client.get("/api/admin/users", headers=admin_headers)
    email = next(u["email"] for u in users_res.json() if u["id"] == user_id)

    logs = client.get(
        "/api/admin/access-logs", headers=admin_headers, params={"email": email, "auth_method": "oauth"},
    ).json()
    matches = [l for l in logs if l["path"] == "/mcp" and l["auth_method"] == "oauth"]
    assert matches
    # /mcp 的驗證點沒有 Request 物件，IP/method 是從 main.py 的 ASGI wrapper 透過
    # contextvar 補進來的（見 app/access_log.py），這裡要確認真的有補到，不是 null。
    assert matches[0]["ip_address"] is not None
    assert matches[0]["method"] is not None


def test_pat_access_is_logged(client, admin_token, active_user, live_server):
    email, password = active_user
    user_token = _user_login(client, email, password)
    res = client.post("/auth/mcp-tokens", headers={"Authorization": f"Bearer {user_token}"}, json={"name": "x"})
    pat = res.json()["token"]

    asyncio.run(_mcp_call(live_server, pat))

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    logs = client.get(
        "/api/admin/access-logs", headers=admin_headers, params={"email": email, "auth_method": "pat"},
    ).json()
    matches = [l for l in logs if l["path"] == "/mcp" and l["auth_method"] == "pat"]
    assert matches
    assert matches[0]["ip_address"] is not None
    assert matches[0]["method"] is not None


def test_access_logs_export_csv(client, admin_token, active_user):
    email, password = active_user
    user_token = _user_login(client, email, password)
    client.get("/auth/me", headers={"Authorization": f"Bearer {user_token}"})

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.get("/api/admin/access-logs/export", headers=admin_headers, params={"email": email})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")

    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0] == ["created_at", "email", "auth_method", "method", "path", "ip_address"]
    assert any(row[1] == email for row in rows[1:])
