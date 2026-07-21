"""帳號登入失敗鎖定機制：/auth/login 與 /oauth/authorize 共用同一套計數，
累積 5 次密碼錯誤後鎖定，只能由管理員解鎖。"""

from tests.conftest import _pkce_pair


def _get_user_id(client, admin_token, email):
    res = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    return next(u["id"] for u in res.json() if u["email"] == email)


def test_login_locks_after_five_failures(client, active_user):
    email, password = active_user
    for _ in range(5):
        res = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert res.status_code == 401

    # 第 6 次，就算密碼是對的也應該被鎖住，而不是登入成功
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 403
    assert "鎖定" in res.json()["detail"]


def test_successful_login_resets_counter(client, active_user):
    email, password = active_user
    for _ in range(3):
        res = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert res.status_code == 401

    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200

    # 重置過後，再錯 3 次不應該達到鎖定門檻（總共才 3 次，未滿 5）
    for _ in range(3):
        res = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert res.status_code == 401
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200


def test_oauth_authorize_shares_lockout_with_auth_login(client, active_user, oauth_client):
    """從 /auth/login 累積失敗次數，應該也會讓 /oauth/authorize 的登入被鎖住（共用同一個計數）。"""
    email, password = active_user
    client_id, redirect_uri = oauth_client
    _, challenge = _pkce_pair()

    for _ in range(5):
        res = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert res.status_code == 401

    res = client.post("/oauth/authorize", data={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "",
        "email": email, "password": password, "action": "approve",
    })
    assert res.status_code == 403
    assert "鎖定" in res.text


def test_admin_can_unlock_user(client, admin_token, active_user):
    email, password = active_user
    headers = {"Authorization": f"Bearer {admin_token}"}

    for _ in range(5):
        client.post("/auth/login", json={"email": email, "password": "wrong"})

    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 403

    user_id = _get_user_id(client, admin_token, email)

    # 解鎖前，users 清單要能看到 is_locked = true
    res = client.get("/api/admin/users", headers=headers)
    user_row = next(u for u in res.json() if u["email"] == email)
    assert user_row["is_locked"] is True

    res = client.post(f"/api/admin/users/{user_id}/unlock", headers=headers)
    assert res.status_code == 200

    res = client.get("/api/admin/users", headers=headers)
    user_row = next(u for u in res.json() if u["email"] == email)
    assert user_row["is_locked"] is False

    # 解鎖後應該能正常登入
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
