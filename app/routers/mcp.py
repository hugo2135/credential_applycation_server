import os

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app.database import SessionLocal
from app.models import ModelChunk, PbiConfig, User, UserPbiConfig
from app.routers.credential import acquire_powerbi_token
from app.security import verify_mcp_access_token


def _issuer() -> str:
    domain = os.getenv("SITE_DOMAIN", "")
    return f"https://{domain}" if domain else "http://localhost:8000"


def _allowed_hosts_and_origins() -> tuple[list[str], list[str]]:
    # mcp SDK 內建 DNS rebinding 防護，預設 allowed_hosts/allowed_origins 是空清單
    # （等於全擋），一定要把實際對外網域加進去，不然所有 /mcp 請求都會被判定
    # Invalid Host header 而回 421。
    domain = os.getenv("SITE_DOMAIN", "")
    if domain:
        # Origin 沒帶（server-to-server 呼叫常見）就直接放行，這裡的清單只在瀏覽器
        # 端真的帶了 Origin header 時才用得到。claude.ai 是目前已知會用瀏覽器走 OAuth
        # 流程的 client；之後如果其他 MCP client 也在瀏覽器端呼叫、被 Invalid Origin
        # header 擋下，比照這裡加進去即可。
        return [domain], [f"https://{domain}", "https://claude.ai"]
    # 本機開發／測試 port 不固定（pytest 的 live_server 用 port=0 隨機挑），用 :* 萬用字元。
    return ["localhost:*", "127.0.0.1:*"], ["http://localhost:*", "http://127.0.0.1:*"]


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
    allowed_hosts, allowed_origins = _allowed_hosts_and_origins()
    server = FastMCP(
        name="pbi-credential-mcp",
        instructions="查詢使用者被授權存取的 Power BI 語意模型結構，並取得執行 DAX 查詢所需的 access token（實際查詢由呼叫端直接對 Power BI REST API 執行）。",
        token_verifier=_JwtTokenVerifier(),
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=f"{issuer}/mcp",
        ),
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
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
        """取得指定 PBI 設定的完整語意模型結構（relationships + tables + filters），DAX 生成前查表格/欄位/量值/篩選規則用。"""
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
                "workspace_id": config.workspace_id,
                "dataset_id": config.dataset_id,
                "filters": config.filters or [],
                "relationships": latest.relationships,
                "tables": latest.tables,
            }

    def _get_powerbi_token_sync(pbi_config_id: str) -> dict:
        with SessionLocal() as db:
            user = _current_user(db)
            _check_access(user, pbi_config_id, db)
            if not user.tenant_id or not user.client_id or not user.client_secret_enc:
                raise ToolError("Azure AD 憑證尚未設定，請聯絡管理員")
            result = acquire_powerbi_token(user)
        return {
            "access_token": result["access_token"],
            "token_type": "Bearer",
            "expires_in": result.get("expires_in", 3600),
        }

    @server.tool()
    async def get_powerbi_token(pbi_config_id: str) -> dict:
        """取得指定 PBI 設定的 Power BI access token（Azure AD 核發），用來直接呼叫 Power BI
        executeQueries API 執行 DAX 查詢。workspace_id/dataset_id 請從 get_model_detail 取得，
        這裡不重複回傳。Token 效期見 expires_in（秒）：在效期內請重複使用同一個 token，
        不要每次查詢都呼叫這個 tool；但也不要把 token 寫進本機檔案跨對話持久化。"""
        # acquire_powerbi_token 內部是同步阻塞的 Azure AD 網路呼叫（msal），這裡丟到背景執行緒，
        # 避免卡住整個 server 的 event loop（並發多個查詢時會互相卡住，見 commit history）。
        return await anyio.to_thread.run_sync(_get_powerbi_token_sync, pbi_config_id)

    _mcp_server = server
    return server
