"""get_model_detail 的語意模型快取。

快取的只有「上傳後就不會再變的 relationships/tables」，key 是 (pbi_config_id,
model_version)。管理員隨時會改的 filters/query_modes/column_aliases/workspace_id
一律每次現讀——這幾個測試就是在守住這條界線，避免有人日後把整包回應都拿去快取。
"""

import json
import uuid

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _model_payload(table_name: str) -> dict:
    return {
        "relationships": [],
        "tables": [{
            "name": table_name,
            "columns": [{"name": "id", "dataType": "Int64", "description": ""}],
            "measures": [],
        }],
    }


async def _get_detail(live_server, access_token, pbi_config_id, mode_id=None):
    args = {"pbi_config_id": pbi_config_id}
    if mode_id:
        args["mode_id"] = mode_id
    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_model_detail", args)
            assert not result.isError, result.content[0].text
            return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_config_edits_are_not_masked_by_cache(live_server, client, admin_token, mcp_access_token):
    """先讓快取熱起來，再改 filters/column_aliases，下一次呼叫必須立刻看到新值。

    這是把快取 key 訂成只含 model_version 的主要理由：如果整包回應都照 model_version
    快取，管理員改完篩選規則後 skill 會繼續拿到舊的，而篩選規則直接影響查詢回傳哪些資料。
    """
    access_token, pbi_config_id, _user_id = mcp_access_token
    headers = {"Authorization": f"Bearer {admin_token}"}

    first = await _get_detail(live_server, access_token, pbi_config_id)
    assert first["filters"] == []
    assert first["column_aliases"] == []

    new_filters = [{
        "filterId": "exclude-returns", "name": "排除退貨單", "description": None,
        "alwaysApply": True, "overrideDefaults": False, "contextKeywords": [],
        "filters": [{"description": "排除退貨單", "expression": 'Orders[t] <> "r"', "requiredTable": None}],
    }]
    new_aliases = [{"table": "TestTable", "column": "region",
                    "values": [{"value": "North", "aliases": ["北區"]}]}]
    res = client.patch(f"/api/admin/pbi-configs/{pbi_config_id}", headers=headers, json={
        "filters": new_filters,
        "column_aliases": new_aliases,
        "workspace_id": "ws-updated",
    })
    assert res.status_code == 200

    second = await _get_detail(live_server, access_token, pbi_config_id)
    assert second["filters"] == new_filters
    assert second["column_aliases"] == new_aliases
    assert second["workspace_id"] == "ws-updated"
    # 模型結構本身沒重新上傳，版本應該不變（代表走的是快取那條路）
    assert second["model_version"] == first["model_version"]


@pytest.mark.anyio
async def test_new_model_version_invalidates_cache(live_server, client, admin_token, mcp_access_token):
    """上傳新版本會讓 model_version 變動、cache key 隨之改變，不需要主動失效。"""
    access_token, pbi_config_id, _user_id = mcp_access_token
    headers = {"Authorization": f"Bearer {admin_token}"}

    first = await _get_detail(live_server, access_token, pbi_config_id)
    assert [t["table"] for t in first["tables"]] == ["TestTable"]

    res = client.post("/api/admin/model/upload", headers=headers, json={
        "pbi_config_id": pbi_config_id, "name": "v2", "data": _model_payload("BrandNewTable"),
    })
    assert res.status_code == 201

    second = await _get_detail(live_server, access_token, pbi_config_id)
    assert second["model_version"] == first["model_version"] + 1
    assert [t["table"] for t in second["tables"]] == ["BrandNewTable"]


@pytest.mark.anyio
async def test_mode_table_filtering_does_not_corrupt_cache(live_server, client, admin_token, mcp_access_token):
    """帶 mode_id 會對 tables 做子集篩選。那必須產生新的 list，不能就地改動快取裡
    共用的那份——否則之後不帶 mode_id 的呼叫會拿到被截斷的表清單。"""
    access_token, pbi_config_id, _user_id = mcp_access_token
    headers = {"Authorization": f"Bearer {admin_token}"}

    res = client.post("/api/admin/model/upload", headers=headers, json={
        "pbi_config_id": pbi_config_id, "name": "multi",
        "data": {
            "relationships": [],
            "tables": [
                {"name": "Alpha", "columns": [{"name": "id", "dataType": "Int64", "description": ""}], "measures": []},
                {"name": "Beta", "columns": [{"name": "id", "dataType": "Int64", "description": ""}], "measures": []},
            ],
        },
    })
    assert res.status_code == 201

    res = client.patch(f"/api/admin/pbi-configs/{pbi_config_id}", headers=headers, json={
        "query_modes": [{"mode_id": "alpha-only", "name": "只看 Alpha", "description": None,
                         "tables": ["Alpha"], "filters": []}],
    })
    assert res.status_code == 200

    scoped = await _get_detail(live_server, access_token, pbi_config_id, mode_id="alpha-only")
    assert [t["table"] for t in scoped["tables"]] == ["Alpha"]

    # 再不帶 mode_id 呼叫一次，兩張表都必須還在
    full = await _get_detail(live_server, access_token, pbi_config_id)
    assert sorted(t["table"] for t in full["tables"]) == ["Alpha", "Beta"]


@pytest.mark.anyio
async def test_cache_actually_hits(live_server, client, admin_token, mcp_access_token):
    """確認第二次呼叫真的走快取，而不是每次都回頭讀 DB。"""
    from app.routers.mcp import _load_model_chunk

    access_token, pbi_config_id, _user_id = mcp_access_token
    _load_model_chunk.cache_clear()

    await _get_detail(live_server, access_token, pbi_config_id)
    after_first = _load_model_chunk.cache_info()
    assert after_first.misses == 1 and after_first.hits == 0

    await _get_detail(live_server, access_token, pbi_config_id)
    after_second = _load_model_chunk.cache_info()
    assert after_second.hits == 1
    assert after_second.misses == 1  # 沒有再進 DB 讀一次


def test_missing_model_chunk_is_not_cached():
    """lru_cache 不會快取例外——刪光版本後重新上傳會讓版本號從 1 重來，
    若當初把「找不到」快取起來，重新上傳的 v1 會被誤判成不存在。"""
    from app.routers.mcp import _ModelChunkMissing, _load_model_chunk

    fake_id = f"no-such-config-{uuid.uuid4().hex[:8]}"
    for _ in range(2):
        with pytest.raises(_ModelChunkMissing):
            _load_model_chunk(fake_id, 1)

    # 兩次都真的去查了 DB，代表失敗結果沒有被留在快取裡
    assert _load_model_chunk.cache_info().misses >= 2
