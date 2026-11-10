"""篩選欄位別名：v1.5 起每組除了欄位值的別名（values[].aliases），還有欄位本身的別名（aliases）。"""

import pytest

from tests.test_model_detail_cache import _get_detail


def test_column_level_aliases_are_saved(client, admin_token, mcp_access_token):
    _, pbi_config_id, _ = mcp_access_token
    headers = {"Authorization": f"Bearer {admin_token}"}
    aliases = [{"table": "Orders", "column": "region", "aliases": ["地區", "區域"], "values": []}]

    res = client.patch(f"/api/admin/pbi-configs/{pbi_config_id}", headers=headers, json={"column_aliases": aliases})
    assert res.status_code == 200

    row = client.get(f"/api/admin/pbi-configs/{pbi_config_id}", headers=headers).json()
    assert row["column_aliases"] == aliases


@pytest.mark.anyio
async def test_old_data_without_column_aliases_key_is_backfilled(live_server, mcp_access_token):
    """v1.5 以前存的資料沒有 aliases 這個 key，get_model_detail 要補成空陣列，skill 端不用判斷。"""
    from app.database import SessionLocal
    from app.models import PbiConfig

    access_token, pbi_config_id, _ = mcp_access_token
    with SessionLocal() as db:
        config = db.query(PbiConfig).filter(PbiConfig.id == pbi_config_id).first()
        config.column_aliases = [{"table": "Orders", "column": "region", "values": [{"value": "North", "aliases": ["北區"]}]}]
        db.commit()

    detail = await _get_detail(live_server, access_token, pbi_config_id)
    assert detail["column_aliases"] == [{
        "table": "Orders",
        "column": "region",
        "aliases": [],
        "values": [{"value": "North", "aliases": ["北區"]}],
    }]
