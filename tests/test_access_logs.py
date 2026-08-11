"""存取歷史：使用者透過 /auth/*（user_session）、/mcp（oauth/pat）、/api/*（mask_key）
存取時都要留一筆 access_logs 紀錄，管理員能在 /api/admin/access-logs 查詢／匯出。"""

import asyncio
import csv
import io

import pytest
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


async def _mcp_call_tool(live_server, token, tool_name, arguments):
    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.call_tool(tool_name, arguments)


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


def test_mcp_tool_invocation_is_logged_with_tool_name(client, admin_token, mcp_access_token, live_server):
    """實際呼叫一個 tool（list_models）之後，除了 verify_token 那邊記的通用 "/mcp"，
    還要多一筆更精確的 "/mcp/list_models"，讓管理員能看出「哪個功能被觸發」。"""
    access_token, _pbi_config_id, user_id = mcp_access_token
    asyncio.run(_mcp_call_tool(live_server, access_token, "list_models", {}))

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    users_res = client.get("/api/admin/users", headers=admin_headers)
    email = next(u["email"] for u in users_res.json() if u["id"] == user_id)

    logs = client.get("/api/admin/access-logs", headers=admin_headers, params={"email": email}).json()
    assert any(l["path"] == "/mcp" for l in logs)
    tool_matches = [l for l in logs if l["path"] == "/mcp/list_models"]
    assert tool_matches
    assert tool_matches[0]["auth_method"] == "oauth"
    assert tool_matches[0]["ip_address"] is not None


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
    assert rows[0] == ["created_at", "email", "auth_method", "method", "path", "ip_address", "detail"]
    assert any(row[1] == email for row in rows[1:])


@pytest.mark.anyio
async def test_tool_access_records_target_pbi_config(client, admin_token, mcp_access_token, live_server):
    """get_model_detail／get_query_ticket 要把「這次針對哪個 PBI 設定」記進 detail。

    查詢實際上是在 client 端直接打 Power BI 的，server 這邊唯一留得下的線索就是這筆
    紀錄；要跟 Power BI 自己的 activity log 對起來還原「誰查了哪個模型」就得有這欄。
    """
    access_token, pbi_config_id, user_id = mcp_access_token
    await _mcp_call_tool(live_server, access_token, "get_model_detail",
                         {"pbi_config_id": pbi_config_id})

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    users_res = client.get("/api/admin/users", headers=admin_headers)
    email = next(u["email"] for u in users_res.json() if u["id"] == user_id)

    logs = client.get("/api/admin/access-logs", headers=admin_headers, params={"email": email}).json()
    detail_row = next(l for l in logs if l["path"] == "/mcp/get_model_detail")
    assert detail_row["detail"] == pbi_config_id

    # list_models 沒有特定對象，detail 應該留空而不是硬塞值
    await _mcp_call_tool(live_server, access_token, "list_models", {})
    logs = client.get("/api/admin/access-logs", headers=admin_headers, params={"email": email}).json()
    list_row = next(l for l in logs if l["path"] == "/mcp/list_models")
    assert list_row["detail"] is None
