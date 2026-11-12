"""查詢權限檢測：用使用者自己的 Service Principal，對已指派的語意模型跑一個最小查詢，
確認「設定完的這組 Azure AD 憑證，到底能不能真的查這個模型」。

`EVALUATE ROW("ok", 1)` 不讀任何真實資料，但跑得過就代表整條路徑都通：Azure AD
憑證正確、SP 已被加入 workspace、Power BI 租用戶設定允許 SP 使用 API、dataset 存在。

這裡用同步的 httpx.post 沒問題：只由管理員手動觸發、頻率極低，而且跑在一般 FastAPI
同步端點上（本來就在 thread pool），情況跟 ticket redeem 一樣。MCP tool 裡的伺服器查詢
（app/server_query.py）才必須全程 async，否則並發時會卡住 event loop。

失敗訊息刻意分兩段：第一行是白話原因（給管理員判斷該去哪裡修），後面附原始錯誤
（可以直接貼給管理 Azure／Power BI 的人）。實務上最花時間的就是「錯誤訊息看不出原因」。
"""

from datetime import datetime

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import PbiConfig, User, UserPbiConfig
from app.routers.credential import acquire_powerbi_token

_TEST_DAX = 'EVALUATE ROW("ok", 1)'
_TIMEOUT_SECONDS = 20
_RAW_ERROR_MAX_CHARS = 1000

# 依 MSAL 回傳的 error_description 裡的 AADSTS 錯誤碼翻成白話。
_AAD_HINTS = [
    ("AADSTS7000215", "Client Secret 錯誤（常見原因：在 Azure 複製到「祕密識別碼」而不是「值」）"),
    ("AADSTS7000222", "Client Secret 已過期，請到 Azure 產生新的 secret 後重新設定"),
    ("AADSTS700016", "Client ID 錯誤，或這個應用程式不屬於該租用戶"),
    ("AADSTS90002", "Tenant ID 錯誤，找不到這個租用戶"),
    ("AADSTS900023", "Tenant ID 格式錯誤"),
]

_POWERBI_HINTS = {
    400: "查詢被 Power BI 拒絕：可能是租用戶設定沒有開啟「Dataset Execute Queries REST API」，或這個 dataset 不支援查詢",
    401: "服務主體沒有這個 workspace 的權限：請確認 SP 已加入 workspace（成員或參與者），且 Power BI 租用戶設定已允許服務主體使用 API",
    403: "服務主體沒有這個 workspace 的權限：請確認 SP 已加入 workspace（成員或參與者），且 Power BI 租用戶設定已允許服務主體使用 API",
    404: "找不到 workspace 或 dataset：請檢查 PBI 設定裡的 ID；SP 沒被加入該 workspace 時 Power BI 也會回這個錯誤",
    429: "Power BI 請求太頻繁，請稍後再重新檢測",
}


def explain_aad_error(detail: str) -> str:
    """把 acquire_powerbi_token 丟出的錯誤翻成白話原因（server 查詢也共用）。"""
    for code, hint in _AAD_HINTS:
        if code in detail:
            return hint
    return "向 Azure AD 換發 token 失敗"


def _failed(hint: str, raw: str | None = None) -> tuple[str, str]:
    return "failed", f"{hint}\n原始錯誤：{raw}" if raw else hint


def run_query_check(user: User, config: PbiConfig) -> tuple[str, str]:
    """回傳 (status, message)，status 為 "ok" 或 "failed"。不寫 DB，方便單獨測試。"""
    if not (user.tenant_id and user.client_id and user.client_secret_enc):
        return _failed("尚未設定 Azure AD 憑證")
    if not (config.workspace_id and config.dataset_id):
        return _failed("PBI 設定缺少 Workspace ID 或 Dataset ID")

    try:
        access_token = acquire_powerbi_token(user)["access_token"]
    except HTTPException as e:
        detail = str(e.detail)
        return _failed(explain_aad_error(detail), detail)
    except Exception as e:  # 例如 SERVER_JWT_SECRET 換過導致 secret 解密失敗、或連不到 Azure
        return _failed("向 Azure AD 換發 token 時發生錯誤", f"{type(e).__name__}: {e}")

    url = (
        f"https://api.powerbi.com/v1.0/myorg/groups/{config.workspace_id}"
        f"/datasets/{config.dataset_id}/executeQueries"
    )
    try:
        res = httpx.post(
            url,
            json={"queries": [{"query": _TEST_DAX}]},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        return _failed("無法連線到 Power BI", f"{type(e).__name__}: {e}")

    if res.status_code == 200:
        return "ok", "可以查詢"
    hint = _POWERBI_HINTS.get(res.status_code, f"Power BI 回應 HTTP {res.status_code}")
    return _failed(hint, f"HTTP {res.status_code} {res.text[:_RAW_ERROR_MAX_CHARS]}")


def check_user_configs(db: Session, user: User, pbi_config_ids: list[str] | None = None) -> list[dict]:
    """檢測使用者已指派的模型（可指定其中幾個），結果寫回 user_pbi_configs 並回傳。"""
    query = db.query(UserPbiConfig).filter(UserPbiConfig.user_id == user.id)
    if pbi_config_ids is not None:
        query = query.filter(UserPbiConfig.pbi_config_id.in_(pbi_config_ids))

    results = []
    for link in query.all():
        config = db.query(PbiConfig).filter(PbiConfig.id == link.pbi_config_id).first()
        if not config:
            continue
        status, message = run_query_check(user, config)
        link.check_status = status
        link.check_message = message
        link.checked_at = datetime.utcnow()
        results.append(link_check_dict(link, config.name))
    db.commit()
    return results


def link_check_dict(link: UserPbiConfig, config_name: str | None = None) -> dict:
    return {
        "pbi_config_id": link.pbi_config_id,
        "pbi_config_name": config_name,
        "check_status": link.check_status,
        "check_message": link.check_message,
        "checked_at": link.checked_at,
    }


def reset_checks(db: Session, *, user_id: str | None = None, pbi_config_ids: list[str] | None = None) -> None:
    """憑證或 workspace/dataset 改過之後，舊的檢測結果就不能再代表現況，改回「未檢測」，
    避免列表繼續顯示過時的綠燈。呼叫端負責 commit。"""
    query = db.query(UserPbiConfig)
    if user_id is not None:
        query = query.filter(UserPbiConfig.user_id == user_id)
    if pbi_config_ids is not None:
        query = query.filter(UserPbiConfig.pbi_config_id.in_(pbi_config_ids))
    query.update(
        {"check_status": None, "check_message": None, "checked_at": None},
        synchronize_session=False,
    )
