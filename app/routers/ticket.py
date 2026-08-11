import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.access_log import client_ip, record_access
from app.database import get_db
from app.models import AccessTicket, PbiConfig, User
from app.routers.credential import acquire_powerbi_token
from app.security import hash_opaque_token

router = APIRouter(prefix="/api/ticket", tags=["ticket"])

DEFAULT_TICKET_TTL_SECONDS = 300


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
    """
    ticket = db.query(AccessTicket).filter(
        AccessTicket.token_hash == hash_opaque_token(body.ticket)
    ).first()
    if not ticket:
        raise HTTPException(status_code=401, detail="ticket 無效")
    if ticket.used_at is not None:
        raise HTTPException(status_code=401, detail="ticket 已使用過，請重新取得")
    if ticket.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="ticket 已過期，請重新取得")

    user = db.query(User).filter(User.id == ticket.user_id).first()
    if not user:
        raise HTTPException(status_code=403, detail="使用者不存在")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="帳號已停用")
    if user.expires_at and user.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="憑證已過期，請聯絡管理員")

    config = db.query(PbiConfig).filter(PbiConfig.id == ticket.pbi_config_id).first()
    if not config:
        raise HTTPException(status_code=503, detail="PBI 設定不存在，請聯絡管理員")

    # 先標記已使用再去跟 Azure AD 換：就算換 token 失敗，這張 ticket 也不該還能重試，
    # 否則等於給了一個可以反覆打 Azure AD 的入口。使用者重新要一張即可。
    ticket.used_at = datetime.utcnow()
    db.commit()

    result = acquire_powerbi_token(user)

    record_access(
        db,
        user_id=user.id,
        email=user.email,
        auth_method="ticket",
        path="/api/ticket/redeem",
        method=request.method,
        ip_address=client_ip(request),
    )

    # 不回傳 workspace_id/dataset_id：那兩個從 get_model_detail 拿，
    # 沿用既有設計，避免同一份靜態資料在兩個地方各回一次。
    return {
        "access_token": result["access_token"],
        "token_type": "Bearer",
        "expires_in": result.get("expires_in", 3600),
    }
