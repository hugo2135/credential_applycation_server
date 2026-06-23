import os
import hashlib
import secrets
import base64
from datetime import datetime, timedelta

from jose import jwt
from passlib.context import CryptContext
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SERVER_JWT_SECRET = os.getenv("SERVER_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_mask_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_mask_key() -> str:
    return secrets.token_hex(32)


def issue_credential_jwt(payload: dict, expires_at: datetime | None = None) -> str:
    expire = expires_at or datetime.utcnow() + timedelta(days=30)
    data = {
        **payload,
        "iss": "pbi-skill-provider",
        "iat": int(datetime.utcnow().timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(data, SERVER_JWT_SECRET, algorithm=JWT_ALGORITHM)


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
