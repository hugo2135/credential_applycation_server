"""v1.6 語意模型版本管理：版本號不重複使用、指定 MCP 提供的版本、刪除表／欄位／量值另存新版本。"""

import json
import uuid

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.model_versions import apply_removal, dax_references, find_broken_measures

# ── DAX 引用分析（純函式）──────────────────────────────────────────────────

TABLES = {"sales", "returns", "date"}


def test_dax_references_ignores_strings_comments_and_function_calls():
    refs = dax_references(
        'CALCULATE(SUM(Sales[qty]), Sales[type] <> "Returns") // 排除 Returns\n'
        "+ DATE(2024, 1, 1) /* Returns */",
        TABLES,
    )
    assert refs["tables"] == {"sales"}
    assert refs["qualified"] == {("sales", "qty"), ("sales", "type")}
    assert refs["unqualified"] == set()


def test_dax_references_quoted_bare_and_unqualified():
    refs = dax_references("DIVIDE([淨銷量], COUNTROWS('Returns')) + SUMX(Date, [x])", TABLES)
    assert refs["tables"] == {"returns", "date"}
    assert refs["unqualified"] == {"淨銷量", "x"}


MODEL_TABLES = [
    {"table": "Sales", "columns": [{"column": "qty"}, {"column": "rid"}], "measures": [
        {"measure": "淨銷量", "expression": "SUM(Sales[qty]) - SUM(Returns[qty])"},
        {"measure": "銷量", "expression": "SUM(Sales[qty])"},
        {"measure": "雙倍淨銷量", "expression": "[淨銷量] * 2"},
        {"measure": "迭代", "expression": "SUMX(Sales, [rid])"},
    ]},
    {"table": "Returns", "columns": [{"column": "qty"}, {"column": "id"}], "measures": [
        {"measure": "退貨量", "expression": "SUM(Returns[qty])"},
    ]},
    {"table": "KPI", "columns": [], "measures": [
        {"measure": "退貨指標", "expression": "[退貨量] / [銷量]"},
    ]},
]


def test_find_broken_measures_table_removal():
    broken = find_broken_measures(MODEL_TABLES, ["Returns"], [], [])
    by_name = {b["measure"]: b["reasons"] for b in broken}
    # 直接引用被刪除的表；引用被刪除表裡的量值也算
    assert set(by_name) == {"淨銷量", "退貨指標"}
    assert by_name["退貨指標"] == ["引用了被刪除的量值 [退貨量]"]


def test_find_broken_measures_cascade_and_columns():
    # 刪掉 [淨銷量] 之後，引用它的 [雙倍淨銷量] 就懸空了
    broken = find_broken_measures(MODEL_TABLES, [], [("Sales", "rid")], [("Sales", "淨銷量")])
    by_name = {b["measure"]: b["reasons"] for b in broken}
    assert by_name["雙倍淨銷量"] == ["引用了被刪除的量值 [淨銷量]"]
    # 迭代函式裡沒加表名的欄位
    assert by_name["迭代"] == ["引用了被刪除的欄位 [rid]"]
    assert "銷量" not in by_name


def test_apply_removal_cleans_relationships_and_empty_tables():
    rels = {"relationships": [
        {"fromTable": "Sales", "fromColumn": "rid", "toTable": "Returns", "toColumn": "id"},
        {"fromTable": "Sales", "fromColumn": "qty", "toTable": "KPI", "toColumn": "x"},
    ]}
    new_rels, new_tables, removed = apply_removal(rels, MODEL_TABLES, [], [("Sales", "rid")], [("KPI", "退貨指標")])
    # KPI 只有一個量值、被刪光後整張視同刪除，連帶它的關聯也刪
    assert [t["table"] for t in new_tables] == ["Sales", "Returns"]
    assert new_rels["relationships"] == []
    assert removed == 2
    # 原物件沒有被修改
    assert len(MODEL_TABLES[0]["columns"]) == 2


# ── API ─────────────────────────────────────────────────────────────────────

def _headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _upload(client, admin_token, config_id, table="T", name="v"):
    res = client.post("/api/admin/model/upload", headers=_headers(admin_token), json={
        "pbi_config_id": config_id, "name": name,
        "data": {"relationships": [], "tables": [
            {"name": table, "columns": [{"name": "id", "dataType": "Int64"}], "measures": []},
        ]},
    })
    assert res.status_code == 201, res.text
    return res.json()["model_version"]


