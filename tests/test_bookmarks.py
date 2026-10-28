"""書籤：skill 透過 MCP tool 存取，使用者在 /auth/bookmarks 管理、匯出匯入。"""

import json
import os
import uuid

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import app.bookmarks as bookmark_module


async def _call(live_server, access_token, tool, args):
    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool, args)


def _json(result):
    assert not result.isError, result.content[0].text
    if result.structuredContent and "result" in result.structuredContent:
        return result.structuredContent["result"]
    return json.loads(result.content[0].text)


def _user_headers(client, email, password):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _upload_model_version(client, admin_token, pbi_config_id):
    res = client.post("/api/admin/model/upload", headers={"Authorization": f"Bearer {admin_token}"}, json={
        "pbi_config_id": pbi_config_id,
        "name": "v-next",
        "model_description": None,
        "data": {"relationships": [], "tables": [{"name": "T2", "columns": [], "measures": []}]},
    })
    assert res.status_code == 201


@pytest.mark.anyio
async def test_save_conflict_requires_explicit_overwrite(live_server, mcp_access_token):
    token, config_id, _ = mcp_access_token
    args = {"pbi_config_id": config_id, "title": "月銷售", "dax": "EVALUATE A", "question": "這個月賣多少"}

    first = _json(await _call(live_server, token, "save_bookmark", args))
    assert first["saved"] is True and first["status"] == "created"
    assert first["bookmark"]["question"] == "這個月賣多少"

    # 同名、沒有 overwrite：不能覆蓋，要回傳既有內容讓 AI 去問使用者
    conflict = _json(await _call(live_server, token, "save_bookmark", {**args, "dax": "EVALUATE B"}))
    assert conflict["saved"] is False and conflict["conflict"] is True
    assert conflict["existing"]["dax"] == "EVALUATE A"

    listed = _json(await _call(live_server, token, "list_bookmarks", {"pbi_config_id": config_id}))
    assert [b["dax"] for b in listed] == ["EVALUATE A"]

    over = _json(await _call(live_server, token, "save_bookmark", {**args, "dax": "EVALUATE B", "overwrite": True}))
    assert over["saved"] is True and over["status"] == "overwritten"
    listed = _json(await _call(live_server, token, "list_bookmarks", {}))
    assert [b["dax"] for b in listed] == ["EVALUATE B"]

    deleted = _json(await _call(live_server, token, "delete_bookmark", {"bookmark_id": listed[0]["id"]}))
    assert deleted == {"deleted": True}
    assert _json(await _call(live_server, token, "list_bookmarks", {})) == []


@pytest.mark.anyio
async def test_bookmark_marked_outdated_after_model_upgrade(live_server, mcp_access_token, client, admin_token):
    token, config_id, _ = mcp_access_token
    _json(await _call(live_server, token, "save_bookmark",
                      {"pbi_config_id": config_id, "title": "x", "dax": "EVALUATE A"}))
    listed = _json(await _call(live_server, token, "list_bookmarks", {}))
    assert listed[0]["possibly_outdated"] is False

    _upload_model_version(client, admin_token, config_id)
    listed = _json(await _call(live_server, token, "list_bookmarks", {}))
    assert listed[0]["possibly_outdated"] is True
    assert listed[0]["current_model_version"] == listed[0]["model_version"] + 1


@pytest.mark.anyio
async def test_cannot_save_to_unassigned_config(live_server, mcp_access_token, client, admin_token):
    token, _, _ = mcp_access_token
    res = client.post("/api/admin/pbi-configs", headers={"Authorization": f"Bearer {admin_token}"},
                      json={"name": f"other-{uuid.uuid4().hex[:8]}"})
    other_config = res.json()["id"]
    result = await _call(live_server, token, "save_bookmark",
                         {"pbi_config_id": other_config, "title": "x", "dax": "EVALUATE A"})
    assert result.isError
    assert "存取權" in result.content[0].text


@pytest.mark.anyio
async def test_bookmarks_hidden_when_assignment_removed(
    live_server, mcp_access_token, active_user, client, admin_token,
):
    token, config_id, user_id = mcp_access_token
    _json(await _call(live_server, token, "save_bookmark",
                      {"pbi_config_id": config_id, "title": "x", "dax": "EVALUATE A"}))
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    client.put(f"/api/admin/users/{user_id}/pbi-configs", headers=admin_headers, json={"pbi_config_ids": []})
    headers = _user_headers(client, *active_user)
    assert client.get("/auth/bookmarks", headers=headers).json() == []

    # 重新指派，書籤回來，不用重存
    client.put(f"/api/admin/users/{user_id}/pbi-configs", headers=admin_headers,
               json={"pbi_config_ids": [config_id]})
    assert len(client.get("/auth/bookmarks", headers=headers).json()) == 1


