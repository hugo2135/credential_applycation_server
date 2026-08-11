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


def test_mcp_no_trailing_slash_does_not_redirect(client):
    """裸路徑 "/mcp" 不能真的發生 HTTP 轉址：部分 MCP client（例如 Gemini）跟隨轉址
    重新發送請求時不會保留 Authorization header，之前用 307 轉址到 "/mcp/" 會讓這些
    client 認證失敗。改成 ASGI 層內部補尾斜線後，"/mcp" 應該跟 "/mcp/" 行為一致
    （直接回 401，而不是先來一次 307）。"""
    res = client.get(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        follow_redirects=False,
    )
    assert res.status_code == 401
    assert "resource_metadata" in res.headers.get("www-authenticate", "")


@pytest.mark.anyio
async def test_mcp_tool_round_trip_without_trailing_slash(live_server, mcp_access_token):
    """有些 MCP client（例如 Gemini）連線設定填的是不帶尾斜線的 "/mcp"。之前這裡
    會先吃一次 307 轉址到 "/mcp/"，如果 client 在轉址後把 Authorization header
    弄丟就會認證失敗；現在 server 端在 ASGI 層直接處理掉這個差異，"/mcp" 應該
    要能像 "/mcp/" 一樣直接完成完整的 MCP 協定往返，不能只靠上面那個 401 測試。"""
    access_token, pbi_config_id, _user_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert {"list_models", "get_model_detail", "get_query_ticket"} <= tool_names


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
            assert {"list_models", "get_model_detail", "get_query_ticket"} <= tool_names

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
async def test_mcp_get_query_ticket_requires_azure_ad_credentials(live_server, mcp_access_token):
    """使用者還沒設定 Azure AD 憑證時，get_query_ticket 就該被擋下並給出清楚訊息——
    刻意在發 ticket 這一步就擋，而不是等到腳本拿去 redeem 才失敗，那時候的錯誤離
    問題根源更遠、更難查。"""
    access_token, pbi_config_id, _user_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_query_ticket", {"pbi_config_id": pbi_config_id})
            assert result.isError
            assert "Azure AD" in result.content[0].text
