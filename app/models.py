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
    query_modes = Column(JSON, nullable=True)  # list[dict]，資料曝光範圍模式（mode_id/name/tables/filters）
    column_aliases = Column(JSON, nullable=True)  # list[dict]，重點欄位值的別名對照（table/column/values[{value,aliases}]）
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


class PersonalAccessToken(Base):
    """給不支援完整 OAuth 流程的 MCP client（例如 Antigravity）用的固定 Bearer token。
    使用者自助在 /mcp-tokens 頁面產生，明文只顯示一次，DB 只存 hash（比照 PBI_MASK_KEY）。"""
    __tablename__ = "personal_access_tokens"

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


class AccessLog(Base):
    """使用者存取歷史，供管理員在 /admin/access-logs 查詢／匯出。只留 90 天（見 main.py
    的背景清理 task），user_id 允許為 null、email 額外存一份純文字快照，這樣使用者
    被刪除後歷史紀錄還能看出當初是誰存取的。"""
    __tablename__ = "access_logs"

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    email = Column(String, nullable=True, index=True)
    path = Column(String, nullable=False)
    method = Column(String, nullable=True)  # /mcp 這個驗證點拿不到 HTTP method，留空
    auth_method = Column(String, nullable=False, index=True)  # user_session / oauth / pat / mask_key
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
