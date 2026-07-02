import os
import hashlib
import logging
import secrets
import base64
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"


def _get_secret() -> str:
    return os.getenv("SERVER_JWT_SECRET", "")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_mask_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_mask_key() -> str:
    return secrets.token_hex(32)


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


def verify_admin_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        logger.error("JWT decode failed: %r", e)
        raise HTTPException(status_code=401, detail="Admin session invalid or expired")
    if payload.get("role") != "admin" or payload.get("iss") != "admin-session":
        raise HTTPException(status_code=401, detail="Admin session invalid or expired")
    return payload


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
