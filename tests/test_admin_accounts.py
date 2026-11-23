"""管理員帳號：一般使用者帳號 + is_admin，可用帳密登入後台（Google 登入見 test_google_login.py）。"""

import pytest


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _user_id(client, admin_token, email):
    users = client.get("/api/admin/users", headers=_headers(admin_token)).json()
    return next(u["id"] for u in users if u["email"] == email)


def _password_login(client, email, password):
    return client.post("/api/admin/login/password", json={"email": email, "password": password})


def test_only_admin_accounts_can_log_in(client, admin_token, active_user):
    email, password = active_user
    res = _password_login(client, email, password)
    assert res.status_code == 403 and "管理後台權限" in res.json()["detail"]

    user_id = _user_id(client, admin_token, email)
    assert client.patch(f"/api/admin/users/{user_id}/admin", headers=_headers(admin_token),
                        json={"is_admin": True}).status_code == 200
    token = _password_login(client, email, password).json()["access_token"]
    assert client.get("/api/admin/users", headers=_headers(token)).status_code == 200

    # 不能拿掉自己的權限
    res = client.patch(f"/api/admin/users/{user_id}/admin", headers=_headers(token), json={"is_admin": False})
    assert res.status_code == 400

    # 停用後就不能登入後台
    client.patch("/api/admin/users/activate", headers=_headers(admin_token), json={"email": email, "is_active": False})
    res = _password_login(client, email, password)
    assert res.status_code == 403 and "停用" in res.json()["detail"]


def test_wrong_password_counts_toward_lockout(client, admin_token, active_user):
    email, password = active_user
    client.patch(f"/api/admin/users/{_user_id(client, admin_token, email)}/admin",
                 headers=_headers(admin_token), json={"is_admin": True})
    for _ in range(5):
        assert _password_login(client, email, "wrong").status_code == 401
    assert _password_login(client, email, password).status_code == 403
    # 同一組計數：使用者登入也被鎖
    assert client.post("/auth/login", json={"email": email, "password": password}).status_code == 403


@pytest.mark.parametrize("secret, status", [("test-admin-secret", 200), ("nope", 401)])
def test_admin_secret_still_works(client, secret, status):
    assert client.post("/api/admin/login", json={"secret": secret}).status_code == status
