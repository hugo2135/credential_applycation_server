"""MCP Personal Access Token：給不支援完整 OAuth 流程的 MCP client
（例如 Antigravity）用的固定 Bearer token，使用者自助在 /auth/mcp-tokens 產生。"""

import os

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _user_login(client, email, password):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_create_list_delete_mcp_token(client, active_user):
    email, password = active_user
    user_token = _user_login(client, email, password)
    headers = {"Authorization": f"Bearer {user_token}"}

    res = client.post("/auth/mcp-tokens", headers=headers, json={"name": "Antigravity"})
    assert res.status_code == 201
    body = res.json()
    assert body["token"].startswith("pat_")
    assert body["name"] == "Antigravity"
    token_id = body["id"]

    res = client.get("/auth/mcp-tokens", headers=headers)
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["id"] == token_id
    assert rows[0]["name"] == "Antigravity"
    assert "token" not in rows[0]  # 明文不應該在列表裡再次出現

    res = client.delete(f"/auth/mcp-tokens/{token_id}", headers=headers)
    assert res.status_code == 204

    res = client.get("/auth/mcp-tokens", headers=headers)
    assert res.json() == []


def test_cannot_delete_other_users_token(client, active_user):
    email, password = active_user
    user_token = _user_login(client, email, password)
    headers = {"Authorization": f"Bearer {user_token}"}
    res = client.post("/auth/mcp-tokens", headers=headers, json={"name": "x"})
    token_id = res.json()["id"]

    # 另一個使用者
    other_email = f"other-{email}"
    client.post("/auth/register", json={"email": other_email, "password": "testpass123"})
    admin_res = client.post("/api/admin/login", json={"secret": os.environ["ADMIN_SECRET"]})
    admin_headers = {"Authorization": f"Bearer {admin_res.json()['access_token']}"}
    client.patch("/api/admin/users/activate", headers=admin_headers,
                 json={"email": other_email, "is_active": True})
    other_token = _user_login(client, other_email, "testpass123")

    res = client.delete(f"/auth/mcp-tokens/{token_id}",
                         headers={"Authorization": f"Bearer {other_token}"})
    assert res.status_code == 404


def test_admin_can_view_and_revoke_user_token(client, admin_token, active_user):
    email, password = active_user
    user_token = _user_login(client, email, password)
    res = client.post("/auth/mcp-tokens", headers={"Authorization": f"Bearer {user_token}"},
                       json={"name": "Antigravity"})
    token_id = res.json()["id"]

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    users_res = client.get("/api/admin/users", headers=admin_headers)
    user_id = next(u["id"] for u in users_res.json() if u["email"] == email)

    res = client.get(f"/api/admin/users/{user_id}/mcp-tokens", headers=admin_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "Antigravity"

    res = client.delete(f"/api/admin/users/{user_id}/mcp-tokens/{token_id}", headers=admin_headers)
    assert res.status_code == 204

    res = client.get("/auth/mcp-tokens", headers={"Authorization": f"Bearer {user_token}"})
    assert res.json() == []


@pytest.mark.anyio
async def test_mcp_tool_call_with_personal_access_token(live_server, client, mcp_access_token):
    """用 personal access token（而不是 OAuth access token）當 Bearer，一樣要能呼叫 MCP tool。"""
    _oauth_access_token, pbi_config_id, user_id = mcp_access_token

    # fixture 只回傳 access_token/pbi_config_id/user_id，沒有使用者的 session token，
    # 這裡用 admin token 查出 email 後用固定密碼（見 conftest.active_user）重新登入。
    admin_res = client.post("/api/admin/login", json={"secret": os.environ["ADMIN_SECRET"]})
    admin_headers = {"Authorization": f"Bearer {admin_res.json()['access_token']}"}
    users_res = client.get("/api/admin/users", headers=admin_headers)
    email = next(u["email"] for u in users_res.json() if u["id"] == user_id)
    user_session_token = _user_login(client, email, "testpass123")
    res = client.post("/auth/mcp-tokens", headers={"Authorization": f"Bearer {user_session_token}"},
                       json={"name": "Antigravity"})
    pat = res.json()["token"]

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {pat}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("list_models", {})
            assert not result.isError
            models = result.structuredContent["result"]
            assert any(m["pbi_config_id"] == pbi_config_id for m in models)


def test_batch_activate_and_batch_delete(client, admin_token):
    import uuid
    headers = {"Authorization": f"Bearer {admin_token}"}
    emails = [f"batch-{uuid.uuid4().hex[:8]}@example.com" for _ in range(2)]
    for e in emails:
        client.post("/auth/register", json={"email": e, "password": "testpass123"})

    users_res = client.get("/api/admin/users", headers=headers)
    ids = [u["id"] for u in users_res.json() if u["email"] in emails]
    assert len(ids) == 2

    res = client.post("/api/admin/users/batch-activate", headers=headers,
                       json={"user_ids": ids, "is_active": True})
    assert res.status_code == 200

    users_res = client.get("/api/admin/users", headers=headers)
    for u in users_res.json():
        if u["id"] in ids:
            assert u["is_active"] is True

    res = client.post("/api/admin/users/batch-delete", headers=headers, json={"user_ids": ids})
    assert res.status_code == 200

    users_res = client.get("/api/admin/users", headers=headers)
    remaining_ids = {u["id"] for u in users_res.json()}
    assert not remaining_ids & set(ids)


def test_batch_assign_pbi_configs_only_adds(client, admin_token, active_user):
    import uuid
    headers = {"Authorization": f"Bearer {admin_token}"}
    email, _ = active_user
    users_res = client.get("/api/admin/users", headers=headers)
    user_id = next(u["id"] for u in users_res.json() if u["email"] == email)

    cfg1 = client.post("/api/admin/pbi-configs", headers=headers,
                        json={"name": f"batch-cfg-{uuid.uuid4().hex[:8]}"}).json()["id"]
    cfg2 = client.post("/api/admin/pbi-configs", headers=headers,
                        json={"name": f"batch-cfg-{uuid.uuid4().hex[:8]}"}).json()["id"]

    # 先指派 cfg1
    client.put(f"/api/admin/users/{user_id}/pbi-configs", headers=headers,
               json={"pbi_config_ids": [cfg1]})

    # 批次指派 cfg2 給這個使用者，cfg1 應該還在（批次是新增，不是取代）
    res = client.put("/api/admin/users/batch-pbi-configs", headers=headers,
                      json={"user_ids": [user_id], "pbi_config_ids": [cfg2]})
    assert res.status_code == 200

    users_res = client.get("/api/admin/users", headers=headers)
    row = next(u for u in users_res.json() if u["id"] == user_id)
    assert set(row["pbi_config_ids"]) == {cfg1, cfg2}
