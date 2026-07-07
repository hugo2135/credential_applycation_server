from datetime import datetime
import msal
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, PbiConfig, ModelChunk, UserPbiConfig
from app.security import hash_mask_key, decrypt_secret

router = APIRouter(prefix="/api", tags=["skill-api"])
bearer = HTTPBearer()

_POWERBI_SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]


def _resolve_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
    db: Session = Depends(get_db),
) -> User:
    key_hash = hash_mask_key(credentials.credentials)
    user = db.query(User).filter(User.mask_key_hash == key_hash).first()
    if not user:
        raise HTTPException(status_code=401, detail="無效的 PBI_MASK_KEY")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="帳號已停用")
    if user.expires_at and user.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="憑證已過期，請聯絡管理員")
    return user


def _check_config_access(user: User, pbi_config_id: str, db: Session) -> PbiConfig:
    link = db.query(UserPbiConfig).filter(
        UserPbiConfig.user_id == user.id,
        UserPbiConfig.pbi_config_id == pbi_config_id,
    ).first()
    if not link:
        raise HTTPException(status_code=403, detail="無此 PBI 設定的存取權")
    config = db.query(PbiConfig).filter(PbiConfig.id == pbi_config_id).first()
    if not config:
        raise HTTPException(status_code=503, detail="PBI 設定不存在，請聯絡管理員")
    return config


def _check_user_credentials(user: User):
    if not user.tenant_id or not user.client_id or not user.client_secret_enc:
        raise HTTPException(status_code=503, detail="Azure AD 憑證尚未設定，請聯絡管理員")


@router.get("/models")
def get_models(
    user: User = Depends(_resolve_user),
    db: Session = Depends(get_db),
):
    links = db.query(UserPbiConfig).filter(UserPbiConfig.user_id == user.id).all()
    result = []
    for link in links:
        config = db.query(PbiConfig).filter(PbiConfig.id == link.pbi_config_id).first()
        if not config:
            continue
        latest = (
            db.query(ModelChunk)
            .filter(ModelChunk.pbi_config_id == link.pbi_config_id)
            .order_by(ModelChunk.model_version.desc())
            .first()
        )
        if not latest:
            continue
        result.append({
            "pbi_config_id": config.id,
            "pbi_config_name": config.name,
            "model_version": latest.model_version,
            "model_description": latest.model_description,
            "relationships": latest.relationships,
            "tables": latest.tables,
        })
    return {"models": result}


@router.get("/token")
def get_token(
    pbi_config_id: str = Query(..., description="PBI 設定 ID"),
    user: User = Depends(_resolve_user),
    db: Session = Depends(get_db),
):
    _check_user_credentials(user)
    config = _check_config_access(user, pbi_config_id, db)
    if not config.workspace_id or not config.dataset_id:
        raise HTTPException(status_code=503, detail="PBI 工作區尚未設定完成，請聯絡管理員")

    client_secret = decrypt_secret(user.client_secret_enc)
    msal_app = msal.ConfidentialClientApplication(
        client_id=user.client_id,
        authority=f"https://login.microsoftonline.com/{user.tenant_id}",
        client_credential=client_secret,
    )
    result = msal_app.acquire_token_for_client(scopes=_POWERBI_SCOPE)

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "未知錯誤"))
        raise HTTPException(status_code=502, detail=f"Azure AD 驗證失敗：{error}")

    latest = (
        db.query(ModelChunk)
        .filter(ModelChunk.pbi_config_id == pbi_config_id)
        .order_by(ModelChunk.model_version.desc())
        .first()
    )

    return {
        "access_token": result["access_token"],
        "token_type": "Bearer",
        "expires_in": result.get("expires_in", 3600),
        "workspace_id": config.workspace_id,
        "dataset_id": config.dataset_id,
        "model_version": latest.model_version if latest else 0,
    }
