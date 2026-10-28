"""手動 OAuth client 註冊：給不會自己做 Dynamic Client Registration、要使用者填
「OAuth 用戶端 ID」的 MCP client（例如 Gemini 網頁版）。使用者在 /mcp-tokens 貼上
該 client 的重新導向 URI，拿到 client_id，之後走一般的 authorize + PKCE 流程。"""

import base64
import hashlib
import secrets
import uuid


def _user_headers(client, email, password):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _pkce_pair():
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _unique_redirect_uri():
    return f"https://gemini.example.com/callback/{uuid.uuid4().hex[:8]}"


def test_same_redirect_uri_returns_same_client_id(client, active_user):
    headers = _user_headers(client, *active_user)
    uri = _unique_redirect_uri()

    first = client.post("/auth/oauth-clients", headers=headers, json={"redirect_uri": uri})
    assert first.status_code == 200
    second = client.post("/auth/oauth-clients", headers=headers, json={"redirect_uri": f"  {uri}  "})
    assert second.status_code == 200
    assert first.json()["client_id"] == second.json()["client_id"]


def test_reuses_client_registered_via_dcr(client, active_user):
    uri = _unique_redirect_uri()
    res = client.post("/oauth/register", json={"redirect_uris": [uri], "client_name": "DCR"})
    dcr_client_id = res.json()["client_id"]

    headers = _user_headers(client, *active_user)
    res = client.post("/auth/oauth-clients", headers=headers, json={"redirect_uri": uri})
    assert res.json()["client_id"] == dcr_client_id


def test_rejects_invalid_redirect_uri(client, active_user):
    headers = _user_headers(client, *active_user)
    for bad in ["not-a-url", "http://evil.example.com/cb", "javascript:alert(1)", ""]:
        res = client.post("/auth/oauth-clients", headers=headers, json={"redirect_uri": bad})
        assert res.status_code == 400, bad


def test_allows_localhost_http(client, active_user):
    headers = _user_headers(client, *active_user)
    res = client.post("/auth/oauth-clients", headers=headers,
                      json={"redirect_uri": f"http://localhost:7777/{uuid.uuid4().hex[:8]}"})
    assert res.status_code == 200


def test_requires_login(client):
    res = client.post("/auth/oauth-clients", json={"redirect_uri": _unique_redirect_uri()})
    assert res.status_code in (401, 403)


def test_full_flow_with_client_id_in_basic_auth(client, active_user):
    """Gemini 這類 client 換 token 時常把 client_id/secret 放在 HTTP Basic 標頭，
    表單裡不帶 client_id——server 要能從標頭取出 client_id，密鑰則忽略。"""
    email, password = active_user
    headers = _user_headers(client, email, password)
    uri = _unique_redirect_uri()
    client_id = client.post("/auth/oauth-clients", headers=headers,
                            json={"redirect_uri": uri}).json()["client_id"]

    verifier, challenge = _pkce_pair()
    res = client.post("/oauth/authorize", data={
        "response_type": "code", "client_id": client_id, "redirect_uri": uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s", "scope": "",
        "email": email, "password": password, "action": "approve",
    }, follow_redirects=False)
    assert res.status_code == 302
    code = res.headers["location"].split("code=")[1].split("&")[0]

    basic = base64.b64encode(f"{client_id}:anything-or-empty".encode()).decode()
    res = client.post("/oauth/token", headers={"Authorization": f"Basic {basic}"}, data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": uri, "code_verifier": verifier,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]

    # refresh 也要能走 Basic
    res = client.post("/oauth/token", headers={"Authorization": f"Basic {basic}"}, data={
        "grant_type": "refresh_token", "refresh_token": body["refresh_token"],
    })
    assert res.status_code == 200


def test_basic_auth_client_id_must_match_code(client, active_user, oauth_client):
    """標頭裡的 client_id 不能拿來冒用別的 client 拿到的 code。"""
    email, password = active_user
    client_id, redirect_uri = oauth_client
    verifier, challenge = _pkce_pair()
    res = client.post("/oauth/authorize", data={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s", "scope": "",
        "email": email, "password": password, "action": "approve",
    }, follow_redirects=False)
    code = res.headers["location"].split("code=")[1].split("&")[0]

    basic = base64.b64encode(b"some-other-client:x").decode()
    res = client.post("/oauth/token", headers={"Authorization": f"Basic {basic}"}, data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "code_verifier": verifier,
    })
    assert res.status_code == 400