def _versions(client, admin_token, config_id):
    res = client.get("/api/admin/model/versions", headers=_headers(admin_token), params={"pbi_config_id": config_id})
    return res.json()


async def _detail(live_server, access_token, config_id):
    async with streamablehttp_client(
        f"{live_server}/mcp/", headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_model_detail", {"pbi_config_id": config_id})
            assert not result.isError, result.content[0].text
            return json.loads(result.content[0].text)


def test_version_numbers_are_never_reused(client, admin_token):
    res = client.post("/api/admin/pbi-configs", headers=_headers(admin_token), json={"name": f"ver-{uuid.uuid4().hex[:8]}"})
    config_id = res.json()["id"]
    assert _upload(client, admin_token, config_id) == 1
    assert _upload(client, admin_token, config_id) == 2

    v2 = next(v for v in _versions(client, admin_token, config_id) if v["model_version"] == 2)
    assert client.delete(f"/api/admin/model/versions/{v2['id']}", headers=_headers(admin_token)).status_code == 204

    # 以前會重新拿到 2，跟快取裡被刪掉的那份 v2 撞號
    assert _upload(client, admin_token, config_id) == 3


@pytest.mark.anyio
async def test_active_version_controls_what_mcp_serves(live_server, client, admin_token, mcp_access_token):
    access_token, config_id, _ = mcp_access_token
    h = _headers(admin_token)
    assert _upload(client, admin_token, config_id, table="NewTable") == 2

    assert (await _detail(live_server, access_token, config_id))["model_version"] == 2

    res = client.put(f"/api/admin/pbi-configs/{config_id}/active-version", headers=h, json={"model_version": 1})
    assert res.status_code == 200
    detail = await _detail(live_server, access_token, config_id)
    assert detail["model_version"] == 1
    assert [t["table"] for t in detail["tables"]] == ["TestTable"]

    # 下拉選單預設列提供中的版本，也可以指定看別版
    assert client.get(f"/api/admin/pbi-configs/{config_id}/schema", headers=h).json()["model_version"] == 1
    res = client.get(f"/api/admin/pbi-configs/{config_id}/schema", headers=h, params={"version": 2})
    assert [t["table"] for t in res.json()["tables"]] == ["NewTable"]

    rows = {v["model_version"]: v for v in _versions(client, admin_token, config_id)}
    assert rows[1]["is_serving"] and not rows[2]["is_serving"]

    # 指定中的版本不能刪
    res = client.delete(f"/api/admin/model/versions/{rows[1]['id']}", headers=h)
    assert res.status_code == 409

    # 新上傳的版本不會自動上線
    assert _upload(client, admin_token, config_id) == 3
    assert (await _detail(live_server, access_token, config_id))["model_version"] == 1

    res = client.put(f"/api/admin/pbi-configs/{config_id}/active-version", headers=h, json={"model_version": None})
    assert res.json()["serving_model_version"] == 3
    assert (await _detail(live_server, access_token, config_id))["model_version"] == 3


def test_active_version_unknown_is_404(client, admin_token, mcp_access_token):
    _, config_id, _ = mcp_access_token
    res = client.put(f"/api/admin/pbi-configs/{config_id}/active-version",
                     headers=_headers(admin_token), json={"model_version": 99})
    assert res.status_code == 404


@pytest.mark.anyio
async def test_bookmarks_compare_against_serving_version(live_server, client, admin_token, mcp_access_token):
    access_token, config_id, _ = mcp_access_token
    async with streamablehttp_client(
        f"{live_server}/mcp/", headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            _upload(client, admin_token, config_id)  # v2，跟隨最新版所以直接上線
            await session.call_tool("save_bookmark", {"pbi_config_id": config_id, "title": "b", "dax": "EVALUATE X"})

            client.put(f"/api/admin/pbi-configs/{config_id}/active-version",
                       headers=_headers(admin_token), json={"model_version": 1})
            result = await session.call_tool("list_bookmarks", {"pbi_config_id": config_id})
            [bookmark] = result.structuredContent["result"]
            assert bookmark["model_version"] == 2
            assert bookmark["current_model_version"] == 1
            assert bookmark["possibly_outdated"] is True


def test_duplicate_copies_serving_version(client, admin_token, mcp_access_token):
    _, config_id, _ = mcp_access_token
    h = _headers(admin_token)
    _upload(client, admin_token, config_id, table="NewTable")
    client.put(f"/api/admin/pbi-configs/{config_id}/active-version", headers=h, json={"model_version": 1})

    res = client.post(f"/api/admin/pbi-configs/{config_id}/duplicate", headers=h, json={"name": f"dup-{uuid.uuid4().hex[:8]}"})
    new_id = res.json()["id"]
    schema = client.get(f"/api/admin/pbi-configs/{new_id}/schema", headers=h).json()
    assert schema["model_version"] == 1
    assert [t["table"] for t in schema["tables"]] == ["TestTable"]
    # 複製出來的設定接著上傳，版本號從 2 開始
    assert _upload(client, admin_token, new_id) == 2


DERIVE_MODEL = {
    "relationships": [
        {"fromTable": "Sales", "fromColumn": "rid", "toTable": "Returns", "toColumn": "id"},
    ],
    "tables": [
        {"name": "Sales", "columns": [{"name": "qty"}, {"name": "rid"}], "measures": [
            {"name": "淨銷量", "expression": "SUM(Sales[qty]) - SUM(Returns[qty])"},
            {"name": "銷量", "expression": "SUM(Sales[qty])"},
        ]},
        {"name": "Returns", "columns": [{"name": "qty"}, {"name": "id"}], "measures": []},
    ],
}


@pytest.mark.anyio
async def test_derive_version_removes_tables_and_relationships(live_server, client, admin_token, mcp_access_token):
    access_token, config_id, _ = mcp_access_token
    h = _headers(admin_token)
    res = client.post("/api/admin/model/upload", headers=h, json={
        "pbi_config_id": config_id, "name": "full", "data": DERIVE_MODEL,
    })
    source_version = res.json()["model_version"]
    source = next(v for v in _versions(client, admin_token, config_id) if v["model_version"] == source_version)

    content = client.get(f"/api/admin/model/versions/{source['id']}/content", headers=h).json()
    assert len(content["relationships"]) == 1

    # 保留的 [淨銷量] 還引用 Returns，沒確認就不給存
    res = client.post(f"/api/admin/model/versions/{source['id']}/derive", headers=h,
                      json={"remove_tables": ["Returns"]})
    assert res.status_code == 409
    assert res.json()["detail"]["dangling"][0]["measure"] == "淨銷量"

    # 連同量值一起刪就沒有懸空引用
    res = client.post(f"/api/admin/model/versions/{source['id']}/derive", headers=h, json={
        "remove_tables": ["Returns"], "remove_measures": [{"table": "Sales", "measure": "淨銷量"}],
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["model_version"] == source_version + 1
    assert body["removed_relationship_count"] == 1

    row = next(v for v in _versions(client, admin_token, config_id) if v["model_version"] == body["model_version"])
    assert row["derived_from_version"] == source_version

    # 原版本不動
    assert len(client.get(f"/api/admin/model/versions/{source['id']}/content", headers=h).json()["tables"]) == 2

    detail = await _detail(live_server, access_token, config_id)
    assert detail["model_version"] == body["model_version"]
    assert [t["table"] for t in detail["tables"]] == ["Sales"]
    assert [m["measure"] for m in detail["tables"][0]["measures"]] == ["銷量"]
    assert detail["relationships"]["relationships"] == []


def test_derive_version_allow_dangling_and_validation(client, admin_token, mcp_access_token):
    _, config_id, _ = mcp_access_token
    h = _headers(admin_token)
    client.post("/api/admin/model/upload", headers=h, json={"pbi_config_id": config_id, "data": DERIVE_MODEL})
    source = _versions(client, admin_token, config_id)[0]
    url = f"/api/admin/model/versions/{source['id']}/derive"

    assert client.post(url, headers=h, json={}).status_code == 422
    assert client.post(url, headers=h, json={"remove_tables": ["NoSuch"]}).status_code == 422
    assert client.post(url, headers=h, json={"remove_tables": ["Sales", "Returns"]}).status_code == 422

    res = client.post(url, headers=h, json={"remove_tables": ["Returns"], "allow_dangling": True})
    assert res.status_code == 201