@pytest.mark.anyio
async def test_bookmark_limit(live_server, mcp_access_token, monkeypatch):
    token, config_id, _ = mcp_access_token
    monkeypatch.setattr(bookmark_module, "MAX_BOOKMARKS_PER_USER", 2)
    for title in ("a", "b"):
        _json(await _call(live_server, token, "save_bookmark",
                          {"pbi_config_id": config_id, "title": title, "dax": "EVALUATE A"}))
    result = await _call(live_server, token, "save_bookmark",
                         {"pbi_config_id": config_id, "title": "c", "dax": "EVALUATE A"})
    assert result.isError
    assert "上限" in result.content[0].text
    # 覆蓋既有書籤不算新增，達上限時仍然可以
    over = _json(await _call(live_server, token, "save_bookmark",
                             {"pbi_config_id": config_id, "title": "a", "dax": "EVALUATE Z", "overwrite": True}))
    assert over["saved"] is True


@pytest.mark.anyio
async def test_export_and_import_between_users(live_server, mcp_access_token, active_user, client, admin_token):
    token, config_id, _ = mcp_access_token
    for title in ("甲", "乙"):
        _json(await _call(live_server, token, "save_bookmark",
                          {"pbi_config_id": config_id, "title": title, "dax": f"EVALUATE {title}"}))
    headers = _user_headers(client, *active_user)
    res = client.get("/auth/bookmarks/export", headers=headers)
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    exported = res.json()
    assert exported["format"] == "nl-to-dax-bookmarks"
    assert {b["title"] for b in exported["bookmarks"]} == {"甲", "乙"}
    assert "id" not in exported["bookmarks"][0]

    # 另一位使用者：有同一個模型的存取權，且已有一筆同名「甲」
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/auth/register", json={"email": other_email, "password": "testpass123"})
    client.patch("/api/admin/users/activate", headers=admin_headers, json={"email": other_email, "is_active": True})
    other_id = next(u["id"] for u in client.get("/api/admin/users", headers=admin_headers).json()
                    if u["email"] == other_email)
    client.put(f"/api/admin/users/{other_id}/pbi-configs", headers=admin_headers,
               json={"pbi_config_ids": [config_id]})
    other_headers = _user_headers(client, other_email, "testpass123")
    client.post("/auth/bookmarks/import", headers=other_headers, json={"data": {
        **exported, "bookmarks": [{**exported["bookmarks"][0], "title": "甲", "dax": "EVALUATE 我自己的"}],
    }})

    res = client.post("/auth/bookmarks/import", headers=other_headers,
                      json={"data": exported, "on_conflict": "skip"})
    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 1 and body["overwritten"] == 0
    assert [s["title"] for s in body["skipped"]] == ["甲"]
    mine = {b["title"]: b["dax"] for b in client.get("/auth/bookmarks", headers=other_headers).json()}
    assert mine["甲"] == "EVALUATE 我自己的"

    res = client.post("/auth/bookmarks/import", headers=other_headers,
                      json={"data": exported, "on_conflict": "overwrite"})
    assert res.json()["overwritten"] == 2
    mine = {b["title"]: b["dax"] for b in client.get("/auth/bookmarks", headers=other_headers).json()}
    assert mine["甲"] == "EVALUATE 甲"


def test_import_reports_unassigned_models_and_rejects_bad_files(client, active_user):
    headers = _user_headers(client, *active_user)
    data = {"format": "nl-to-dax-bookmarks", "version": 1, "bookmarks": [
        {"pbi_config_id": "nope", "pbi_config_name": "別人的模型", "title": "t", "dax": "EVALUATE A"},
    ]}
    res = client.post("/auth/bookmarks/import", headers=headers, json={"data": data})
    assert res.status_code == 200
    assert res.json()["failed"] == [{"title": "t", "reason": "你沒有「別人的模型」這個模型的存取權"}]

    for bad in ({"bookmarks": []}, {**data, "version": 99}, {**data, "bookmarks": "x"}):
        assert client.post("/auth/bookmarks/import", headers=headers, json={"data": bad}).status_code == 400
    assert client.post("/auth/bookmarks/import", headers=headers,
                       json={"data": data, "on_conflict": "merge"}).status_code == 400


@pytest.mark.anyio
async def test_cannot_delete_other_users_bookmark(live_server, mcp_access_token, client, admin_token):
    token, config_id, _ = mcp_access_token
    saved = _json(await _call(live_server, token, "save_bookmark",
                              {"pbi_config_id": config_id, "title": "x", "dax": "EVALUATE A"}))
    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/auth/register", json={"email": other_email, "password": "testpass123"})
    res = client.post("/api/admin/login", json={"secret": os.environ["ADMIN_SECRET"]})
    client.patch("/api/admin/users/activate", headers={"Authorization": f"Bearer {res.json()['access_token']}"},
                 json={"email": other_email, "is_active": True})
    other_headers = _user_headers(client, other_email, "testpass123")
    res = client.delete(f"/auth/bookmarks/{saved['bookmark']['id']}", headers=other_headers)
    assert res.status_code == 404
