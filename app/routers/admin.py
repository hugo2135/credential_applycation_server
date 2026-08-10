import csv
import io
import os
import json
import secrets as _secrets
from datetime import datetime
from typing import Optional

from fastapi import Query
from fastapi.responses import Response

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AccessLog, PersonalAccessToken, User, PbiConfig, ModelChunk, UserPbiConfig
from app.security import MAX_LOGIN_ATTEMPTS, encrypt_secret, issue_admin_jwt, verify_admin_jwt
from scripts.chunk_model import parse_model

router = APIRouter(prefix="/api/admin", tags=["admin"])

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
    expires_at: Optional[datetime] = None


class UserPbiConfigsRequest(BaseModel):
    pbi_config_ids: list[str]


@router.get("/users")
def list_users(_=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    users = db.query(User).all()
    links = db.query(UserPbiConfig).all()
    config_map: dict[str, list[str]] = {}
    for lnk in links:
        config_map.setdefault(lnk.user_id, []).append(lnk.pbi_config_id)
    return [
        {
            "id": u.id,
            "email": u.email,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "pbi_config_ids": config_map.get(u.id, []),
            "has_credentials": bool(u.tenant_id and u.client_id and u.client_secret_enc),
            "expires_at": u.expires_at,
            "created_at": u.created_at,
            "is_locked": u.failed_login_attempts >= MAX_LOGIN_ATTEMPTS,
        }
        for u in users
    ]


@router.patch("/users/activate")
def activate_user(body: ActivateRequest, _=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    user.is_active = body.is_active
    if body.expires_at is not None:
        user.expires_at = body.expires_at
    db.commit()
    return {"message": f"{'開通' if body.is_active else '停用'} {body.email} 成功"}


class UserCredentialsRequest(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: str


@router.post("/users/{user_id}/reset-mask-key")
def reset_mask_key(
    user_id: str,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    user.mask_key_hash = None
    db.commit()
    return {"message": "PBI_MASK_KEY 已重設，使用者可重新至 Dashboard 領取"}


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: str,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    user.failed_login_attempts = 0
    db.commit()
    return {"message": f"{user.email} 已解鎖"}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    db.query(UserPbiConfig).filter(UserPbiConfig.user_id == user_id).delete()
    db.delete(user)
    db.commit()


# ── MCP Personal Access Token（管理員只能查看/撤銷，不能代發——明文只在使用者
# 自己產生當下顯示一次，管理員從來看不到明文） ────────────────────────────────

@router.get("/users/{user_id}/mcp-tokens")
def admin_list_mcp_tokens(
    user_id: str,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    tokens = db.query(PersonalAccessToken).filter(PersonalAccessToken.user_id == user_id).all()
    return [
        {"id": t.id, "name": t.name, "created_at": t.created_at, "last_used_at": t.last_used_at}
        for t in tokens
    ]


@router.delete("/users/{user_id}/mcp-tokens/{token_id}", status_code=204)
def admin_delete_mcp_token(
    user_id: str,
    token_id: str,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    token = db.query(PersonalAccessToken).filter(
        PersonalAccessToken.id == token_id,
        PersonalAccessToken.user_id == user_id,
    ).first()
    if not token:
        raise HTTPException(status_code=404, detail="找不到 token")
    db.delete(token)
    db.commit()


# ── 批次操作 ───────────────────────────────────────────────────────────────

class BatchActivateRequest(BaseModel):
    user_ids: list[str]
    is_active: bool


class BatchPbiConfigsRequest(BaseModel):
    user_ids: list[str]
    pbi_config_ids: list[str]


class BatchDeleteRequest(BaseModel):
    user_ids: list[str]


@router.post("/users/batch-activate")
def batch_activate_users(
    body: BatchActivateRequest,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    updated = db.query(User).filter(User.id.in_(body.user_ids)).update(
        {"is_active": body.is_active}, synchronize_session=False
    )
    db.commit()
    return {"message": f"已{'開通' if body.is_active else '停用'} {updated} 位使用者"}


@router.put("/users/batch-pbi-configs")
def batch_assign_pbi_configs(
    body: BatchPbiConfigsRequest,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    """批次指派是「新增」，不會動到每位使用者既有的指派——批次替換風險太高，容易誤刪其他設定。"""
    for cid in body.pbi_config_ids:
        if not db.query(PbiConfig).filter(PbiConfig.id == cid).first():
            raise HTTPException(status_code=404, detail=f"找不到 PBI 設定：{cid}")
    added = 0
    for uid in body.user_ids:
        if not db.query(User).filter(User.id == uid).first():
            continue
        for cid in body.pbi_config_ids:
            exists = db.query(UserPbiConfig).filter(
                UserPbiConfig.user_id == uid, UserPbiConfig.pbi_config_id == cid,
            ).first()
            if not exists:
                db.add(UserPbiConfig(user_id=uid, pbi_config_id=cid))
                added += 1
    db.commit()
    return {"message": f"已新增 {added} 筆指派"}


@router.post("/users/batch-delete", status_code=200)
def batch_delete_users(
    body: BatchDeleteRequest,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    db.query(UserPbiConfig).filter(UserPbiConfig.user_id.in_(body.user_ids)).delete(synchronize_session=False)
    deleted = db.query(User).filter(User.id.in_(body.user_ids)).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已刪除 {deleted} 位使用者"}


# ── 存取歷史（/dashboard、/mcp、/mcp-tokens、/api 等，只留 90 天） ────────────────

def _filtered_access_logs(
    db: Session,
    email: Optional[str],
    auth_method: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
):
    q = db.query(AccessLog)
    if email:
        q = q.filter(AccessLog.email.ilike(f"%{email}%"))
    if auth_method:
        q = q.filter(AccessLog.auth_method == auth_method)
    if start:
        q = q.filter(AccessLog.created_at >= start)
    if end:
        q = q.filter(AccessLog.created_at <= end)
    return q.order_by(AccessLog.created_at.desc())


@router.get("/access-logs")
def list_access_logs(
    email: Optional[str] = Query(None, description="依 email 模糊搜尋"),
    auth_method: Optional[str] = Query(None, description="user_session / oauth / pat / mask_key"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(200, le=1000),
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    rows = _filtered_access_logs(db, email, auth_method, start, end).limit(limit).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "email": r.email,
            "path": r.path,
            "method": r.method,
            "auth_method": r.auth_method,
            "ip_address": r.ip_address,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/access-logs/export")
def export_access_logs(
    email: Optional[str] = Query(None),
    auth_method: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    rows = _filtered_access_logs(db, email, auth_method, start, end).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "email", "auth_method", "method", "path", "ip_address"])
    for r in rows:
        writer.writerow([
            r.created_at.isoformat(), r.email or "", r.auth_method, r.method or "", r.path, r.ip_address or "",
        ])

    filename = f"access-logs-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/users/{user_id}/credentials")
def set_user_credentials(
    user_id: str,
    body: UserCredentialsRequest,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    user.tenant_id = body.tenant_id
    user.client_id = body.client_id
    user.client_secret_enc = encrypt_secret(body.client_secret)
    db.commit()
    return {"message": "Azure AD 憑證設定成功"}


@router.put("/users/{user_id}/pbi-configs")
def set_user_pbi_configs(
    user_id: str,
    body: UserPbiConfigsRequest,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    if not db.query(User).filter(User.id == user_id).first():
        raise HTTPException(status_code=404, detail="找不到使用者")
    for cid in body.pbi_config_ids:
        if not db.query(PbiConfig).filter(PbiConfig.id == cid).first():
            raise HTTPException(status_code=404, detail=f"找不到 PBI 設定：{cid}")
    db.query(UserPbiConfig).filter(UserPbiConfig.user_id == user_id).delete()
    for cid in body.pbi_config_ids:
        db.add(UserPbiConfig(user_id=user_id, pbi_config_id=cid))
    db.commit()
    return {"message": "PBI 設定指派成功"}


# ── PBI 設定管理 ───────────────────────────────────────────────────────────

class FilterRule(BaseModel):
    description: str
    expression: str
    requiredTable: Optional[str] = None


class FilterProfile(BaseModel):
    filterId: str
    name: str
    description: Optional[str] = None
    alwaysApply: bool = False
    overrideDefaults: bool = False
    contextKeywords: list[str] = []
    filters: list[FilterRule] = []


class QueryMode(BaseModel):
    """資料曝光範圍模式：限定這個模式下能看到哪些表、外加該模式專屬的篩選條件（疊加在
    filters 比對出來的結果之上，不取代）。存取限制沿用既有的 PBI 設定指派機制，不另外
    做使用者-模式層級的授權。"""
    mode_id: str
    name: str
    description: Optional[str] = None
    tables: list[str] = []
    filters: list[FilterRule] = []


class ColumnValueAlias(BaseModel):
    value: str
    aliases: list[str] = []


class ColumnAliasGroup(BaseModel):
    table: str
    column: str
    values: list[ColumnValueAlias] = []


class PbiConfigCreate(BaseModel):
    name: str
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None


class PbiConfigUpdate(BaseModel):
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None
    filters: Optional[list[FilterProfile]] = None
    query_modes: Optional[list[QueryMode]] = None
    column_aliases: Optional[list[ColumnAliasGroup]] = None


class PbiConfigDuplicateRequest(BaseModel):
    name: str


class BatchPbiConfigUpdateRequest(BaseModel):
    """批次修改只開放 workspace_id/dataset_id/column_aliases——這三個是底層 Power BI
    dataset 本身的屬性，多個設定共用同一份資料時理應一致。filters/query_modes 刻意
    不給批次改，因為它們存在的目的就是讓不同設定之間刻意不同（部門區隔），批次覆蓋
    容易靜默破壞管理員已經調好的存取範圍。"""
    config_ids: list[str]
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None
    column_aliases: Optional[list[ColumnAliasGroup]] = None


def _pbi_config_dict(c: PbiConfig) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "workspace_id": c.workspace_id,
        "dataset_id": c.dataset_id,
        "filters": c.filters or [],
        "query_modes": c.query_modes or [],
        "column_aliases": c.column_aliases or [],
        "updated_at": c.updated_at,
    }


@router.get("/pbi-configs")
def list_pbi_configs(_=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    configs = db.query(PbiConfig).all()
    return [_pbi_config_dict(c) for c in configs]


@router.get("/pbi-configs/{config_id}")
def get_pbi_config(config_id: str, _=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    config = db.query(PbiConfig).filter(PbiConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="找不到 PBI 設定")
    return _pbi_config_dict(config)


@router.post("/pbi-configs", status_code=201)
def create_pbi_config(body: PbiConfigCreate, _=Depends(_require_admin_jwt), db: Session = Depends(get_db)):
    if db.query(PbiConfig).filter(PbiConfig.name == body.name).first():
        raise HTTPException(status_code=409, detail="名稱已存在")
    config = PbiConfig(
        name=body.name,
        workspace_id=body.workspace_id,
        dataset_id=body.dataset_id,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return {"id": config.id, "name": config.name, "message": "PBI 設定建立成功"}


# 一定要在 PATCH /pbi-configs/{config_id} 之前註冊：FastAPI 依註冊順序比對路由，
# {config_id} 這種單一路徑段會吃掉字面上的 "batch-update"，順序反了會變成
# 「找不到 PBI 設定：batch-update」的 404，而不是真的執行批次更新。
@router.patch("/pbi-configs/batch-update")
def batch_update_pbi_configs(
    body: BatchPbiConfigUpdateRequest,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    configs = db.query(PbiConfig).filter(PbiConfig.id.in_(body.config_ids)).all()
    for config in configs:
        if body.workspace_id is not None:
            config.workspace_id = body.workspace_id
        if body.dataset_id is not None:
            config.dataset_id = body.dataset_id
        if body.column_aliases is not None:
            config.column_aliases = [a.model_dump() for a in body.column_aliases]
        config.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"已更新 {len(configs)} 筆 PBI 設定"}


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
    if body.workspace_id is not None:
        config.workspace_id = body.workspace_id
    if body.dataset_id is not None:
        config.dataset_id = body.dataset_id
    if body.filters is not None:
        config.filters = [f.model_dump() for f in body.filters]
    if body.query_modes is not None:
        config.query_modes = [m.model_dump() for m in body.query_modes]
    if body.column_aliases is not None:
        config.column_aliases = [a.model_dump() for a in body.column_aliases]
    config.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "PBI 設定更新成功"}


@router.post("/pbi-configs/{config_id}/duplicate", status_code=201)
def duplicate_pbi_config(
    config_id: str,
    body: PbiConfigDuplicateRequest,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    source = db.query(PbiConfig).filter(PbiConfig.id == config_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="找不到 PBI 設定")
    if db.query(PbiConfig).filter(PbiConfig.name == body.name).first():
        raise HTTPException(status_code=409, detail="名稱已存在")

    new_config = PbiConfig(
        name=body.name,
        workspace_id=source.workspace_id,
        dataset_id=source.dataset_id,
        filters=source.filters,
        query_modes=source.query_modes,
        column_aliases=source.column_aliases,
    )
    db.add(new_config)
    db.flush()  # 先取得 new_config.id，語意模型才有 pbi_config_id 可以掛

    latest = (
        db.query(ModelChunk)
        .filter(ModelChunk.pbi_config_id == config_id)
        .order_by(ModelChunk.model_version.desc())
        .first()
    )
    if latest:
        db.add(ModelChunk(
            model_version=1,
            name=latest.name,
            pbi_config_id=new_config.id,
            model_description=latest.model_description,
            relationships=latest.relationships,
            tables=latest.tables,
        ))

    db.commit()
    db.refresh(new_config)
    return {"id": new_config.id, "name": new_config.name, "message": "PBI 設定複製成功"}


@router.delete("/pbi-configs/{config_id}", status_code=204)
def delete_pbi_config(
    config_id: str,
    _=Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    config = db.query(PbiConfig).filter(PbiConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="找不到 PBI 設定")
    db.query(UserPbiConfig).filter(UserPbiConfig.pbi_config_id == config_id).delete()
    db.query(ModelChunk).filter(ModelChunk.pbi_config_id == config_id).delete()
    db.delete(config)
    db.commit()


# ── 語意模型管理 ───────────────────────────────────────────────────────────

class ModelUploadRequest(BaseModel):
    pbi_config_id: str
    name: Optional[str] = None
    model_description: Optional[str] = None
    data: dict


class RenameVersionRequest(BaseModel):
    name: Optional[str] = None
    model_description: Optional[str] = None


@router.post("/model/upload", status_code=201)
def upload_model(
    body: ModelUploadRequest,
    _: dict = Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    try:
        relationships, tables = parse_model(body.data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"JSON 解析失敗：{e}")

    latest = (
        db.query(ModelChunk)
        .filter(ModelChunk.pbi_config_id == body.pbi_config_id)
        .order_by(ModelChunk.model_version.desc())
        .first()
    )
    next_version = (latest.model_version + 1) if latest else 1

    if not db.query(PbiConfig).filter(PbiConfig.id == body.pbi_config_id).first():
        raise HTTPException(status_code=404, detail="找不到指定的 PBI 設定")

    chunk = ModelChunk(
        model_version=next_version,
        name=body.name,
        model_description=body.model_description,
        pbi_config_id=body.pbi_config_id,
        relationships=relationships,
        tables=tables,
    )
    db.add(chunk)
    db.commit()
    return {
        "model_version": next_version,
        "name": body.name,
        "table_count": len(tables),
        "relationship_count": len(relationships["relationships"]),
        "message": "語意模型上傳成功",
    }


@router.get("/model/versions")
def list_model_versions(
    pbi_config_id: Optional[str] = Query(None),
    _: dict = Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    q = db.query(ModelChunk)
    if pbi_config_id:
        q = q.filter(ModelChunk.pbi_config_id == pbi_config_id)
    chunks = q.order_by(ModelChunk.model_version.desc()).all()
    return [
        {
            "id": c.id,
            "model_version": c.model_version,
            "name": c.name,
            "model_description": c.model_description,
            "pbi_config_id": c.pbi_config_id,
            "table_count": len(c.tables) if c.tables else 0,
            "relationship_count": len(c.relationships.get("relationships", [])) if c.relationships else 0,
            "uploaded_at": c.uploaded_at,
        }
        for c in chunks
    ]


@router.get("/model/versions/{chunk_id}")
def get_model_version(
    chunk_id: str,
    _: dict = Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    chunk = db.query(ModelChunk).filter(ModelChunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {
        "id": chunk.id,
        "model_version": chunk.model_version,
        "name": chunk.name,
        "model_description": chunk.model_description,
        "tables": [t["table"] for t in chunk.tables] if chunk.tables else [],
        "table_count": len(chunk.tables) if chunk.tables else 0,
        "relationship_count": len(chunk.relationships.get("relationships", [])) if chunk.relationships else 0,
        "uploaded_at": chunk.uploaded_at,
    }


@router.patch("/model/versions/{chunk_id}")
def rename_model_version(
    chunk_id: str,
    body: RenameVersionRequest,
    _: dict = Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    chunk = db.query(ModelChunk).filter(ModelChunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="版本不存在")
    chunk.name = body.name
    if body.model_description is not None:
        chunk.model_description = body.model_description
    db.commit()
    return {"message": "已更新版本資訊"}


@router.get("/model/versions/{chunk_id}/export")
def export_model_version(
    chunk_id: str,
    _: dict = Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    chunk = db.query(ModelChunk).filter(ModelChunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="版本不存在")
    payload = {
        "model_version": chunk.model_version,
        "name": chunk.name,
        "pbi_config_id": chunk.pbi_config_id,
        "relationships": chunk.relationships,
        "tables": chunk.tables,
    }
    filename = f"model_v{chunk.model_version}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/model/versions/{chunk_id}", status_code=204)
def delete_model_version(
    chunk_id: str,
    _: dict = Depends(_require_admin_jwt),
    db: Session = Depends(get_db),
):
    chunk = db.query(ModelChunk).filter(ModelChunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="版本不存在")
    db.delete(chunk)
    db.commit()
