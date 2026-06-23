from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, PbiConfig, ModelChunk
from app.security import hash_mask_key, decrypt_secret, issue_credential_jwt

router = APIRouter(prefix="/api", tags=["skill-api"])
bearer = HTTPBearer()


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


@router.get("/credential")
def get_credential(user: User = Depends(_resolve_user), db: Session = Depends(get_db)):
    if not user.pbi_config_id:
        raise HTTPException(status_code=503, detail="尚未分配 PBI 設定，請聯絡管理員")

    config: PbiConfig = db.query(PbiConfig).filter(PbiConfig.id == user.pbi_config_id).first()
    if not config:
        raise HTTPException(status_code=503, detail="PBI 設定不存在，請聯絡管理員")
    if not config.workspace_id or not config.dataset_id:
        raise HTTPException(status_code=503, detail="PBI 工作區尚未設定完成，請聯絡管理員")

    latest = (
        db.query(ModelChunk)
        .order_by(ModelChunk.model_version.desc())
        .first()
    )
    model_version = latest.model_version if latest else 0

    payload = {
        "tenant_id": config.tenant_id,
        "client_id": config.client_id,
        "client_secret": decrypt_secret(config.client_secret_enc),
        "workspace_id": config.workspace_id,
        "dataset_id": config.dataset_id,
        "model_version": model_version,
    }
    token = issue_credential_jwt(payload, expires_at=user.expires_at)
    return {"jwt": token}


@router.get("/model")
def get_model(user: User = Depends(_resolve_user), db: Session = Depends(get_db)):
    latest = (
        db.query(ModelChunk)
        .order_by(ModelChunk.model_version.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="尚未上傳語意模型")

    return {
        "model_version": latest.model_version,
        "relationships": latest.relationships,
        "tables": latest.tables,
    }
