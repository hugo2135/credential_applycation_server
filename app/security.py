import os
import hashlib
import logging
import secrets
import base64
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException
from jose import jwt, JWTError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
MAX_LOGIN_ATTEMPTS = 5


def _get_secret() -> str:
    return os.getenv("SERVER_JWT_SECRET", "")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def authenticate_user(db: Session, email: str, password: str):
    """帳密登入共用邏輯（/auth/login、/oauth/authorize 都要用），含失敗鎖定。

    回傳 (user, status)：status 為 "ok" / "invalid" / "locked"。
    帳號累積 MAX_LOGIN_ATTEMPTS 次密碼錯誤後鎖定，只能由管理員解鎖
    （不設自動過期解鎖，避免被反覆嘗試繞過）。成功登入會重置計數。
    """
    from app.models import User  # 延後 import，避免 security.py 對 models.py 產生模組層級依賴

    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None, "invalid"
    if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
        return None, "locked"
    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        db.commit()
        return None, "invalid"
    user.failed_login_attempts = 0
    db.commit()
    return user, "ok"


def hash_mask_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_mask_key() -> str:
    return secrets.token_hex(32)


def generate_personal_access_token() -> str:
    return "pat_" + secrets.token_hex(32)


def generate_access_ticket() -> str:
    """一次性短效 ticket：純隨機、不含任何語意（誰／哪個設定全部存在 DB 那一列）。"""
    return secrets.token_urlsafe(32)


def issue_credential_jwt(payload: dict, expires_at: datetime | None = None) -> str:
    expire = expires_at or datetime.now(timezone.utc) + timedelta(days=30)
    data = {
        **payload,
        "iss": "pbi-skill-provider",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(data, _get_secret(), algorithm=JWT_ALGORITHM)


def issue_admin_jwt() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "role": "admin",
        "iss": "admin-session",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def issue_user_jwt(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": "user",
        "iss": "user-session",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()),
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def verify_user_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        logger.error("User JWT decode failed: %r", e)
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    if payload.get("role") != "user" or payload.get("iss") != "user-session":
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    return payload


def verify_admin_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        logger.error("JWT decode failed: %r", e)
        raise HTTPException(status_code=401, detail="Admin session invalid or expired")
    if payload.get("role") != "admin" or payload.get("iss") != "admin-session":
        raise HTTPException(status_code=401, detail="Admin session invalid or expired")
    return payload


def issue_mcp_access_token(user_id: str, email: str, client_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "client_id": client_id,
        "role": "mcp",
        "iss": "oauth-access-token",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def verify_mcp_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        logger.error("MCP access token decode failed: %r", e)
        raise HTTPException(status_code=401, detail="Access token invalid or expired")
    if payload.get("role") != "mcp" or payload.get("iss") != "oauth-access-token":
        raise HTTPException(status_code=401, detail="Access token invalid or expired")
    return payload


def generate_authorization_code() -> str:
    return secrets.token_urlsafe(32)


def generate_refresh_token() -> str:
    return secrets.token_hex(32)


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    if method != "S256":
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(computed, code_challenge)


def _aes_key() -> bytes:
    raw = os.getenv("SERVER_JWT_SECRET", "fallback-key-change-me")
    return hashlib.sha256(raw.encode()).digest()  # 32 bytes → AES-256


def encrypt_secret(plaintext: str) -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_aes_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_secret(encoded: str) -> str:
    raw = base64.b64decode(encoded)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_aes_key()).decrypt(nonce, ct, None).decode()
