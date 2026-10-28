"""查詢權限檢測：用使用者的 SP 對已指派模型跑一個最小查詢，結果記在「使用者 × 模型」上。
Azure AD 與 Power BI 都 mock 掉，測的是錯誤翻譯、結果寫回、以及何時要把結果重置成未檢測。"""

import httpx
import pytest
from fastapi import HTTPException

import app.query_check as query_check


@pytest.fixture
def fake_powerbi(monkeypatch):
    """預設 Azure AD 與 Power BI 都成功；測試可以改 state 模擬各種失敗。"""
    state = {"aad_error": None, "pbi_status": 200, "pbi_body": '{"results": []}', "calls": []}

    def fake_acquire(user):
        if state["aad_error"]:
            raise HTTPException(status_code=502, detail=f"Azure AD 驗證失敗：{state['aad_error']}")
        return {"access_token": "fake"}

    def fake_post(url, **kwargs):
        state["calls"].append((url, kwargs["json"]))
        return httpx.Response(state["pbi_status"], text=state["pbi_body"])

    monkeypatch.setattr(query_check, "acquire_powerbi_token", fake_acquire)
    monkeypatch.setattr(query_check.httpx, "post", fake_post)
    return state


def _admin(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _set_credentials(client, admin_token, user_id):
    res = client.patch(f"/api/admin/users/{user_id}/credentials", headers=_admin(admin_token),
                       json={"tenant_id": "t", "client_id": "c", "client_secret": "s"})
    assert res.status_code == 200


def _checks(client, admin_token, user_id):
    user = next(u for u in client.get("/api/admin/users", headers=_admin(admin_token)).json() if u["id"] == user_id)
    return {c["pbi_config_id"]: c for c in user["pbi_config_checks"]}


def _run(client, admin_token, user_id):
    res = client.post(f"/api/admin/users/{user_id}/query-check", headers=_admin(admin_token), json={})
    assert res.status_code == 200
    return {r["pbi_config_id"]: r for r in res.json()}


def test_check_without_credentials(client, admin_token, mcp_access_token, fake_powerbi):
    _, config_id, user_id = mcp_access_token
    result = _run(client, admin_token, user_id)[config_id]
    assert result["check_status"] == "failed"
    assert result["check_message"] == "尚未設定 Azure AD 憑證"
    assert fake_powerbi["calls"] == []


def test_check_ok_is_saved_and_listed(client, admin_token, mcp_access_token, fake_powerbi):
    _, config_id, user_id = mcp_access_token
    assert _checks(client, admin_token, user_id)[config_id]["check_status"] is None  # 未檢測

    _set_credentials(client, admin_token, user_id)
    result = _run(client, admin_token, user_id)[config_id]
    assert result["check_status"] == "ok"
    url, body = fake_powerbi["calls"][0]
    assert url.endswith("/groups/ws-test/datasets/ds-test/executeQueries")
    assert body == {"queries": [{"query": 'EVALUATE ROW("ok", 1)'}]}

    listed = _checks(client, admin_token, user_id)[config_id]
    assert listed["check_status"] == "ok" and listed["checked_at"]


@pytest.mark.parametrize("aad_error, expected", [
    ("AADSTS7000215: Invalid client secret provided.", "祕密識別碼"),
    ("AADSTS700016: Application not found.", "Client ID 錯誤"),
    ("AADSTS90002: Tenant not found.", "Tenant ID 錯誤"),
    ("something unexpected", "向 Azure AD 換發 token 失敗"),
])
def test_azure_errors_are_translated(client, admin_token, mcp_access_token, fake_powerbi, aad_error, expected):
    _, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    fake_powerbi["aad_error"] = aad_error
    message = _run(client, admin_token, user_id)[config_id]["check_message"]
    assert expected in message
    assert aad_error in message  # 原始錯誤也要保留，給管理員貼給 Azure 那邊的人


@pytest.mark.parametrize("status, expected", [
    (401, "服務主體沒有這個 workspace 的權限"),
    (404, "找不到 workspace 或 dataset"),
    (500, "Power BI 回應 HTTP 500"),
])
def test_powerbi_errors_are_translated(client, admin_token, mcp_access_token, fake_powerbi, status, expected):
    _, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    fake_powerbi["pbi_status"] = status
    fake_powerbi["pbi_body"] = '{"error":{"code":"PowerBINotAuthorizedException"}}'
    result = _run(client, admin_token, user_id)[config_id]
    assert result["check_status"] == "failed"
    assert expected in result["check_message"]
    assert "PowerBINotAuthorizedException" in result["check_message"]


def test_results_reset_when_credentials_change(client, admin_token, mcp_access_token, fake_powerbi):
    _, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    _run(client, admin_token, user_id)
    _set_credentials(client, admin_token, user_id)
    assert _checks(client, admin_token, user_id)[config_id]["check_status"] is None


def test_results_reset_only_when_dataset_target_changes(client, admin_token, mcp_access_token, fake_powerbi):
    _, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    _run(client, admin_token, user_id)

    # 改篩選規則、或送出同樣的 workspace_id：不影響能不能查，結果保留
    res = client.patch(f"/api/admin/pbi-configs/{config_id}", headers=_admin(admin_token),
                       json={"workspace_id": "ws-test", "filters": []})
    assert res.status_code == 200
    assert _checks(client, admin_token, user_id)[config_id]["check_status"] == "ok"

    res = client.patch(f"/api/admin/pbi-configs/{config_id}", headers=_admin(admin_token),
                       json={"dataset_id": "ds-new"})
    assert res.status_code == 200
    assert _checks(client, admin_token, user_id)[config_id]["check_status"] is None

    _run(client, admin_token, user_id)
    res = client.patch("/api/admin/pbi-configs/batch-update", headers=_admin(admin_token),
                       json={"config_ids": [config_id], "workspace_id": "ws-new"})
    assert res.status_code == 200
    assert _checks(client, admin_token, user_id)[config_id]["check_status"] is None


def test_reassigning_keeps_results_of_unchanged_models(client, admin_token, mcp_access_token, fake_powerbi):
    _, config_id, user_id = mcp_access_token
    _set_credentials(client, admin_token, user_id)
    _run(client, admin_token, user_id)

    res = client.post("/api/admin/pbi-configs", headers=_admin(admin_token), json={"name": f"extra-{user_id[:8]}"})
    extra_id = res.json()["id"]
    res = client.put(f"/api/admin/users/{user_id}/pbi-configs", headers=_admin(admin_token),
                     json={"pbi_config_ids": [config_id, extra_id]})
    assert res.status_code == 200
    checks = _checks(client, admin_token, user_id)
    assert checks[config_id]["check_status"] == "ok"  # 原本的保留
    assert checks[extra_id]["check_status"] is None  # 新指派的未檢測

    # 只檢測指定的那一個
    res = client.post(f"/api/admin/users/{user_id}/query-check", headers=_admin(admin_token),
                      json={"pbi_config_ids": [extra_id]})
    assert [r["pbi_config_id"] for r in res.json()] == [extra_id]
    assert res.json()[0]["check_message"] == "PBI 設定缺少 Workspace ID 或 Dataset ID"
