"""管理員在 /admin/settings 調整的系統參數。

每個設定都有預設值，DB 沒有那一列就用預設值，所以新增設定不需要 migration。
值存在 `system_settings` 表（見 models.SystemSetting），每次需要時現讀——管理員
改完立刻生效，不需要重啟服務；這些讀取量很小（一次查詢讀一次），不值得另做快取。
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import SystemSetting

QUERY_EXECUTION_MODES = ("edge", "server")


@dataclass(frozen=True)
class _IntSetting:
    default: int
    min: int
    max: int

    def validate(self, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("必須是整數")
        if not self.min <= value <= self.max:
            raise ValueError(f"必須介於 {self.min} 到 {self.max} 之間")
        return value


@dataclass(frozen=True)
class _ChoiceSetting:
    default: str
    choices: tuple[str, ...]

    def validate(self, value: Any) -> str:
        if value not in self.choices:
            raise ValueError(f"必須是 {' / '.join(self.choices)} 其中之一")
        return value


SETTINGS: dict[str, _IntSetting | _ChoiceSetting] = {
    # 同時進行中的 server 查詢上限，超過的請求排隊。小 VM 上每個查詢都要把 Power BI
    # 回應整包讀進記憶體，訂太高容易在尖峰時把記憶體吃光。
    "server_query_max_concurrency": _IntSetting(default=4, min=1, max=32),
    # 每個結果表最多回傳幾列給 AI。結果會整包進入對話上下文，太大會塞爆 context，
    # AI 看到 truncated=true 會自己改成彙總或加篩選。
    "server_query_max_rows": _IntSetting(default=1000, min=1, max=10000),
    # 含排隊等待時間。Power BI executeQueries 一般幾秒內回應，超過通常代表 DAX 太重。
    "server_query_timeout_seconds": _IntSetting(default=60, min=5, max=300),
    # 新註冊使用者的查詢方式。既有使用者不受影響，要改請到使用者管理批次切換。
    "default_query_execution": _ChoiceSetting(default="edge", choices=QUERY_EXECUTION_MODES),
}


def get_setting(db: Session, key: str) -> Any:
    spec = SETTINGS[key]
    row = db.get(SystemSetting, key)
    if row is None:
        return spec.default
    try:
        return spec.validate(row.value)
    except ValueError:
        # DB 裡的值不合法（例如設定範圍改過）時回退預設，不讓一筆壞資料弄掛查詢
        return spec.default


def get_all_settings(db: Session) -> dict[str, Any]:
    return {key: get_setting(db, key) for key in SETTINGS}


def update_settings(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    """全部驗證通過才寫入（任一個不合法就丟 ValueError、什麼都不改）。呼叫端負責 commit。"""
    validated = {}
    for key, value in values.items():
        spec = SETTINGS.get(key)
        if spec is None:
            raise ValueError(f"未知的設定：{key}")
        try:
            validated[key] = spec.validate(value)
        except ValueError as e:
            raise ValueError(f"{key} {e}") from None
    for key, value in validated.items():
        row = db.get(SystemSetting, key)
        if row is None:
            db.add(SystemSetting(key=key, value=value))
        else:
            row.value = value
    return validated
