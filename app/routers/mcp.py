import os

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from app.database import SessionLocal
from app.models import ModelChunk, PbiConfig, User, UserPbiConfig
from app.routers.credential import execute_dax_query
from app.security import verify_mcp_access_token


def _issuer() -> str:
    domain = os.getenv("SITE_DOMAIN", "")
    return f"https://{domain}" if domain else "http://localhost:8000"


class _JwtTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = verify_mcp_access_token(token)
        except Exception:
            return None
        return AccessToken(
            token=token,
            client_id=payload.get("client_id", ""),
            scopes=[],
            subject=payload.get("sub"),
            claims=payload,
        )


def _current_user(db) -> User:
    access_token = get_access_token()
    if not access_token or not access_token.subject:
        raise ToolError("未授權：請重新連線")
    user = db.query(User).filter(User.id == access_token.subject).first()
    if not user:
        raise ToolError("使用者不存在")
    if not user.is_active:
        raise ToolError("帳號已停用，請聯絡管理員")
    return user


def _check_access(user: User, pbi_config_id: str, db) -> PbiConfig:
    link = db.query(UserPbiConfig).filter(
        UserPbiConfig.user_id == user.id,
        UserPbiConfig.pbi_config_id == pbi_config_id,
    ).first()
    if not link:
        raise ToolError("無此 PBI 設定的存取權")
    config = db.query(PbiConfig).filter(PbiConfig.id == pbi_config_id).first()
    if not config:
        raise ToolError("PBI 設定不存在，請聯絡管理員")
    return config


_mcp_server: FastMCP | None = None


def get_mcp_server() -> FastMCP:
    global _mcp_server
    if _mcp_server is not None:
        return _mcp_server

    issuer = _issuer()
    server = FastMCP(
        name="pbi-credential-mcp",
        instructions="查詢使用者被授權存取的 Power BI 語意模型，並執行 DAX 查詢。",
        token_verifier=_JwtTokenVerifier(),
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=f"{issuer}/mcp",
        ),
        # 這個 app 之後會被 main.py mount 在 /mcp 上，這裡的路徑要設成根路徑，
        # 不然對外實際路徑會變成 /mcp/mcp。
        streamable_http_path="/",
    )

    @server.tool()
    async def list_models() -> list[dict]:
        """列出目前使用者被授權存取的所有 PBI 語意模型（輕量版：id、名稱、說明、表數量，不含完整結構）。"""
        with SessionLocal() as db:
            user = _current_user(db)
            links = db.query(UserPbiConfig).filter(UserPbiConfig.user_id == user.id).all()
            result = []
            for link in links:
                config = db.query(PbiConfig).filter(PbiConfig.id == link.pbi_config_id).first()
                if not config:
                    continue
                latest = (
                    db.query(ModelChunk)
                    .filter(ModelChunk.pbi_config_id == link.pbi_config_id)
                    .order_by(ModelChunk.model_version.desc())
                    .first()
                )
                if not latest:
                    continue
                result.append({
                    "pbi_config_id": config.id,
                    "pbi_config_name": config.name,
                    "model_version": latest.model_version,
                    "model_description": latest.model_description,
                    "table_count": len(latest.tables) if latest.tables else 0,
                })
            return result

    @server.tool()
    async def get_model_detail(pbi_config_id: str) -> dict:
        """取得指定 PBI 設定的完整語意模型結構（relationships + tables），DAX 生成前查表格/欄位/量值用。"""
        with SessionLocal() as db:
            user = _current_user(db)
            config = _check_access(user, pbi_config_id, db)
            latest = (
                db.query(ModelChunk)
                .filter(ModelChunk.pbi_config_id == pbi_config_id)
                .order_by(ModelChunk.model_version.desc())
                .first()
            )
            if not latest:
                raise ToolError("此 PBI 設定尚未上傳任何語意模型")
            return {
                "pbi_config_id": config.id,
                "pbi_config_name": config.name,
                "model_version": latest.model_version,
                "relationships": latest.relationships,
                "tables": latest.tables,
            }

    @server.tool()
    async def run_dax_query(pbi_config_id: str, dax: str) -> list[dict]:
        """對指定 PBI 設定執行 DAX 查詢（須為完整 EVALUATE 查詢語法），回傳查詢結果列。"""
        with SessionLocal() as db:
            user = _current_user(db)
            config = _check_access(user, pbi_config_id, db)
            if not user.tenant_id or not user.client_id or not user.client_secret_enc:
                raise ToolError("Azure AD 憑證尚未設定，請聯絡管理員")
            return execute_dax_query(user, config, dax)

    _mcp_server = server
    return server
