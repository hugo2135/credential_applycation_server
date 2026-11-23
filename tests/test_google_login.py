"""Google 登入（v3.0）：使用者網頁、MCP 授權頁、管理後台三個入口，帳號以 sub 綁定。

Google 那一段（拿 code 換 id_token）用 monkeypatch 換掉，其餘從 /oauth/google/start 到
callback 都是真的 HTTP 往返，含 state cookie 與 nonce 檢查。
"""

import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from jose import jwt

import app.routers.google as google_router
from app.google_login import read_flow_state
from tests.conftest import _pkce_pair

DOMAIN = "corp.example"
CLIENT_ID = "google-client-id"


def _headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def google_enabled(client, admin_token):
    """啟用 Google 登入，測完還原（allowed_email_domains 會影響其他測試的帳密註冊）。"""
    original = client.get("/api/admin/settings", headers=_headers(admin_token)).json()["values"]
    res = client.put("/api/admin/settings", headers=_headers(admin_token), json={
        "google_login_enabled": True,
        "google_client_id": CLIENT_ID,
        "google_client_secret": "google-secret",
        "allowed_email_domains": [DOMAIN],
        "google_auto_activate": True,
        "google_auto_link": True,
        "google_admin_emails": [f"boss@{DOMAIN}"],
    })
    assert res.status_code == 200, res.text
    yield
    keys = ("google_login_enabled", "google_client_id", "allowed_email_domains",
            "google_auto_activate", "google_auto_link", "google_admin_emails")
    client.put("/api/admin/settings", headers=_headers(admin_token),
               json={**{k: original[k] for k in keys}, "google_client_secret": ""})


def _claims(email, sub=None, **overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": sub or uuid.uuid4().hex,
        "email": email,
        "email_verified": True,
        "hd": DOMAIN,
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _google_login(live_server, monkeypatch, flow, claims, start_params=None, nonce_override=None):
    """跑一次 start → (假的 Google) → callback，回傳 callback 的回應。"""
    with httpx.Client(base_url=live_server) as browser:
        res = browser.get("/oauth/google/start", params={"flow": flow, **(start_params or {})},
                          follow_redirects=False)
        assert res.status_code == 302, res.text
        google_url = urlparse(res.headers["location"])
        assert google_url.netloc == "accounts.google.com"
        query = parse_qs(google_url.query)
        assert query["scope"] == ["openid email"]
        state = query["state"][0]
        nonce = read_flow_state(browser.cookies["google_login_state"])["nonce"]

        id_token = jwt.encode({**claims, "nonce": nonce_override or nonce}, "unused", algorithm="HS256")
        monkeypatch.setattr(google_router, "fetch_id_token", lambda config, code, redirect_uri: id_token)
        return browser.get("/oauth/google/callback", params={"code": "c", "state": state},
                           follow_redirects=False)


def _fragment(res):
    assert res.status_code == 302, res.text
    return {k: v[0] for k, v in parse_qs(urlparse(res.headers["location"]).fragment).items()}


def _user(client, admin_token, email):
    users = client.get("/api/admin/users", headers=_headers(admin_token)).json()
    return next((u for u in users if u["email"] == email), None)


def test_new_user_is_created_active_and_linked(live_server, client, admin_token, google_enabled, monkeypatch):
    email = f"new-{uuid.uuid4().hex[:6]}@{DOMAIN}"
    fragment = _fragment(_google_login(live_server, monkeypatch, "user", _claims(email)))
    assert "google_linked" not in fragment and fragment["email"] == email

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {fragment['google_token']}"})
    assert me.status_code == 200 and me.json()["is_active"] is True
    user = _user(client, admin_token, email)
    assert user["google_linked"] and user["pbi_config_ids"] == [] and not user["has_credentials"]


@pytest.mark.parametrize("overrides, reason", [
    ({"hd": None}, "personal account"),
    ({"hd": "other.example"}, "other workspace"),
    ({"email_verified": False}, "unverified"),
    ({"aud": "someone-else"}, "token for another app"),
])
def test_rejected_identities(live_server, client, admin_token, google_enabled, monkeypatch, overrides, reason):
    email = f"x-{uuid.uuid4().hex[:6]}@{DOMAIN}"
    fragment = _fragment(_google_login(live_server, monkeypatch, "user", _claims(email, **overrides)))
    assert "google_error" in fragment and "google_token" not in fragment, reason
    assert _user(client, admin_token, email) is None


def test_nonce_mismatch_is_rejected(live_server, google_enabled, monkeypatch):
    claims = _claims(f"n-{uuid.uuid4().hex[:6]}@{DOMAIN}")
    fragment = _fragment(_google_login(live_server, monkeypatch, "user", claims, nonce_override="forged"))
    assert "google_error" in fragment


def test_callback_without_matching_state_cookie_is_rejected(client, google_enabled):
    res = client.get("/oauth/google/callback", params={"code": "c", "state": "whatever"}, follow_redirects=False)
    assert res.status_code == 400


def test_existing_account_is_linked_and_password_stops_working(
    live_server, client, admin_token, google_enabled, monkeypatch,
):
    email = f"old-{uuid.uuid4().hex[:6]}@{DOMAIN}"
    assert client.post("/auth/register", json={"email": email, "password": "testpass123"}).status_code == 201
    before = _user(client, admin_token, email)

    fragment = _fragment(_google_login(live_server, monkeypatch, "user", _claims(email)))
    assert fragment["google_linked"] == "1"
    after = _user(client, admin_token, email)
    # 綁定只寫 google_sub，不動開通狀態等其他欄位
    assert after["google_linked"] and after["is_active"] == before["is_active"] is False

    res = client.post("/auth/login", json={"email": email, "password": "testpass123"})
    assert res.status_code == 403 and "Google" in res.json()["detail"]

    # 管理員解除綁定後，原密碼恢復可用
    assert client.delete(f"/api/admin/users/{after['id']}/google-link", headers=_headers(admin_token)).status_code == 200
    assert client.post("/auth/login", json={"email": email, "password": "testpass123"}).status_code == 200


def test_auto_link_disabled_rejects_existing_email(live_server, client, admin_token, google_enabled, monkeypatch):
    email = f"nolink-{uuid.uuid4().hex[:6]}@{DOMAIN}"
    assert client.post("/auth/register", json={"email": email, "password": "testpass123"}).status_code == 201
    client.put("/api/admin/settings", headers=_headers(admin_token), json={"google_auto_link": False})

    fragment = _fragment(_google_login(live_server, monkeypatch, "user", _claims(email)))
    assert "google_error" in fragment
    assert not _user(client, admin_token, email)["google_linked"]


def test_email_bound_to_another_google_account_is_rejected(live_server, google_enabled, monkeypatch):
    email = f"reused-{uuid.uuid4().hex[:6]}@{DOMAIN}"
    assert "google_token" in _fragment(_google_login(live_server, monkeypatch, "user", _claims(email, sub="A")))
    # 同一個 sub 再登入照常
    assert "google_token" in _fragment(_google_login(live_server, monkeypatch, "user", _claims(email, sub="A")))
    # 同 email、不同 sub（例如離職者 email 重新分配）→ 不能繼承原帳號
    fragment = _fragment(_google_login(live_server, monkeypatch, "user", _claims(email, sub="B")))
    assert "google_error" in fragment and "已綁定其他" in fragment["google_error"]


def test_mcp_authorize_with_google(live_server, client, admin_token, oauth_client, google_enabled, monkeypatch):
    client_id, redirect_uri = oauth_client
    verifier, challenge = _pkce_pair()
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
              "code_challenge": challenge, "code_challenge_method": "S256", "state": "st", "scope": ""}

    page = client.get("/oauth/authorize", params=params)
    assert "/oauth/google/start?flow=mcp" in page.text and 'href="/register"' in page.text

    res = _google_login(live_server, monkeypatch, "mcp", _claims(f"mcp-{uuid.uuid4().hex[:6]}@{DOMAIN}"), params)
    assert res.status_code == 302
    location = urlparse(res.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == redirect_uri
    query = parse_qs(location.query)
    assert query["state"] == ["st"]

    token = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": query["code"][0],
        "redirect_uri": redirect_uri, "client_id": client_id, "code_verifier": verifier,
    })
    assert token.status_code == 200 and token.json()["access_token"]


