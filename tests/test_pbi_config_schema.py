"""詳情頁表單用的表名／欄位名清單：取最新一版語意模型，沒上傳過模型時回空清單。"""

import uuid

from tests.test_pbi_config_duplicate_batch import _create_config_with_model


def test_schema_returns_latest_model_tables_and_columns(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    config_id = _create_config_with_model(client, headers, f"schema-{uuid.uuid4().hex[:8]}")

    res = client.get(f"/api/admin/pbi-configs/{config_id}/schema", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["model_version"] == 1
    assert body["tables"] == [{"table": "TestTable", "columns": ["id"]}]


def test_schema_without_model_is_empty(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/pbi-configs", headers=headers, json={"name": f"schema-empty-{uuid.uuid4().hex[:8]}"})
    config_id = res.json()["id"]

    res = client.get(f"/api/admin/pbi-configs/{config_id}/schema", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"model_version": None, "tables": []}


def test_schema_unknown_config_is_404(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.get("/api/admin/pbi-configs/does-not-exist/schema", headers=headers)
    assert res.status_code == 404
