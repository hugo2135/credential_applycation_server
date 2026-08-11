import os
from datetime import datetime, timedelta

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app.access_log import get_mcp_request_context, record_access
from app.database import SessionLocal
from app.models import AccessTicket, ModelChunk, PbiConfig, PersonalAccessToken, User, UserPbiConfig
from app.routers.ticket import ticket_ttl_seconds
from app.security import generate_access_ticket, hash_opaque_token, verify_mcp_access_token


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
            ctx = get_mcp_request_context()
            with SessionLocal() as db:
                record_access(
                    db,
                    user_id=payload.get("sub"),
                    email=payload.get("email"),
                    auth_method="oauth",
                    path="/mcp",
                    method=ctx["method"],
                    ip_address=ctx["ip"],
                )
            return AccessToken(
                token=token,
                client_id=payload.get("client_id", ""),
                scopes=[],
                subject=payload.get("sub"),
                claims=payload,
            )
        except Exception:
            pass

        # 不是 OAuth 發的 JWT，查是不是使用者自己在 /mcp-tokens 產生的 personal
        # access token（給不支援完整 OAuth 流程的 MCP client，例如 Antigravity）。
        with SessionLocal() as db:
            pat = db.query(PersonalAccessToken).filter(
                PersonalAccessToken.token_hash == hash_opaque_token(token)
            ).first()
            if not pat:
                return None
            pat.last_used_at = datetime.utcnow()
            user = db.query(User).filter(User.id == pat.user_id).first()
            ctx = get_mcp_request_context()
            record_access(  # 內部會 commit，一併把上面 last_used_at 的更新存下去
                db,
                user_id=pat.user_id,
                email=user.email if user else None,
                auth_method="pat",
                path="/mcp",
                method=ctx["method"],
                ip_address=ctx["ip"],
            )
            return AccessToken(
                token=token,
                client_id="personal-access-token",
                scopes=[],
                subject=pat.user_id,
                claims={},
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


def _log_tool_access(db, user: User, tool_name: str) -> None:
    # _JwtTokenVerifier 只在每個 HTTP request 驗證 token 時記一筆通用的 "/mcp"，
    # 不知道這個 request 實際觸發了哪個 tool（initialize/list_tools 這些協定層
    # 呼叫也會經過那裡）。這裡額外補一筆更精確的紀錄，path 帶上實際的 tool 名稱，
    # 讓管理員在 /admin/access-logs 能看到「哪個使用者、什麼時候、觸發了哪個功能」。
    access_token = get_access_token()
    auth_method = "pat" if access_token and access_token.client_id == "personal-access-token" else "oauth"
    ctx = get_mcp_request_context()
    record_access(
        db,
        user_id=user.id,
        email=user.email,
        auth_method=auth_method,
        path=f"/mcp/{tool_name}",
        method=ctx["method"],
        ip_address=ctx["ip"],
    )


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
            _log_tool_access(db, user, "list_models")
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
                    "query_modes": [
                        {"mode_id": m.get("mode_id"), "name": m.get("name"), "description": m.get("description")}
                        for m in (config.query_modes or [])
                    ],
                })
            return result

    @server.tool()
    async def get_model_detail(pbi_config_id: str, mode_id: str | None = None) -> dict:
        """取得指定 PBI 設定的完整語意模型結構（relationships + tables + filters + column_aliases），
        DAX 生成前查表格/欄位/量值/篩選規則/欄位別名用。mode_id 選填：list_models 回傳的
        query_modes 若有多個選項，先讓使用者選一個再帶進來，只回該模式範圍內的表，
        且該模式自己的篩選規則會疊加成一筆 alwaysApply 的 filter profile。不帶 mode_id
        時行為跟以前完全一樣（全表、不含模式篩選）。"""
        with SessionLocal() as db:
            user = _current_user(db)
            _log_tool_access(db, user, "get_model_detail")
            config = _check_access(user, pbi_config_id, db)
            latest = (
                db.query(ModelChunk)
                .filter(ModelChunk.pbi_config_id == pbi_config_id)
                .order_by(ModelChunk.model_version.desc())
                .first()
            )
            if not latest:
                raise ToolError("此 PBI 設定尚未上傳任何語意模型")

            tables = latest.tables
            filters = list(config.filters or [])
            if mode_id:
                mode = next((m for m in (config.query_modes or []) if m.get("mode_id") == mode_id), None)
                if not mode:
                    raise ToolError(f"找不到查詢模式：{mode_id}")
                mode_tables = mode.get("tables") or []
                if mode_tables:
                    tables = [t for t in tables if t.get("table") in mode_tables]
                if mode.get("filters"):
                    filters.append({
                        "filterId": f"mode:{mode_id}",
                        "name": mode.get("name", mode_id),
                        "description": mode.get("description"),
                        "alwaysApply": True,
                        "overrideDefaults": False,
                        "contextKeywords": [],
                        "filters": mode["filters"],
                    })

            return {
                "pbi_config_id": config.id,
                "pbi_config_name": config.name,
                "model_version": latest.model_version,
                "workspace_id": config.workspace_id,
                "dataset_id": config.dataset_id,
                "query_mode_id": mode_id,
                "filters": filters,
                "column_aliases": config.column_aliases or [],
                "relationships": latest.relationships,
                "tables": tables,
            }

    @server.tool()
    async def get_query_ticket(pbi_config_id: str) -> dict:
        """取得執行 DAX 查詢用的一次性 ticket。

        **這不是 access token，本身不能拿來呼叫 Power BI**，而且它是短效、單次使用的
        （見 expires_in，秒）。正確用法是把 ticket 原樣交給你的查詢腳本，由腳本自己
        POST 到 redeem_url（body: {"ticket": "..."}）換取真正的 access token 後直接
        呼叫 Power BI executeQueries API。

        **請在真正要執行查詢的前一刻才呼叫這個 tool**：所有澄清、選項確認、DAX 生成
        都完成之後再拿 ticket。ticket 會過期，中間若還要跟使用者來回確認，等回來時
        它可能已經失效了。

        **不要把 ticket 或換到的 token 寫進檔案、也不要顯示給使用者**——真正的 token
        只應該存在於查詢腳本的行程記憶體裡。ticket 用過就失效，不需要也不應該快取；
        每次要執行查詢就重新呼叫這個 tool 拿一張新的。

        如果腳本兌換時收到「ticket 已過期」，直接重新呼叫這個 tool 拿新的再跑一次即可，
        這沒有任何副作用。

        workspace_id/dataset_id 請從 get_model_detail 取得，這裡不重複回傳。
        """
        with SessionLocal() as db:
            user = _current_user(db)
            _log_tool_access(db, user, "get_query_ticket")
            _check_access(user, pbi_config_id, db)
            # 先擋掉憑證沒設定的情況：不然使用者要等到腳本 redeem 時才會失敗，
            # 那時候的錯誤訊息離問題根源更遠、更難查。
            if not user.tenant_id or not user.client_id or not user.client_secret_enc:
                raise ToolError("Azure AD 憑證尚未設定，請聯絡管理員")

            ttl = ticket_ttl_seconds()
            raw_ticket = generate_access_ticket()
            db.add(AccessTicket(
                token_hash=hash_opaque_token(raw_ticket),
                user_id=user.id,
                pbi_config_id=pbi_config_id,
                expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            ))
            db.commit()

        return {
            "ticket": raw_ticket,
            "redeem_url": f"{_issuer()}/api/ticket/redeem",
            "expires_in": ttl,
        }

    _mcp_server = server
    return server
