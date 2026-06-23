import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer, JSON, ForeignKey
from app.database import Base


def new_uuid():
    return str(uuid.uuid4())


class PbiConfig(Base):
    __tablename__ = "pbi_config"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, unique=True, nullable=False)       # 識別名稱，例如 "TenantA"
    tenant_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    client_secret_enc = Column(String, nullable=False)       # AES-GCM 加密後儲存
    workspace_id = Column(String, nullable=True)             # 指派工作區後填入
    dataset_id = Column(String, nullable=True)               # 指派工作區後填入
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    mask_key_hash = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    pbi_config_id = Column(String, ForeignKey("pbi_config.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class ModelChunk(Base):
    __tablename__ = "model_chunks"

    id = Column(String, primary_key=True, default=new_uuid)
    model_version = Column(Integer, nullable=False, index=True)
    relationships = Column(JSON, nullable=False)
    tables = Column(JSON, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
