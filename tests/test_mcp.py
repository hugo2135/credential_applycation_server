import json

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _list_result(result):
    """list[...] 型別的回傳，FastMCP 會用 structuredContent = {"result": [...]} 包起來。"""
    return result.structuredContent["result"]


def _dict_result(result):
    """dict 型別的回傳沒有明確 output schema，FastMCP 不會填 structuredContent，
    直接從 content[0].text 解析 JSON。"""
    return json.loads(result.content[0].text)


def test_mcp_requires_auth(client):
    res = client.get(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        follow_redirects=True,
    )
    assert res.status_code == 401
    assert "resource_metadata" in res.headers.get("www-authenticate", "")


def test_mcp_no_trailing_slash_redirects(client):
    res = client.get("/mcp", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/mcp/"


@pytest.mark.anyio
async def test_mcp_tool_round_trip(live_server, mcp_access_token):
    access_token, pbi_config_id, _user_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert {"list_models", "get_model_detail", "get_powerbi_token"} <= tool_names

            result = await session.call_tool("list_models", {})
            assert not result.isError
            models = _list_result(result)
            assert any(m["pbi_config_id"] == pbi_config_id for m in models)

            result = await session.call_tool("get_model_detail", {"pbi_config_id": pbi_config_id})
            assert not result.isError
            detail = _dict_result(result)
            assert detail["pbi_config_id"] == pbi_config_id
            assert detail["workspace_id"] == "ws-test"
            assert detail["dataset_id"] == "ds-test"
            assert detail["tables"][0]["table"] == "TestTable"


@pytest.mark.anyio
async def test_mcp_tool_call_without_access_rejected(live_server, mcp_access_token):
    """換一個沒被指派這個 pbi_config 的使用者 token 呼叫 get_model_detail，應該被拒。"""
    access_token, pbi_config_id, _user_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_model_detail", {"pbi_config_id": "not-a-real-config-id"})
            assert result.isError


@pytest.mark.anyio
async def test_mcp_get_powerbi_token_requires_azure_ad_credentials(live_server, mcp_access_token):
    """使用者還沒設定 Azure AD 憑證時，get_powerbi_token 應該被擋下並給出清楚訊息，而不是直接打 Azure AD 炸掉。"""
    access_token, pbi_config_id, _user_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_powerbi_token", {"pbi_config_id": pbi_config_id})
            assert result.isError
            assert "Azure AD" in result.content[0].text


@pytest.mark.anyio
async def test_mcp_get_powerbi_token_uses_msal(live_server, client, admin_token, mcp_access_token, monkeypatch):
    """設好 Azure AD 憑證後，get_powerbi_token 應該回傳 access_token/token_type/expires_in，
    且不含 workspace_id/dataset_id（那些留給 get_model_detail 回傳，避免重複）。
    這裡直接 mock acquire_powerbi_token（而不是 msal 內部），因為 msal 建構
    ConfidentialClientApplication 時就會打網路去驗證 authority，光 mock
    acquire_token_for_client 不夠。要 patch 在 app.routers.mcp 這個命名空間裡，
    因為 mcp.py 是用 `from app.routers.credential import acquire_powerbi_token`
    直接把函式物件 import 進自己的命名空間，patch credential 模組本身沒用。"""
    import app.routers.mcp as mcp_module

    def fake_acquire_powerbi_token(user):
        return {"access_token": "fake-azure-token", "expires_in": 3599}

    monkeypatch.setattr(mcp_module, "acquire_powerbi_token", fake_acquire_powerbi_token)

    access_token, pbi_config_id, user_id = mcp_access_token

    res = client.patch(
        f"/api/admin/users/{user_id}/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"tenant_id": "test-tenant", "client_id": "test-client", "client_secret": "test-secret"},
    )
    assert res.status_code == 200

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_powerbi_token", {"pbi_config_id": pbi_config_id})
            assert not result.isError
            token_info = _dict_result(result)
            assert token_info["access_token"] == "fake-azure-token"
            assert token_info["token_type"] == "Bearer"
            assert token_info["expires_in"] == 3599
            assert "workspace_id" not in token_info
            assert "dataset_id" not in token_info
