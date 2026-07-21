import os
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import (
    hash_password, authenticate_user,
    generate_mask_key, hash_mask_key,
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
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict:
    return verify_user_jwt(credentials.credentials)


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
