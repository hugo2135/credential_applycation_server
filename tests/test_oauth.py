import base64
import hashlib
import secrets


def _pkce_pair():
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def test_authorization_server_metadata(client):
    res = client.get("/.well-known/oauth-authorization-server")
    assert res.status_code == 200
    data = res.json()
    assert data["authorization_endpoint"].endswith("/oauth/authorize")
    assert data["token_endpoint"].endswith("/oauth/token")
    assert "S256" in data["code_challenge_methods_supported"]


def test_dynamic_client_registration(client):
    res = client.post("/oauth/register", json={
        "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
        "client_name": "Test",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["client_id"]
    assert data["token_endpoint_auth_method"] == "none"


def test_dynamic_client_registration_requires_redirect_uris(client):
    res = client.post("/oauth/register", json={"redirect_uris": []})
    assert res.status_code == 400


def test_authorize_page_renders(client, oauth_client):
    client_id, redirect_uri = oauth_client
    _, challenge = _pkce_pair()
    res = client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
    })
    assert res.status_code == 200
    assert "想要存取你的 PBI 語意模型資料" in res.text


def test_authorize_rejects_unregistered_redirect_uri(client, oauth_client):
    client_id, _ = oauth_client
    _, challenge = _pkce_pair()
    res = client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": "https://evil.example.com/cb",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
    })
    assert res.status_code == 400


def test_authorize_wrong_password_rejected(client, oauth_client, active_user):
    client_id, redirect_uri = oauth_client
    email, _ = active_user
    _, challenge = _pkce_pair()
    res = client.post("/oauth/authorize", data={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "",
        "email": email, "password": "wrong-password", "action": "approve",
    })
    assert res.status_code == 401
    assert "帳號或密碼錯誤" in res.text


def test_authorize_deny_redirects_with_error(client, oauth_client, active_user):
    client_id, redirect_uri = oauth_client
    email, password = active_user
    _, challenge = _pkce_pair()
    res = client.post("/oauth/authorize", data={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "",
        "email": email, "password": password, "action": "deny",
    }, follow_redirects=False)
    assert res.status_code == 302
    assert "error=access_denied" in res.headers["location"]


def test_full_authorization_code_and_refresh_flow(client, oauth_client, active_user):
    client_id, redirect_uri = oauth_client
    email, password = active_user
    verifier, challenge = _pkce_pair()

    res = client.post("/oauth/authorize", data={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "",
        "email": email, "password": password, "action": "approve",
    }, follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert location.startswith(redirect_uri)
    code = location.split("code=")[1].split("&")[0]

    # 錯的 code_verifier 應該被拒（PKCE）
    res = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "client_id": client_id, "code_verifier": "wrong-verifier",
    })
    assert res.status_code == 400

    # 正確的 code_verifier 應該換到 token
    res = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "client_id": client_id, "code_verifier": verifier,
    })
    assert res.status_code == 200
    tokens = res.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"] == "Bearer"

    # 同一個 code 不能重用（防重放）
    res = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "client_id": client_id, "code_verifier": verifier,
    })
    assert res.status_code == 400

    # refresh token 換新 access token，且輪換後舊 refresh token 失效
    old_refresh = tokens["refresh_token"]
    res = client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": old_refresh, "client_id": client_id,
    })
    assert res.status_code == 200
    new_tokens = res.json()
    assert new_tokens["refresh_token"] != old_refresh

    res = client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": old_refresh, "client_id": client_id,
    })
    assert res.status_code == 400
