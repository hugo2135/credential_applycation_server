from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import hash_password, verify_password, generate_mask_key, hash_mask_key

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    user_id: str
    email: str
    is_active: bool
    is_admin: bool


class MaskKeyResponse(BaseModel):
    mask_key: str
    note: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email 已被使用")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "email": user.email, "message": "註冊成功，等待管理員開通"}


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    return LoginResponse(
        user_id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
    )


@router.post("/mask-key", response_model=MaskKeyResponse)
def issue_mask_key(body: LoginRequest, db: Session = Depends(get_db)):
    """登入後領取 PBI_MASK_KEY（僅能領取一次，領取後舊的失效）"""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="帳號尚未開通，請聯絡管理員")

    key = generate_mask_key()
    user.mask_key_hash = hash_mask_key(key)
    db.commit()

    return MaskKeyResponse(
        mask_key=key,
        note="請立即複製並妥善保存，此金鑰僅顯示一次",
    )
