"""PBI 設定的複製（連同最新語意模型一起複製）與批次修改
（僅 workspace_id/dataset_id/column_aliases，filters/query_modes 刻意不開放批次覆蓋）。"""

import uuid

SAMPLE_FILTERS = [
    {
        "filterId": "exclude-return-orders",
        "name": "排除退貨單",
        "description": None,
        "alwaysApply": True,
        "overrideDefaults": False,
        "contextKeywords": [],
        "filters": [{"description": "排除退貨單", "expression": 'Orders[order_type] <> "return_order"', "requiredTable": None}],
    }
]
SAMPLE_QUERY_MODES = [
    {"mode_id": "summary", "name": "摘要模式", "description": None, "tables": ["TestTable"], "filters": []}
]
SAMPLE_COLUMN_ALIASES = [
    {"table": "TestTable", "column": "region", "values": [{"value": "North", "aliases": ["北區"]}]}
]


def _create_config_with_model(client, headers, name):
    res = client.post("/api/admin/pbi-configs", headers=headers, json={
        "name": name, "workspace_id": "ws-1", "dataset_id": "ds-1",
    })
    config_id = res.json()["id"]
    client.patch(f"/api/admin/pbi-configs/{config_id}", headers=headers, json={
        "filters": SAMPLE_FILTERS,
        "query_modes": SAMPLE_QUERY_MODES,
        "column_aliases": SAMPLE_COLUMN_ALIASES,
    })
    res = client.post("/api/admin/model/upload", headers=headers, json={
        "pbi_config_id": config_id,
        "name": "v1",
        "data": {
            "relationships": [],
            "tables": [{
                "name": "TestTable",
                "columns": [{"name": "id", "dataType": "Int64", "description": ""}],
                "measures": [],
            }],
        },
    })
    assert res.status_code == 201
    return config_id


def test_duplicate_pbi_config_copies_settings_and_latest_model(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    source_id = _create_config_with_model(client, headers, f"dup-src-{uuid.uuid4().hex[:8]}")

    new_name = f"dup-dst-{uuid.uuid4().hex[:8]}"
    res = client.post(f"/api/admin/pbi-configs/{source_id}/duplicate", headers=headers, json={"name": new_name})
    assert res.status_code == 201
    new_id = res.json()["id"]
    assert new_id != source_id

    res = client.get(f"/api/admin/pbi-configs/{new_id}", headers=headers)
    row = res.json()
    assert row["name"] == new_name
    assert row["workspace_id"] == "ws-1"
    assert row["dataset_id"] == "ds-1"
    assert row["filters"] == SAMPLE_FILTERS
    assert row["query_modes"] == SAMPLE_QUERY_MODES
    assert row["column_aliases"] == SAMPLE_COLUMN_ALIASES

    res = client.get("/api/admin/model/versions", headers=headers, params={"pbi_config_id": new_id})
    versions = res.json()
    assert len(versions) == 1
    assert versions[0]["model_version"] == 1
    assert versions[0]["table_count"] == 1

    # 複製後彼此獨立：改來源不影響複製出來的設定
    client.patch(f"/api/admin/pbi-configs/{source_id}", headers=headers, json={"workspace_id": "ws-changed"})
    res = client.get(f"/api/admin/pbi-configs/{new_id}", headers=headers)
    assert res.json()["workspace_id"] == "ws-1"


def test_duplicate_pbi_config_without_model_skips_model_copy(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/pbi-configs", headers=headers, json={"name": f"nomodel-{uuid.uuid4().hex[:8]}"})
    source_id = res.json()["id"]

    new_name = f"nomodel-dup-{uuid.uuid4().hex[:8]}"
    res = client.post(f"/api/admin/pbi-configs/{source_id}/duplicate", headers=headers, json={"name": new_name})
    assert res.status_code == 201
    new_id = res.json()["id"]

    res = client.get("/api/admin/model/versions", headers=headers, params={"pbi_config_id": new_id})
    assert res.json() == []


def test_duplicate_pbi_config_rejects_existing_name(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    source_id = _create_config_with_model(client, headers, f"dup-src-{uuid.uuid4().hex[:8]}")
    existing_name = f"dup-taken-{uuid.uuid4().hex[:8]}"
    res = client.post("/api/admin/pbi-configs", headers=headers, json={"name": existing_name})
    assert res.status_code == 201

    res = client.post(f"/api/admin/pbi-configs/{source_id}/duplicate", headers=headers, json={"name": existing_name})
    assert res.status_code == 409


def test_duplicate_pbi_config_404_for_missing_source(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/pbi-configs/does-not-exist/duplicate", headers=headers, json={"name": "x"})
    assert res.status_code == 404


def test_batch_update_pbi_configs_only_touches_specified_fields(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    id_a = _create_config_with_model(client, headers, f"batch-a-{uuid.uuid4().hex[:8]}")
    id_b = _create_config_with_model(client, headers, f"batch-b-{uuid.uuid4().hex[:8]}")

    new_aliases = [{"table": "TestTable", "column": "region", "values": [{"value": "South", "aliases": ["南區"]}]}]
    res = client.patch("/api/admin/pbi-configs/batch-update", headers=headers, json={
        "config_ids": [id_a, id_b],
        "workspace_id": "ws-shared",
        "dataset_id": "ds-shared",
        "column_aliases": new_aliases,
    })
    assert res.status_code == 200

    for cid in (id_a, id_b):
        row = client.get(f"/api/admin/pbi-configs/{cid}", headers=headers).json()
        assert row["workspace_id"] == "ws-shared"
        assert row["dataset_id"] == "ds-shared"
        assert row["column_aliases"] == new_aliases
        # filters/query_modes 不在批次修改的欄位範圍內，應該完全不變
        assert row["filters"] == SAMPLE_FILTERS
        assert row["query_modes"] == SAMPLE_QUERY_MODES


def test_batch_update_pbi_configs_partial_fields_leaves_others_untouched(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    config_id = _create_config_with_model(client, headers, f"batch-partial-{uuid.uuid4().hex[:8]}")

    res = client.patch("/api/admin/pbi-configs/batch-update", headers=headers, json={
        "config_ids": [config_id],
        "workspace_id": "ws-only",
    })
    assert res.status_code == 200

    row = client.get(f"/api/admin/pbi-configs/{config_id}", headers=headers).json()
    assert row["workspace_id"] == "ws-only"
    assert row["dataset_id"] == "ds-1"  # 沒帶 dataset_id，維持原值
    assert row["column_aliases"] == SAMPLE_COLUMN_ALIASES  # 沒帶 column_aliases，維持原值
