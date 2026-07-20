import base64
import hashlib
import os
import secrets
import tempfile
import threading
import time
import uuid

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ.setdefault("SERVER_JWT_SECRET", "test-secret-" + "a" * 60)
os.environ.setdefault("ADMIN_SECRET", "test-admin-secret")
os.environ["SITE_DOMAIN"] = ""

import httpx
import pytest
import uvicorn

from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def live_server():
    """
    真的用 uvicorn 起一個 server（而不是用 TestClient 的假 ASGI transport），
    因為 MCP 的 StreamableHTTPSessionManager 是 singleton、只能被 run() 一次，
    如果同時有 TestClient 跟另一個 ASGI transport 各自觸發一次 app 的 lifespan
    會搶著初始化同一個 session manager 而炸掉。統一走真實網路請求最單純。
    """
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def client(live_server):
    with httpx.Client(base_url=live_server) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    res = client.post("/api/admin/login", json={"secret": os.environ["ADMIN_SECRET"]})
    assert res.status_code == 200
    return res.json()["access_token"]


@pytest.fixture
def active_user(client, admin_token):
    """註冊並開通一個帳號，回傳 (email, password)。"""
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    password = "testpass123"
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201
    res = client.patch(
        "/api/admin/users/activate",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": email, "is_active": True},
    )
    assert res.status_code == 200
    return email, password


@pytest.fixture
def oauth_client(client):
    """透過 DCR 註冊一個 OAuth client，回傳 (client_id, redirect_uri)。"""
    redirect_uri = "https://claude.ai/api/mcp/auth_callback"
    res = client.post("/oauth/register", json={
        "redirect_uris": [redirect_uri],
        "client_name": "Test Client",
    })
    assert res.status_code == 201
    return res.json()["client_id"], redirect_uri


def _pkce_pair():
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@pytest.fixture
def mcp_access_token(client, admin_token, active_user, oauth_client):
    """
    完整跑一次 OAuth flow 拿到 MCP access token，並先透過 admin API 建一個
    PBI 設定、指派給測試使用者、上傳一份簡化語意模型，回傳 (access_token, pbi_config_id)。
    """
    email, password = active_user
    client_id, redirect_uri = oauth_client
    headers = {"Authorization": f"Bearer {admin_token}"}

    res = client.post("/api/admin/pbi-configs", headers=headers, json={
        "name": f"test-config-{uuid.uuid4().hex[:8]}",
        "workspace_id": "ws-test",
        "dataset_id": "ds-test",
    })
    assert res.status_code == 201
    pbi_config_id = res.json()["id"]

    res = client.get("/api/admin/users", headers=headers)
    user_id = next(u["id"] for u in res.json() if u["email"] == email)
    res = client.put(f"/api/admin/users/{user_id}/pbi-configs", headers=headers, json={
        "pbi_config_ids": [pbi_config_id],
    })
    assert res.status_code == 200

    res = client.post("/api/admin/model/upload", headers=headers, json={
        "pbi_config_id": pbi_config_id,
        "name": "v1",
        "model_description": None,
        "data": {
            "relationships": [],
            "tables": [{
                "name": "TestTable",
                "columns": [{"name": "id", "dataType": "Int64", "description": ""}],
                "measures": [{"name": "Total", "expression": "SUM(TestTable[id])", "description": ""}],
            }],
        },
    })
    assert res.status_code == 201

    verifier, challenge = _pkce_pair()
    res = client.post("/oauth/authorize", data={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "",
        "email": email, "password": password, "action": "approve",
    }, follow_redirects=False)
    assert res.status_code == 302
    code = res.headers["location"].split("code=")[1].split("&")[0]

    res = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "client_id": client_id, "code_verifier": verifier,
    })
    assert res.status_code == 200
    access_token = res.json()["access_token"]

    return access_token, pbi_config_id
