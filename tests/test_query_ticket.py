"""一次性 query ticket：MCP 的 get_query_ticket 只發 ticket 不發 token，
真正的 Power BI access token 要由呼叫端腳本拿 ticket 去 /api/ticket/redeem 換，
目的是讓 token 不會出現在 MCP tool 的回傳值（也就不會進入對話上下文）。"""

import json
from datetime import datetime, timedelta

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

FAKE_TOKEN = "fake-azure-token"


@pytest.fixture
def fake_azure(monkeypatch):
    """mock 掉真正打 Azure AD 的 acquire_powerbi_token。

    要 patch 在 app.routers.ticket 這個命名空間裡——redeem 端點是用
    `from app.routers.credential import acquire_powerbi_token` 把函式物件直接
    import 進自己的命名空間，patch credential 模組本身沒有用。
    """
    import app.routers.ticket as ticket_module

    def fake_acquire_powerbi_token(user):
        return {"access_token": FAKE_TOKEN, "expires_in": 3599}

    monkeypatch.setattr(ticket_module, "acquire_powerbi_token", fake_acquire_powerbi_token)


def _set_credentials(client, admin_token, user_id):
    res = client.patch(
        f"/api/admin/users/{user_id}/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"tenant_id": "test-tenant", "client_id": "test-client", "client_secret": "test-secret"},
    )
    assert res.status_code == 200


async def _issue_ticket(live_server, access_token, pbi_config_id):
    async with streamablehttp_client(
        f"{live_server}/mcp/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("get_query_ticket", {"pbi_config_id": pbi_config_id})
            assert not result.isError
            return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_get_query_ticket_does_not_return_access_token(
    live_server, client, admin_token, mcp_access_token,
):
    """這是整個功能的重點：MCP tool 的回傳值裡不能有任何 access token。"""
    access_token, pbi_config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)

    payload = await _issue_ticket(live_server, access_token, pbi_config_id)

    assert "access_token" not in payload
    assert payload["ticket"]
    assert payload["redeem_url"].endswith("/api/ticket/redeem")
    assert payload["expires_in"] > 0
    # ticket 必須是不含語意的隨機字串，不能夾帶使用者或設定的識別資訊
    assert user_id not in payload["ticket"]
    assert pbi_config_id not in payload["ticket"]


@pytest.mark.anyio
async def test_redeem_ticket_returns_token_once(
    live_server, client, admin_token, mcp_access_token, fake_azure,
):
    access_token, pbi_config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    payload = await _issue_ticket(live_server, access_token, pbi_config_id)

    res = client.post("/api/ticket/redeem", json={"ticket": payload["ticket"]})
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"] == FAKE_TOKEN
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3599
    # 沿用既有設計：workspace_id/dataset_id 從 get_model_detail 拿，這裡不重複回傳
    assert "workspace_id" not in body
    assert "dataset_id" not in body

    # 第二次用同一張 ticket 必須失敗（單次使用）
    res = client.post("/api/ticket/redeem", json={"ticket": payload["ticket"]})
    assert res.status_code == 401


def test_redeem_invalid_ticket(client):
    res = client.post("/api/ticket/redeem", json={"ticket": "definitely-not-a-real-ticket"})
    assert res.status_code == 401


@pytest.mark.anyio
async def test_redeem_expired_ticket(
    live_server, client, admin_token, mcp_access_token, fake_azure,
):
    from app.database import SessionLocal
    from app.models import AccessTicket
    from app.security import hash_opaque_token

    access_token, pbi_config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    payload = await _issue_ticket(live_server, access_token, pbi_config_id)

    # 直接把到期時間改到過去，避免測試真的等 60 秒
    with SessionLocal() as db:
        row = db.query(AccessTicket).filter(
            AccessTicket.token_hash == hash_opaque_token(payload["ticket"])
        ).first()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()

    res = client.post("/api/ticket/redeem", json={"ticket": payload["ticket"]})
    assert res.status_code == 401
    assert "過期" in res.json()["detail"]


@pytest.mark.anyio
async def test_redeem_rejected_after_account_deactivated(
    live_server, client, admin_token, mcp_access_token, fake_azure,
):
    """ticket 發出後帳號才被停用，兌換時仍要擋下來——ticket 不能變成繞過停用的後門。"""
    access_token, pbi_config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    payload = await _issue_ticket(live_server, access_token, pbi_config_id)

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    users_res = client.get("/api/admin/users", headers=admin_headers)
    email = next(u["email"] for u in users_res.json() if u["id"] == user_id)
    res = client.patch("/api/admin/users/activate", headers=admin_headers,
                       json={"email": email, "is_active": False})
    assert res.status_code == 200

    res = client.post("/api/ticket/redeem", json={"ticket": payload["ticket"]})
    assert res.status_code == 403


@pytest.mark.anyio
async def test_redeem_is_recorded_in_access_logs(
    live_server, client, admin_token, mcp_access_token, fake_azure,
):
    access_token, pbi_config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    payload = await _issue_ticket(live_server, access_token, pbi_config_id)

    res = client.post("/api/ticket/redeem", json={"ticket": payload["ticket"]})
    assert res.status_code == 200

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    users_res = client.get("/api/admin/users", headers=admin_headers)
    email = next(u["email"] for u in users_res.json() if u["id"] == user_id)
    logs = client.get("/api/admin/access-logs", headers=admin_headers,
                      params={"email": email, "auth_method": "ticket"}).json()
    assert any(l["path"] == "/api/ticket/redeem" for l in logs)
