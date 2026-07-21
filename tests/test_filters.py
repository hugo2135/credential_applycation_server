"""PbiConfig.filters：管理員在 /admin/pbi-configs 設定的篩選規則，
透過 MCP 的 get_model_detail 交給 skill 端使用。"""

import json
import uuid

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SAMPLE_FILTERS = [
    {
        "filterId": "exclude-return-orders",
        "name": "排除退貨單",
        "description": "預設查詢排除退貨訂單",
        "alwaysApply": True,
        "overrideDefaults": False,
        "contextKeywords": [],
        "filters": [
            {
                "description": "排除退貨單",
                "expression": 'Orders[order_type] <> "return_order"',
                "requiredTable": None,
            }
        ],
    }
]


def test_update_pbi_config_filters(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/pbi-configs", headers=headers, json={
        "name": f"filter-test-{uuid.uuid4().hex[:8]}",
    })
    assert res.status_code == 201
    config_id = res.json()["id"]

    res = client.get("/api/admin/pbi-configs", headers=headers)
    row = next(c for c in res.json() if c["id"] == config_id)
    assert row["filters"] == []

    res = client.patch(f"/api/admin/pbi-configs/{config_id}", headers=headers, json={
        "filters": SAMPLE_FILTERS,
    })
    assert res.status_code == 200

    res = client.get("/api/admin/pbi-configs", headers=headers)
    row = next(c for c in res.json() if c["id"] == config_id)
    assert row["filters"] == SAMPLE_FILTERS


def test_update_pbi_config_filters_rejects_invalid_shape(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/pbi-configs", headers=headers, json={
        "name": f"filter-test-{uuid.uuid4().hex[:8]}",
    })
    config_id = res.json()["id"]

    # 缺必填欄位 name
    res = client.patch(f"/api/admin/pbi-configs/{config_id}", headers=headers, json={
        "filters": [{"filterId": "x", "filters": []}],
    })
    assert res.status_code == 422


@pytest.mark.anyio
async def test_get_model_detail_includes_filters(live_server, client, admin_token, mcp_access_token):
    access_token, pbi_config_id, _user_id = mcp_access_token

    res = client.patch(f"/api/admin/pbi-configs/{pbi_config_id}",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"filters": SAMPLE_FILTERS})
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
            assert detail["filters"] == SAMPLE_FILTERS