def test_mcp_linking_shows_notice_before_continuing(
    live_server, client, admin_token, oauth_client, google_enabled, monkeypatch,
):
    client_id, redirect_uri = oauth_client
    _, challenge = _pkce_pair()
    email = f"mcplink-{uuid.uuid4().hex[:6]}@{DOMAIN}"
    assert client.post("/auth/register", json={"email": email, "password": "testpass123"}).status_code == 201
    client.patch("/api/admin/users/activate", headers=_headers(admin_token), json={"email": email, "is_active": True})

    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
              "code_challenge": challenge, "state": "st"}
    res = _google_login(live_server, monkeypatch, "mcp", _claims(email), params)
    assert res.status_code == 200
    assert "原本的密碼已經失效" in res.text and redirect_uri in res.text


def test_mcp_inactive_account_is_refused(live_server, client, admin_token, oauth_client, google_enabled, monkeypatch):
    client_id, redirect_uri = oauth_client
    _, challenge = _pkce_pair()
    client.put("/api/admin/settings", headers=_headers(admin_token), json={"google_auto_activate": False})
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
              "code_challenge": challenge, "state": "st"}
    res = _google_login(live_server, monkeypatch, "mcp", _claims(f"wait-{uuid.uuid4().hex[:6]}@{DOMAIN}"), params)
    assert res.status_code == 403 and "尚未開通" in res.text


def test_admin_login_with_google(live_server, client, google_enabled, monkeypatch):
    fragment = _fragment(_google_login(live_server, monkeypatch, "admin", _claims(f"boss@{DOMAIN}")))
    users = client.get("/api/admin/users", headers=_headers(fragment["google_token"]))
    assert users.status_code == 200

    fragment = _fragment(_google_login(live_server, monkeypatch, "admin", _claims(f"staff@{DOMAIN}")))
    assert "google_error" in fragment and "google_token" not in fragment


def test_disabled_google_login(client):
    assert client.get("/oauth/google/status").json() == {"enabled": False, "admin_enabled": False}
    res = client.get("/oauth/google/start", params={"flow": "user"}, follow_redirects=False)
    assert res.status_code == 302 and "google_error" in res.headers["location"]


def test_client_secret_is_write_only(client, admin_token, google_enabled):
    data = client.get("/api/admin/settings", headers=_headers(admin_token)).json()
    assert data["secrets"] == {"google_client_secret": True}
    assert "google-secret" not in str(data)
    assert data["google_redirect_uri"].endswith("/oauth/google/callback")
    assert client.get("/oauth/google/status").json() == {"enabled": True, "admin_enabled": True}

    # 不帶 secret 的更新不會清掉它
    client.put("/api/admin/settings", headers=_headers(admin_token), json={"google_auto_link": True})
    assert client.get("/api/admin/settings", headers=_headers(admin_token)).json()["secrets"]["google_client_secret"]


def test_settings_reject_bad_domains(client, admin_token):
    res = client.put("/api/admin/settings", headers=_headers(admin_token),
                     json={"allowed_email_domains": ["not a domain"]})
    assert res.status_code == 422
