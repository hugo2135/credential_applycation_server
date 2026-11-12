import os
import time
from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.access_log import client_ip, elapsed_ms, record_access
from app.database import get_db
from app.models import AccessTicket, PbiConfig, User
from app.routers.credential import acquire_powerbi_token
from app.security import hash_opaque_token

router = APIRouter(prefix="/api/ticket", tags=["ticket"])

DEFAULT_TICKET_TTL_SECONDS = 300

# 指的是管理員設定的帳號「到期時間」（User.expires_at），刻意不用「憑證」兩個字：
# 跟 Azure AD client secret 過期（會帶 AADSTS7000222）容易搞混。
EXPIRED_ACCOUNT_MESSAGE = "帳號使用期限已到，請聯絡管理員"


def ticket_ttl_seconds() -> int:
    """ticket 效期（秒）。動態讀取而不是 module-level 常數，比照 `security._get_secret()`
    的慣例避開 .env 載入時序問題，順便讓測試可以 monkeypatch。

    預設 300 秒：ticket 是在 MCP tool 回傳時發出、在查詢腳本啟動時才兌換，中間會夾雜
    使用者按下工具權限確認的時間——這段人為延遲不是 skill 能控制的，訂太短（例如 60 秒）
    會讓「使用者晚幾十秒才按允許」變成查詢失敗。安全性上放寬影響有限：ticket 仍是單次
    使用，暴露價值只存在於「尚未被兌換」那段時間，而正常情況腳本幾秒內就兌換掉了。
    """
    raw = os.getenv("MCP_TICKET_TTL_SECONDS", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TICKET_TTL_SECONDS
    return value if value > 0 else DEFAULT_TICKET_TTL_SECONDS


class RedeemRequest(BaseModel):
    ticket: str


@router.post("/redeem")
def redeem_ticket(
    body: RedeemRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """用 MCP 的 `get_query_ticket` 發出的一次性 ticket 換 Power BI access token。

    這支端點刻意**不需要其他身份驗證**——ticket 本身就是憑證（單次使用、短效，
    DB 只存 hash）。它是給使用者機器／沙盒上的查詢腳本呼叫的，所以也必須列在
    `main.py` 的 IP 白名單豁免清單裡，否則設了 `ALLOWED_IPS` 的環境會一直 403。

    成功與失敗都會寫進 access log（失敗時 `error` 欄位放原因），唯一例外是查無此
    ticket：那種請求連是誰都不知道，而這支端點不需要登入，記下來等於讓任何人都能
    往 DB 灌資料。
    """
    started = time.monotonic()
    ticket = db.query(AccessTicket).filter(
        AccessTicket.token_hash == hash_opaque_token(body.ticket)
    ).first()
    if not ticket:
        raise HTTPException(status_code=401, detail="ticket 無效")

    user = db.query(User).filter(User.id == ticket.user_id).first()

    def log(error: str | None = None) -> None:
        record_access(
            db,
            user_id=user.id if user else ticket.user_id,
            email=user.email if user else None,
            auth_method="ticket",
            path="/api/ticket/redeem",
            method=request.method,
            ip_address=client_ip(request),
            detail=ticket.pbi_config_id,
            error=error,
            query_text=ticket.query_text,
            duration_ms=elapsed_ms(started),
        )

    def fail(status_code: int, message: str) -> NoReturn:
        log(message)
        raise HTTPException(status_code=status_code, detail=message)

    if ticket.used_at is not None:
        fail(401, "ticket 已使用過，請重新取得")
    if ticket.expires_at < datetime.utcnow():
        fail(401, "ticket 已過期，請重新取得")

    if not user:
        fail(403, "使用者不存在")
    if not user.is_active:
        fail(403, "帳號已停用")
    if user.expires_at and user.expires_at < datetime.utcnow():
        fail(403, EXPIRED_ACCOUNT_MESSAGE)

    config = db.query(PbiConfig).filter(PbiConfig.id == ticket.pbi_config_id).first()
    if not config:
        fail(503, "PBI 設定不存在，請聯絡管理員")

    # 先標記已使用再去跟 Azure AD 換：就算換 token 失敗，這張 ticket 也不該還能重試，
    # 否則等於給了一個可以反覆打 Azure AD 的入口。使用者重新要一張即可。
    ticket.used_at = datetime.utcnow()
    db.commit()

    try:
        result = acquire_powerbi_token(user)
    except HTTPException as e:
        log(str(e.detail))
        raise
    except Exception as e:
        log(f"換取 token 時發生未預期錯誤：{type(e).__name__}")
        raise

    log()

    # 不回傳 workspace_id/dataset_id：那兩個從 get_model_detail 拿，
    # 沿用既有設計，避免同一份靜態資料在兩個地方各回一次。
    return {
        "access_token": result["access_token"],
        "token_type": "Bearer",
        "expires_in": result.get("expires_in", 3600),
    }
