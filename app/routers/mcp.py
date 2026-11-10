import os
from datetime import datetime, timedelta
from functools import lru_cache

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app import bookmarks as bookmark_store
from app.access_log import get_mcp_request_context, record_access
from app.database import SessionLocal
from app.models import AccessTicket, ModelChunk, PbiConfig, PersonalAccessToken, User, UserPbiConfig
from app.routers.ticket import EXPIRED_ACCOUNT_MESSAGE, ticket_ttl_seconds
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
    # 比照 legacy REST 與 ticket redeem：沒在這裡擋的話，過期使用者還能列模型、
    # 領 ticket，要到腳本兌換時才失敗，離問題根源太遠、也看不出是哪一步出錯。
    if user.expires_at and user.expires_at < datetime.utcnow():
        raise ToolError(EXPIRED_ACCOUNT_MESSAGE)
    return user


def _log_tool_access(db, user: User, tool_name: str, detail: str | None = None) -> None:
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
        detail=detail,
    )


class _ModelChunkMissing(Exception):
    """內部用：找不到指定版本的語意模型。

    刻意用例外而不是回傳 None，因為 `functools.lru_cache` **不會快取例外**。若快取了
    None，「把某個設定的版本全部刪光後重新上傳」會讓版本號從 1 重新開始（見 admin.py
    的 upload_model），然後撞到先前快取的 None 而誤判成「尚未上傳任何語意模型」。
    """


# 每筆約等於一份語意模型的大小（實測單一模型的 JSON 約 95KB），16 筆上限約 1.5MB，
# 對 1GB RAM 的小型 VM 是可以接受的常駐量。
_MODEL_CHUNK_CACHE_SIZE = 16


