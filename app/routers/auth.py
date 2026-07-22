import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.access_log import client_ip, record_access
from app.database import get_db
from app.models import PersonalAccessToken, User
from app.security import (
    hash_password, authenticate_user,
    generate_mask_key, hash_mask_key,
    generate_personal_access_token, hash_opaque_token,
    issue_user_jwt, verify_user_jwt,
)


def _check_email_domain(email: str):
    raw = os.getenv("ALLOWED_EMAIL_DOMAINS", "")
    allowed = {d.strip().lower() for d in raw.split(",") if d.strip()}
    if not allowed:
        return
    domain = email.split("@")[-1].lower()
    if domain not in allowed:
        raise HTTPException(status_code=400, detail="此信箱網域不開放註冊，請洽管理員")

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer()


def _require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
    db: Session = Depends(get_db),
) -> dict:
    payload = verify_user_jwt(credentials.credentials)
    record_access(
        db,
        user_id=payload.get("sub"),
        email=payload.get("email"),
        auth_method="user_session",
        path=request.url.path,
        method=request.method,
        ip_address=client_ip(request),
    )
    return payload


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMeResponse(BaseModel):
    user_id: str
    email: str
    is_active: bool
    has_mask_key: bool
    expires_at: str | None = None


class MaskKeyResponse(BaseModel):
    mask_key: str
    note: str


class McpTokenCreateRequest(BaseModel):
    name: Optional[str] = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    _check_email_domain(body.email)
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email 已被使用")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "email": user.email, "message": "註冊成功，等待管理員開通"}


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user, status_ = authenticate_user(db, body.email, body.password)
    if status_ == "locked":
        raise HTTPException(status_code=403, detail="帳號已被鎖定，請聯絡管理員解鎖")
    if status_ != "ok" or not user:
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    return TokenResponse(access_token=issue_user_jwt(str(user.id), user.email))


@router.get("/me", response_model=UserMeResponse)
def get_me(payload: dict = Depends(_require_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    return UserMeResponse(
        user_id=str(user.id),
        email=user.email,
        is_active=user.is_active,
        has_mask_key=user.mask_key_hash is not None,
        expires_at=user.expires_at.isoformat() if user.expires_at else None,
    )


@router.post("/mask-key", response_model=MaskKeyResponse)
def issue_mask_key(payload: dict = Depends(_require_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="帳號尚未開通，請聯絡管理員")
    key = generate_mask_key()
    user.mask_key_hash = hash_mask_key(key)
    db.commit()
    return MaskKeyResponse(
        mask_key=key,
        note="請立即複製並妥善保存，此金鑰僅顯示一次",
    )


# ── MCP Personal Access Token（給不支援完整 OAuth 的 MCP client 用） ──────────

@router.post("/mcp-tokens", status_code=status.HTTP_201_CREATED)
def create_mcp_token(
    body: McpTokenCreateRequest,
    payload: dict = Depends(_require_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="帳號尚未開通，請聯絡管理員")
    token = generate_personal_access_token()
    pat = PersonalAccessToken(user_id=user.id, name=body.name, token_hash=hash_opaque_token(token))
    db.add(pat)
    db.commit()
    db.refresh(pat)
    return {
        "id": pat.id,
        "token": token,
        "name": pat.name,
        "note": "請立即複製並妥善保存，此 token 僅顯示一次，用於不支援 OAuth 連線的 MCP client",
    }


@router.get("/mcp-tokens")
def list_mcp_tokens(payload: dict = Depends(_require_user), db: Session = Depends(get_db)):
    tokens = db.query(PersonalAccessToken).filter(PersonalAccessToken.user_id == payload["sub"]).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "created_at": t.created_at,
            "last_used_at": t.last_used_at,
        }
        for t in tokens
    ]


@router.delete("/mcp-tokens/{token_id}", status_code=204)
def delete_mcp_token(
    token_id: str,
    payload: dict = Depends(_require_user),
    db: Session = Depends(get_db),
):
    token = db.query(PersonalAccessToken).filter(
        PersonalAccessToken.id == token_id,
        PersonalAccessToken.user_id == payload["sub"],
    ).first()
    if not token:
        raise HTTPException(status_code=404, detail="找不到 token")
    db.delete(token)
    db.commit()
