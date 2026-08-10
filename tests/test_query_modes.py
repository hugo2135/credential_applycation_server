"""PbiConfig.query_modes／column_aliases：管理員在 /admin/pbi-configs 設定的資料曝光
範圍模式跟重點欄位別名，透過 MCP 的 list_models／get_model_detail 交給 skill 端使用。"""

import json
import uuid

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SAMPLE_QUERY_MODES = [
    {
        "mode_id": "summary",
        "name": "摘要模式",
        "description": "只看高階彙總表",
        "tables": ["TestTable"],
        "filters": [
            {"description": "只看啟用中的資料", "expression": "TestTable[active] = TRUE()", "requiredTable": None},
        ],
    }
]

SAMPLE_COLUMN_ALIASES = [
    {
        "table": "TestTable",
        "column": "region",
        "values": [
            {"value": "North", "aliases": ["北區", "北部"]},
            {"value": "South", "aliases": ["南區", "南部"]},
        ],
    }
]


def test_update_pbi_config_query_modes_and_aliases(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/pbi-configs", headers=headers, json={
        "name": f"mode-test-{uuid.uuid4().hex[:8]}",
    })
    assert res.status_code == 201
    config_id = res.json()["id"]

    res = client.get(f"/api/admin/pbi-configs/{config_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["query_modes"] == []
    assert res.json()["column_aliases"] == []

    res = client.patch(f"/api/admin/pbi-configs/{config_id}", headers=headers, json={
        "query_modes": SAMPLE_QUERY_MODES,
        "column_aliases": SAMPLE_COLUMN_ALIASES,
    })
    assert res.status_code == 200

    res = client.get(f"/api/admin/pbi-configs/{config_id}", headers=headers)
    assert res.json()["query_modes"] == SAMPLE_QUERY_MODES
    assert res.json()["column_aliases"] == SAMPLE_COLUMN_ALIASES

    # 列表頁也要看得到（PbiConfigsView.vue 用這個）
    res = client.get("/api/admin/pbi-configs", headers=headers)
    row = next(c for c in res.json() if c["id"] == config_id)
    assert row["query_modes"] == SAMPLE_QUERY_MODES


def test_update_pbi_config_query_modes_rejects_invalid_shape(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/pbi-configs", headers=headers, json={
        "name": f"mode-test-{uuid.uuid4().hex[:8]}",
    })
    config_id = res.json()["id"]

    # 缺必填欄位 name（QueryMode 要求 mode_id/name）
    res = client.patch(f"/api/admin/pbi-configs/{config_id}", headers=headers, json={
        "query_modes": [{"mode_id": "x"}],
    })
    assert res.status_code == 422


def test_get_pbi_config_404(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.get("/api/admin/pbi-configs/does-not-exist", headers=headers)
    assert res.status_code == 404


@pytest.mark.anyio
async def test_list_models_includes_query_modes(live_server, client, admin_token, mcp_access_token):
    access_token, pbi_config_id, _user_id = mcp_access_token

    res = client.patch(f"/api/admin/pbi-configs/{pbi_config_id}",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"query_modes": SAMPLE_QUERY_MODES})
    assert res.status_code == 200

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("list_models", {})
            assert not result.isError
            models = result.structuredContent["result"]
            row = next(m for m in models if m["pbi_config_id"] == pbi_config_id)
            assert row["query_modes"] == [
                {"mode_id": "summary", "name": "摘要模式", "description": "只看高階彙總表"},
            ]


@pytest.mark.anyio
async def test_get_model_detail_with_mode_id_filters_tables_and_merges_filters(
    live_server, client, admin_token, mcp_access_token,
):
    access_token, pbi_config_id, _user_id = mcp_access_token

    res = client.patch(f"/api/admin/pbi-configs/{pbi_config_id}",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"query_modes": SAMPLE_QUERY_MODES, "column_aliases": SAMPLE_COLUMN_ALIASES})
    assert res.status_code == 200

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_model_detail", {"pbi_config_id": pbi_config_id, "mode_id": "summary"},
            )
            assert not result.isError
            detail = json.loads(result.content[0].text)

            assert detail["query_mode_id"] == "summary"
            assert [t["table"] for t in detail["tables"]] == ["TestTable"]
            assert detail["column_aliases"] == SAMPLE_COLUMN_ALIASES

            # 模式自己的 filters 要疊加成一筆 alwaysApply profile，不取代既有 filters
            mode_profile = next(f for f in detail["filters"] if f["filterId"] == "mode:summary")
            assert mode_profile["alwaysApply"] is True
            assert mode_profile["filters"] == SAMPLE_QUERY_MODES[0]["filters"]


@pytest.mark.anyio
async def test_get_model_detail_without_mode_id_is_unchanged(live_server, client, admin_token, mcp_access_token):
    """向後相容：沒帶 mode_id 時行為要跟加這個功能之前完全一樣（全表、不含模式篩選）。"""
    access_token, pbi_config_id, _user_id = mcp_access_token

    res = client.patch(f"/api/admin/pbi-configs/{pbi_config_id}",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"query_modes": SAMPLE_QUERY_MODES})
    assert res.status_code == 200

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_model_detail", {"pbi_config_id": pbi_config_id})
            assert not result.isError
            detail = json.loads(result.content[0].text)
            assert detail["query_mode_id"] is None
            assert not any(f["filterId"] == "mode:summary" for f in detail["filters"])


@pytest.mark.anyio
async def test_get_model_detail_unknown_mode_id_is_tool_error(live_server, client, mcp_access_token):
    access_token, pbi_config_id, _user_id = mcp_access_token

    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_model_detail", {"pbi_config_id": pbi_config_id, "mode_id": "does-not-exist"},
            )
            assert result.isError
