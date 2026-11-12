"""Server 查詢模式（v2.0）：使用者層級切換 edge／server，server 模式由 run_query 代查。"""

import json
import uuid

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import app.server_query as server_query
from app.server_query import QueryLimits, QueryTarget, ServerQueryError, execute_dax

ROWS = [{"T[a]": 1}, {"T[a]": 2}, {"T[a]": 3}]


@pytest.fixture
def fake_powerbi(monkeypatch):
    """mock 掉 Azure AD 與 Power BI。回傳 state：可改 response，可讀到收到的請求。"""
    state = {"status": 200, "body": {"results": [{"tables": [{"rows": ROWS}]}]}, "requests": [], "delay": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if state["delay"]:
            await anyio.sleep(state["delay"])
        return httpx.Response(state["status"], json=state["body"])

    monkeypatch.setattr(server_query, "acquire_powerbi_token", lambda creds: {"access_token": "fake"})
    monkeypatch.setattr(server_query, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return state


def _headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _set_credentials(client, admin_token, user_id):
    res = client.patch(f"/api/admin/users/{user_id}/credentials", headers=_headers(admin_token),
                       json={"tenant_id": "t", "client_id": "c", "client_secret": "s"})
    assert res.status_code == 200


def _set_mode(client, admin_token, user_ids, mode):
    res = client.post("/api/admin/users/batch-query-execution", headers=_headers(admin_token),
                      json={"user_ids": user_ids, "query_execution": mode})
    assert res.status_code == 200


def _put_settings(client, admin_token, values):
    return client.put("/api/admin/settings", headers=_headers(admin_token), json=values)


async def _call(live_server, access_token, tool, args):
    async with streamablehttp_client(
        f"{live_server}/mcp/", headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool, args)


def _run_query_logs(client, admin_token, user_id):
    users = client.get("/api/admin/users", headers=_headers(admin_token)).json()
    email = next(u["email"] for u in users if u["id"] == user_id)
    logs = client.get("/api/admin/access-logs", headers=_headers(admin_token), params={"email": email}).json()
    return [l for l in logs if l["path"] == "/mcp/run_query"]


@pytest.mark.anyio
async def test_edge_user_cannot_run_query(live_server, client, admin_token, mcp_access_token, fake_powerbi):
    access_token, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)

    detail = await _call(live_server, access_token, "get_model_detail", {"pbi_config_id": config_id})
    assert json.loads(detail.content[0].text)["query_execution"] == "edge"

    result = await _call(live_server, access_token, "run_query", {"pbi_config_id": config_id, "dax": "EVALUATE T"})
    assert result.isError
    assert "get_query_ticket" in result.content[0].text
    assert not fake_powerbi["requests"]
    logs = _run_query_logs(client, admin_token, user_id)
    assert logs and logs[0]["error"] and logs[0]["query_text"] == "EVALUATE T"


@pytest.mark.anyio
async def test_server_user_runs_query_and_ticket_is_refused(
    live_server, client, admin_token, mcp_access_token, fake_powerbi,
):
    access_token, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    _set_mode(client, admin_token, [user_id], "server")

    users = client.get("/api/admin/users", headers=_headers(admin_token)).json()
    assert next(u for u in users if u["id"] == user_id)["query_execution"] == "server"

    ticket = await _call(live_server, access_token, "get_query_ticket", {"pbi_config_id": config_id})
    assert ticket.isError
    assert "run_query" in ticket.content[0].text

    original = client.get("/api/admin/settings", headers=_headers(admin_token)).json()["values"]
    assert _put_settings(client, admin_token, {"server_query_max_rows": 2}).status_code == 200
    try:
        result = await _call(live_server, access_token, "run_query",
                             {"pbi_config_id": config_id, "dax": "EVALUATE T"})
    finally:
        _put_settings(client, admin_token, {"server_query_max_rows": original["server_query_max_rows"]})

    assert not result.isError
    payload = json.loads(result.content[0].text)
    table = payload["tables"][0]
    assert table["columns"] == ["T[a]"]
    assert table["rows"] == ROWS[:2]
    assert table["row_count"] == 3 and table["truncated"] is True

    request = fake_powerbi["requests"][0]
    assert "/groups/ws-test/datasets/ds-test/executeQueries" in str(request.url)
    assert json.loads(request.content)["queries"][0]["query"] == "EVALUATE T"

    logs = _run_query_logs(client, admin_token, user_id)
    assert logs[0]["error"] is None
    assert logs[0]["query_text"] == "EVALUATE T"
    assert logs[0]["detail"] == config_id


@pytest.mark.anyio
async def test_dax_error_is_returned_to_ai(live_server, client, admin_token, mcp_access_token, fake_powerbi):
    access_token, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    _set_mode(client, admin_token, [user_id], "server")
    fake_powerbi["status"] = 400
    fake_powerbi["body"] = {"error": {"code": "DatasetExecuteQueriesError", "pbi.error": {"details": [
        {"code": "DetailsMessage", "detail": {"type": 1, "value": "Query (1, 10) Cannot find table 'X'."}},
    ]}}}

    result = await _call(live_server, access_token, "run_query", {"pbi_config_id": config_id, "dax": "EVALUATE X"})
    assert result.isError
    assert "DAX 執行錯誤" in result.content[0].text
    assert "Cannot find table 'X'" in result.content[0].text
    assert "Cannot find table" in _run_query_logs(client, admin_token, user_id)[0]["error"]


@pytest.mark.anyio
async def test_concurrency_limit_queues_and_times_out(fake_powerbi):
    fake_powerbi["delay"] = 1
    target = QueryTarget("t", "c", "s", "ws", "ds")
    limits = QueryLimits(max_concurrency=1, max_rows=10, timeout_seconds=1)
    outcomes = []

    async def run():
        try:
            await execute_dax(target, "EVALUATE T", limits)
            outcomes.append("ok")
        except ServerQueryError as e:
            outcomes.append(str(e))

    # 兩個查詢都超時：第一個拿到位子後被 Power BI 拖住，第二個一直在排隊
    async with anyio.create_task_group() as tg:
        tg.start_soon(run)
        tg.start_soon(run)
    assert any("排隊逾時" in o for o in outcomes)
    assert any("超過 1 秒" in o for o in outcomes)
    assert len(fake_powerbi["requests"]) == 1


def test_settings_validation_is_all_or_nothing(client, admin_token):
    before = client.get("/api/admin/settings", headers=_headers(admin_token)).json()
    assert set(before["query_execution_counts"]) == {"edge", "server"}

    res = _put_settings(client, admin_token, {"server_query_max_rows": 5, "server_query_max_concurrency": 0})
    assert res.status_code == 422
    for bad in ({"no_such_key": 1}, {"default_query_execution": "cloud"}, {"server_query_timeout_seconds": "60"}):
        assert _put_settings(client, admin_token, bad).status_code == 422

    after = client.get("/api/admin/settings", headers=_headers(admin_token)).json()
    assert after["values"] == before["values"]


def test_default_mode_applies_to_new_registrations_only(client, admin_token):
    assert _put_settings(client, admin_token, {"default_query_execution": "server"}).status_code == 200
    try:
        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        assert client.post("/auth/register", json={"email": email, "password": "testpass123"}).status_code == 201
    finally:
        _put_settings(client, admin_token, {"default_query_execution": "edge"})
    users = client.get("/api/admin/users", headers=_headers(admin_token)).json()
    assert next(u for u in users if u["email"] == email)["query_execution"] == "server"
