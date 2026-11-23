"""管理員在 /admin/settings 調整的系統參數。

每個設定都有預設值，DB 沒有那一列就用預設值，所以新增設定不需要 migration。
值存在 `system_settings` 表（見 models.SystemSetting），每次需要時現讀——管理員
改完立刻生效，不需要重啟服務；這些讀取量很小（一次查詢讀一次），不值得另做快取。
"""

import os
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import SystemSetting
from app.security import decrypt_secret, encrypt_secret

QUERY_EXECUTION_MODES = ("edge", "server")

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


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


@dataclass(frozen=True)
class _BoolSetting:
    default: bool

    def validate(self, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("必須是 true 或 false")
        return value


@dataclass(frozen=True)
class _StrSetting:
    default: str
    max_length: int = 512

    def validate(self, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("必須是字串")
        value = value.strip()
        if len(value) > self.max_length:
            raise ValueError(f"長度不可超過 {self.max_length}")
        return value


@dataclass(frozen=True)
class _ListSetting:
    """字串清單（網域、email）。一律轉小寫、去重複；`env_fallback` 是 DB 還沒有值時
    沿用的舊環境變數（逗號分隔），讓搬到網頁設定之前已部署的環境行為不變。"""
    pattern: re.Pattern
    label: str
    env_fallback: str | None = None

    @property
    def default(self) -> list[str]:
        raw = os.getenv(self.env_fallback, "") if self.env_fallback else ""
        return [v for v in dict.fromkeys(s.strip().lower() for s in raw.split(",")) if v]

    def validate(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("必須是字串陣列")
        items = [v for v in dict.fromkeys(s.strip().lower() for s in value) if v]
        for item in items:
            if not self.pattern.match(item):
                raise ValueError(f"「{item}」不是合法的{self.label}")
        return items


SETTINGS: dict[str, Any] = {
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
    # 允許註冊的 email 網域，帳密註冊與 Google 登入共用。空清單時帳密註冊不限制（舊行為），
    # Google 登入則一律拒絕——Google 登入會自動開通帳號，不能在沒設網域時對所有人開放。
    "allowed_email_domains": _ListSetting(_DOMAIN_RE, "網域", env_fallback="ALLOWED_EMAIL_DOMAINS"),
    # ── Google 登入（見 app/google_login.py）。client secret 不在這裡，另外加密存（見 set_secret）
    "google_login_enabled": _BoolSetting(default=False),
    "google_client_id": _StrSetting(default=""),
    # Google 登入第一次遇到系統裡沒有的人時，建立的帳號是否直接開通（其他設定照預設，
    # 沒指派模型、沒填 Azure AD 憑證照樣查不了）。只在建立當下生效，之後不會再碰 is_active。
    "google_auto_activate": _BoolSetting(default=True),
    # 同 email 的既有帳號（還沒綁過 Google）是否自動綁定。關閉時這種人會被擋下，請他用帳密登入。
    "google_auto_link": _BoolSetting(default=True),
}

# 機密設定：加密後存在同一張表，只能寫入、API 永不回傳明文，畫面只看得到「已設定」。
SECRET_SETTINGS = ("google_client_secret",)


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
    """全部驗證通過才寫入（任一個不合法就丟 ValueError、什麼都不改）。呼叫端負責 commit。

    機密設定也從這裡寫：送空字串代表清除，不送代表不變。"""
    validated = {}
    secrets_to_write = {}
    for key, value in values.items():
        if key in SECRET_SETTINGS:
            if not isinstance(value, str):
                raise ValueError(f"{key} 必須是字串")
            secrets_to_write[key] = value.strip()
            continue
        spec = SETTINGS.get(key)
        if spec is None:
            raise ValueError(f"未知的設定：{key}")
        try:
            validated[key] = spec.validate(value)
        except ValueError as e:
            raise ValueError(f"{key} {e}") from None
    for key, value in validated.items():
        _write(db, key, value)
    for key, value in secrets_to_write.items():
        _write(db, key, encrypt_secret(value) if value else None)
    return validated


def _write(db: Session, key: str, value: Any) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def get_secret(db: Session, key: str) -> str | None:
    row = db.get(SystemSetting, key)
    if row is None or not row.value:
        return None
    try:
        return decrypt_secret(row.value)
    except Exception:
        # SERVER_JWT_SECRET 換過就解不開，當成沒設定，管理員重新填一次即可
        return None


def secret_status(db: Session) -> dict[str, bool]:
    """畫面用：每個機密設定只回傳「有沒有設定」。"""
    return {key: get_secret(db, key) is not None for key in SECRET_SETTINGS}
