"""Azure AD client secret 到期日追蹤。

Azure 的 client secret 最長 24 個月，而且到期時 Azure 不會主動通知——症狀是使用者
突然查不了、錯誤訊息看不出原因。管理員設定憑證時一併記下到期日，列表才能提前警示。
"""

import uuid
from datetime import datetime, timedelta


def _register_and_get_id(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    email = f"secret-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/auth/register", json={"email": email, "password": "testpass123"}).status_code == 201
    users = client.get("/api/admin/users", headers=headers).json()
    return next(u["id"] for u in users if u["email"] == email)


def test_secret_expiry_is_stored_and_returned(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    user_id = _register_and_get_id(client, admin_token)

    expires = (datetime.utcnow() + timedelta(days=180)).replace(microsecond=0)
    res = client.patch(f"/api/admin/users/{user_id}/credentials", headers=headers, json={
        "tenant_id": "t", "client_id": "c", "client_secret": "s",
        "client_secret_expires_at": expires.isoformat(),
    })
    assert res.status_code == 200

    row = next(u for u in client.get("/api/admin/users", headers=headers).json() if u["id"] == user_id)
    assert row["has_credentials"] is True
    assert row["client_secret_expires_at"].startswith(expires.date().isoformat())


def test_secret_expiry_is_optional(client, admin_token):
    """沒填到期日仍要能正常設定憑證——不是所有人都會維護這欄。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    user_id = _register_and_get_id(client, admin_token)

    res = client.patch(f"/api/admin/users/{user_id}/credentials", headers=headers, json={
        "tenant_id": "t", "client_id": "c", "client_secret": "s",
    })
    assert res.status_code == 200

    row = next(u for u in client.get("/api/admin/users", headers=headers).json() if u["id"] == user_id)
    assert row["has_credentials"] is True
    assert row["client_secret_expires_at"] is None