@lru_cache(maxsize=_MODEL_CHUNK_CACHE_SIZE)
def _load_model_chunk(pbi_config_id: str, model_version: int) -> tuple[dict, list]:
    """讀取並快取語意模型的 relationships/tables。

    這是 `get_model_detail` 最貴的部分：單一模型的 JSON 實測約 95KB，每次呼叫都要讓
    SQLite 把 TEXT 讀出來再 `json.loads` 成 Python 物件，在小型 VM 上是實際負擔，而且
    每個對話都至少會呼叫一次。

    **快取 key 刻意只有 `(pbi_config_id, model_version)`**，不含 `PbiConfig` 的任何欄位——
    因為這裡只快取「上傳之後就不會再變的模型結構」。`filters`／`query_modes`／
    `column_aliases`／`workspace_id`／`dataset_id` 這些管理員隨時會在詳情頁改的東西，
    一律由呼叫端每次從 `config` 物件現讀，所以改完立刻生效，不會因為快取而讀到舊值。
    上傳新版本會讓 `model_version` 變動、key 自然改變，也就不需要任何主動失效機制。

    回傳的結構是**多個呼叫共用的**，呼叫端只能讀、不可以就地修改。
    """
    with SessionLocal() as db:
        chunk = (
            db.query(ModelChunk)
            .filter(
                ModelChunk.pbi_config_id == pbi_config_id,
                ModelChunk.model_version == model_version,
            )
            .first()
        )
        if not chunk:
            raise _ModelChunkMissing
        return chunk.relationships, chunk.tables


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
            _log_tool_access(db, user, "get_model_detail", detail=pbi_config_id)
            config = _check_access(user, pbi_config_id, db)
            # 只撈 model_version 這一欄，不要整列 select——整列會連 relationships/tables
            # 兩個大 JSON 欄位一起讀出來並解析，那正是下面要靠快取避開的成本。
            latest = (
                db.query(ModelChunk.model_version)
                .filter(ModelChunk.pbi_config_id == pbi_config_id)
                .order_by(ModelChunk.model_version.desc())
                .first()
            )
            if not latest:
                raise ToolError("此 PBI 設定尚未上傳任何語意模型")
            model_version = latest[0]

            try:
                relationships, tables = _load_model_chunk(pbi_config_id, model_version)
            except _ModelChunkMissing:
                raise ToolError("此 PBI 設定尚未上傳任何語意模型")

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
                "model_version": model_version,
                "workspace_id": config.workspace_id,
                "dataset_id": config.dataset_id,
                "query_mode_id": mode_id,
                "filters": filters,
                # v1.5 起每組都有欄位本身的 aliases，舊資料沒有這個 key，補成空陣列讓 skill 端不用判斷
                "column_aliases": [{**g, "aliases": g.get("aliases") or []} for g in (config.column_aliases or [])],
                "relationships": relationships,
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
            _log_tool_access(db, user, "get_query_ticket", detail=pbi_config_id)
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

    @server.tool()
    async def list_bookmarks(pbi_config_id: str | None = None) -> list[dict]:
        """列出使用者存過的書籤（常用查詢），可用 pbi_config_id 只看某個模型的。

        每筆含 title、dax、question（存檔時的原始自然語言問題）。執行書籤時跟一般查詢
        一樣：先呼叫 get_query_ticket，再把書籤的 dax 交給查詢腳本。

        **possibly_outdated 為 true 時**，代表存檔後語意模型升過版（model_version !=
        current_model_version），DAX 引用的表/欄位可能已改名或刪除。這時請先告知使用者，
        並建議改用 question 搭配 get_model_detail 重新生成 DAX，不要直接執行舊的 DAX。
        """
        with SessionLocal() as db:
            user = _current_user(db)
            _log_tool_access(db, user, "list_bookmarks", detail=pbi_config_id)
            try:
                return bookmark_store.list_bookmarks(db, user.id, pbi_config_id)
            except bookmark_store.BookmarkError as e:
                raise ToolError(str(e))

    @server.tool()
    async def save_bookmark(
        pbi_config_id: str,
        title: str,
        dax: str,
        question: str | None = None,
        overwrite: bool = False,
    ) -> dict:
        """把一個查詢存成書籤。title 是給使用者辨識用的名稱，dax 是完整的 DAX 查詢，
        question 建議一併帶上使用者原本的自然語言問題（模型改版後可以據此重新生成 DAX）。

        **同一個模型下標題不可重複。** 第一次呼叫請一律用 overwrite=false：若已有同名
        書籤，這裡不會覆蓋，而是回傳 saved=false、conflict=true 以及既有書籤的內容。
        **這時必須先把既有書籤的內容告訴使用者，詢問是否要覆蓋**，使用者同意後才可以帶
        overwrite=true 再呼叫一次；使用者不同意就請他換一個標題。不可以未經使用者同意
        就自行帶 overwrite=true。
        """
        with SessionLocal() as db:
            user = _current_user(db)
            _log_tool_access(db, user, "save_bookmark", detail=pbi_config_id)
            try:
                status, bookmark = bookmark_store.save_bookmark(
                    db, user.id, pbi_config_id, title, dax, question, overwrite,
                )
            except bookmark_store.BookmarkError as e:
                raise ToolError(str(e))
            config = db.query(PbiConfig).filter(PbiConfig.id == pbi_config_id).first()
            item = bookmark_store.bookmark_dict(
                bookmark, config.name if config else None,
                bookmark_store.latest_model_version(db, pbi_config_id),
            )
            if status == "conflict":
                return {
                    "saved": False,
                    "conflict": True,
                    "message": "已有同名書籤，請先詢問使用者是否覆蓋；同意後帶 overwrite=true 再呼叫一次",
                    "existing": item,
                }
            return {"saved": True, "conflict": False, "status": status, "bookmark": item}

    @server.tool()
    async def delete_bookmark(bookmark_id: str) -> dict:
        """刪除一個書籤（bookmark_id 從 list_bookmarks 取得）。刪除前請先跟使用者確認。"""
        with SessionLocal() as db:
            user = _current_user(db)
            _log_tool_access(db, user, "delete_bookmark", detail=bookmark_id)
            if not bookmark_store.delete_bookmark(db, user.id, bookmark_id):
                raise ToolError("找不到這個書籤")
            return {"deleted": True}

    _mcp_server = server
    return server
