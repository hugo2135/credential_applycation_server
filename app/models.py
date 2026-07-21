import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer, JSON, Text, ForeignKey
from app.database import Base


def new_uuid():
    return str(uuid.uuid4())


class PbiConfig(Base):
    __tablename__ = "pbi_config"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, unique=True, nullable=False)
    workspace_id = Column(String, nullable=True)
    dataset_id = Column(String, nullable=True)
    filters = Column(JSON, nullable=True)  # list[dict]，篩選設定檔（filterId/name/alwaysApply/...）
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    mask_key_hash = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    pbi_config_id = Column(String, ForeignKey("pbi_config.id"), nullable=True)  # legacy
    tenant_id = Column(String, nullable=True)
    client_id = Column(String, nullable=True)
    client_secret_enc = Column(String, nullable=True)        # AES-GCM 加密後儲存
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    failed_login_attempts = Column(Integer, default=0, nullable=False)


class UserPbiConfig(Base):
    __tablename__ = "user_pbi_configs"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    pbi_config_id = Column(String, ForeignKey("pbi_config.id"), primary_key=True)


class ModelChunk(Base):
    __tablename__ = "model_chunks"

    id = Column(String, primary_key=True, default=new_uuid)
    model_version = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=True)
    pbi_config_id = Column(String, ForeignKey("pbi_config.id"), nullable=True, index=True)
    model_description = Column(Text, nullable=True)
    relationships = Column(JSON, nullable=False)
    tables = Column(JSON, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class OAuthClient(Base):
    """MCP connector 端透過 Dynamic Client Registration 自行註冊的 client（public client，靠 PKCE 保護，不存 secret）。"""
    __tablename__ = "oauth_clients"

    client_id = Column(String, primary_key=True, default=new_uuid)
    client_name = Column(String, nullable=True)
    redirect_uris = Column(JSON, nullable=False)  # list[str]
    created_at = Column(DateTime, default=datetime.utcnow)


class OAuthAuthorizationCode(Base):
    """短效期一次性 authorization code，換 access token 用（PKCE S256）。"""
    __tablename__ = "oauth_authorization_codes"

    code = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("oauth_clients.client_id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    redirect_uri = Column(String, nullable=False)
    code_challenge = Column(String, nullable=False)
    code_challenge_method = Column(String, nullable=False, default="S256")
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class OAuthRefreshToken(Base):
    """長效 refresh token，明文只在核發當下回傳一次，DB 只存 hash（比照 PBI_MASK_KEY 的作法）。"""
    __tablename__ = "oauth_refresh_tokens"

    token_hash = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("oauth_clients.client_id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
