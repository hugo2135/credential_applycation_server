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
    access_token, pbi_config_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert {"list_models", "get_model_detail", "run_dax_query"} <= tool_names

            result = await session.call_tool("list_models", {})
            assert not result.isError
            models = _list_result(result)
            assert any(m["pbi_config_id"] == pbi_config_id for m in models)

            result = await session.call_tool("get_model_detail", {"pbi_config_id": pbi_config_id})
            assert not result.isError
            detail = _dict_result(result)
            assert detail["pbi_config_id"] == pbi_config_id
            assert detail["tables"][0]["table"] == "TestTable"


@pytest.mark.anyio
async def test_mcp_tool_call_without_access_rejected(live_server, mcp_access_token):
    """換一個沒被指派這個 pbi_config 的使用者 token 呼叫 get_model_detail，應該被拒。"""
    access_token, pbi_config_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_model_detail", {"pbi_config_id": "not-a-real-config-id"})
            assert result.isError


@pytest.mark.anyio
async def test_mcp_run_dax_query_requires_azure_ad_credentials(live_server, mcp_access_token):
    """使用者還沒設定 Azure AD 憑證時，run_dax_query 應該被擋下並給出清楚訊息，而不是直接打 Power BI 炸掉。"""
    access_token, pbi_config_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("run_dax_query", {
                "pbi_config_id": pbi_config_id,
                "dax": "EVALUATE TestTable",
            })
            assert result.isError
            assert "Azure AD" in result.content[0].text
