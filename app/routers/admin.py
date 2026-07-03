import os
import secrets as _secrets
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, PbiConfig, ModelChunk
from app.security import encrypt_secret, issue_admin_jwt, verify_admin_jwt

router = APIRouter(prefix="/admin", tags=["admin"])

_bearer = HTTPBearer()


def _require_admin_jwt(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict:
    return verify_admin_jwt(credentials.credentials)


# ── 管理員登入 ──────────────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    secret: str


class AdminLoginResponse(BaseModel):
    access_token: str
    expires_in: int


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(body: AdminLoginRequest):
    bootstrap = os.getenv("ADMIN_SECRET", "")
    if not _secrets.compare_digest(body.secret, bootstrap):
        raise HTTPException(status_code=401, detail="Invalid admin secret")
    return AdminLoginResponse(access_token=issue_admin_jwt(), expires_in=3600)


# ── 使用者管理 ─────────────────────────────────────────────────────────────

class ActivateRequest(BaseModel):
    email: EmailStr
    is_active: bool
    pbi_config_id: Optional[str] = None
    expires_at: Optional[datetime] = None


@router.get("/users")
def list_users(_=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "pbi_config_id": u.pbi_config_id,
            "expires_at": u.expires_at,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.patch("/users/activate")
def activate_user(body: ActivateRequest, _=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")

    user.is_active = body.is_active
    if body.pbi_config_id is not None:
        user.pbi_config_id = body.pbi_config_id
    if body.expires_at is not None:
        user.expires_at = body.expires_at

    db.commit()
    return {"message": f"{'開通' if body.is_active else '停用'} {body.email} 成功"}


# ── PBI 設定管理 ───────────────────────────────────────────────────────────

class PbiConfigCreate(BaseModel):
    name: str
    tenant_id: str
    client_id: str
    client_secret: str
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None


class PbiConfigUpdate(BaseModel):
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None


@router.get("/pbi-configs")
def list_pbi_configs(_=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    configs = db.query(PbiConfig).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "tenant_id": c.tenant_id,
            "client_id": c.client_id,
            "workspace_id": c.workspace_id,
            "dataset_id": c.dataset_id,
            "updated_at": c.updated_at,
        }
        for c in configs
    ]


@router.post("/pbi-configs", status_code=201)
def create_pbi_config(body: PbiConfigCreate, _=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    if db.query(PbiConfig).filter(PbiConfig.name == body.name).first():
        raise HTTPException(status_code=409, detail="名稱已存在")

    config = PbiConfig(
        name=body.name,
        tenant_id=body.tenant_id,
        client_id=body.client_id,
        client_secret_enc=encrypt_secret(body.client_secret),
        workspace_id=body.workspace_id,
        dataset_id=body.dataset_id,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return {"id": config.id, "name": config.name, "message": "PBI 設定建立成功"}


@router.patch("/pbi-configs/{config_id}")
def update_pbi_config(
    config_id: str,
    body: PbiConfigUpdate,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    config = db.query(PbiConfig).filter(PbiConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="找不到 PBI 設定")

    if body.tenant_id is not None:
        config.tenant_id = body.tenant_id
    if body.client_id is not None:
        config.client_id = body.client_id
    if body.client_secret is not None:
        config.client_secret_enc = encrypt_secret(body.client_secret)
    if body.workspace_id is not None:
        config.workspace_id = body.workspace_id
    if body.dataset_id is not None:
        config.dataset_id = body.dataset_id
    config.updated_at = datetime.utcnow()

    db.commit()
    return {"message": "PBI 設定更新成功"}


# ── 語意模型管理 ───────────────────────────────────────────────────────────

def _parse_pbi_json(raw: dict) -> tuple[dict, list]:
    """接受原始 PBI JSON 或簡化語意 JSON，回傳 (relationships_dict, tables_list)。"""
    if "clientDataModel" in raw:
        data_model = raw["clientDataModel"]["dataModel"]
        fmt = "raw"
    else:
        data_model = raw
        fmt = "semantic"

    relationships: list = []
    for rel in data_model.get("relationships", []):
        if fmt == "raw":
            from_table = rel.get("fromTableRef", {}).get("name", "")
            to_table   = rel.get("toTableRef",   {}).get("name", "")
            direction_map = {"OneDirection": "Single", "BothDirections": "Both"}
            chunk = {
                "fromTable":            from_table,
                "fromColumn":           rel.get("fromColumnRef", {}).get("name", ""),
                "toTable":              to_table,
                "toColumn":             rel.get("toColumnRef",   {}).get("name", ""),
                "cardinality":          f"{rel.get('fromCardinality','Many')}To{rel.get('toCardinality','One')}",
                "crossFilterDirection": direction_map.get(rel.get("crossFilteringBehavior", "OneDirection"), "Single"),
                "isActive":             rel.get("isActive", True),
            }
        else:
            from_table = rel.get("fromTable", "")
            to_table   = rel.get("toTable",   "")
            chunk = {
                "fromTable":            from_table,
                "fromColumn":           rel.get("fromColumn", ""),
                "toTable":              to_table,
                "toColumn":             rel.get("toColumn", ""),
                "cardinality":          rel.get("cardinality", ""),
                "crossFilterDirection": rel.get("crossFilterDirection", "Single"),
                "isActive":             rel.get("isActive", True),
            }

        if any(n.startswith(("LocalDateTable_", "DateTableTemplate_")) for n in [from_table, to_table]):
            continue
        relationships.append(chunk)

    tables: list = []
    for table in data_model.get("tables", []):
        name = table.get("name", "")
        if name.startswith(("LocalDateTable_", "DateTableTemplate_")):
            continue
        entry = {
            "table":       name,
            "description": table.get("description", ""),
            "columns":     [],
            "measures":    [],
        }
        for col in table.get("columns", []):
            if col.get("columnType") == "RowNumber":
                continue
            entry["columns"].append({
                "column":      col.get("name"),
                "dataType":    col.get("dataType"),
                "description": col.get("description", ""),
            })
        for meas in table.get("measures", []):
            entry["measures"].append({
                "measure":     meas.get("name"),
                "expression":  meas.get("expression", ""),
                "description": meas.get("description", ""),
            })
        if entry["columns"] or entry["measures"]:
            tables.append(entry)

    return {"relationships": relationships}, tables


@router.post("/model/upload", status_code=201)
def upload_model(
    raw: Any = Body(...),
    _: dict = Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    try:
        relationships, tables = _parse_pbi_json(raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"JSON 解析失敗：{e}")

    latest = db.query(ModelChunk).order_by(ModelChunk.model_version.desc()).first()
    next_version = (latest.model_version + 1) if latest else 1

    chunk = ModelChunk(
        model_version=next_version,
        relationships=relationships,
        tables=tables,
    )
    db.add(chunk)
    db.commit()
    return {
        "model_version": next_version,
        "table_count": len(tables),
        "relationship_count": len(relationships["relationships"]),
        "message": "語意模型上傳成功",
    }


@router.get("/model/versions")
def list_model_versions(_=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    chunks = db.query(ModelChunk).order_by(ModelChunk.model_version.desc()).all()
    return [
        {"model_version": c.model_version, "uploaded_at": c.uploaded_at}
        for c in chunks
    ]
