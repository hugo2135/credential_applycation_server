from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from app.access_log import set_mcp_request_context
from app.database import engine, Base, SessionLocal
from app.models import AccessLog
from app.routers import auth, credential, admin, oauth
from app.routers import mcp as mcp_router

_raw_ips = os.getenv("ALLOWED_IPS", "")
ALLOWED_IPS: set[str] = {ip.strip() for ip in _raw_ips.split(",") if ip.strip()}

Base.metadata.create_all(bind=engine)

# pbi_config schema 遷移：移除舊的 NOT NULL 憑證欄位
with engine.connect() as _conn:
    try:
        rows = _conn.execute(text("PRAGMA table_info(pbi_config)")).fetchall()
        col_names = [r[1] for r in rows]
        if "tenant_id" in col_names:
            _conn.execute(text("""
                CREATE TABLE pbi_config_v2 (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    workspace_id TEXT,
                    dataset_id TEXT,
                    updated_at DATETIME
                )
            """))
            _conn.execute(text("""
                INSERT INTO pbi_config_v2 (id, name, workspace_id, dataset_id, updated_at)
                SELECT id, name, workspace_id, dataset_id, updated_at FROM pbi_config
            """))
            _conn.execute(text("DROP TABLE pbi_config"))
            _conn.execute(text("ALTER TABLE pbi_config_v2 RENAME TO pbi_config"))
            _conn.commit()
    except Exception as _e:
        print(f"[migration] pbi_config schema: {_e}")

# 自動補欄位（不刪資料的輕量 migration）
with engine.connect() as _conn:
    for _stmt in [
        "ALTER TABLE model_chunks ADD COLUMN name TEXT",
        "ALTER TABLE model_chunks ADD COLUMN pbi_config_id TEXT REFERENCES pbi_config(id)",
        "ALTER TABLE model_chunks ADD COLUMN model_description TEXT",
        """CREATE TABLE IF NOT EXISTS user_pbi_configs (
            user_id TEXT NOT NULL REFERENCES users(id),
            pbi_config_id TEXT NOT NULL REFERENCES pbi_config(id),
            PRIMARY KEY (user_id, pbi_config_id)
        )""",
        # 將舊的 users.pbi_config_id 單一綁定遷移至多對多表
        "INSERT OR IGNORE INTO user_pbi_configs (user_id, pbi_config_id) SELECT id, pbi_config_id FROM users WHERE pbi_config_id IS NOT NULL",
        "ALTER TABLE users ADD COLUMN tenant_id TEXT",
        "ALTER TABLE users ADD COLUMN client_id TEXT",
        "ALTER TABLE users ADD COLUMN client_secret_enc TEXT",
        "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE pbi_config ADD COLUMN filters TEXT",
        "ALTER TABLE pbi_config ADD COLUMN query_modes TEXT",
        "ALTER TABLE pbi_config ADD COLUMN column_aliases TEXT",
    ]:
        try:
            _conn.execute(text(_stmt))
            _conn.commit()
        except Exception:
            pass

_mcp_server = mcp_router.get_mcp_server()


class _McpTrailingSlashFix:
    """Starlette 的 Mount 只認得帶尾斜線的 "/mcp/"，裸路徑 "/mcp" 原本要靠 307
    轉址到 "/mcp/" 才能命中。但部分 MCP client（例如 Gemini）跟隨轉址重新發送
    請求時不會保留原本的 Authorization header，導致認證失敗。改成在 ASGI 層、
    Starlette Router 決定路由之前，直接把路徑補上尾斜線再往下傳，同一個請求
    內處理完，client 端完全不會看到任何轉址，也就不會有 header 掉的問題。
    必須包住整個 app（而不是只包 /mcp 掛載的 sub-app），因為 Router 比對路徑
    是否命中 Mount 這一步，發生在 sub-app 被呼叫之前。

    同時順便把這次連線的 client IP／HTTP method 存進 access_log 的 contextvar：
    mcp.py 的 _JwtTokenVerifier 只拿得到 token 字串、沒有 Request 物件，唯一能
    取得這兩個值的地方就是這裡的原始 ASGI scope。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            headers = dict(scope.get("headers") or [])
            forwarded_for = headers.get(b"x-forwarded-for")
            if forwarded_for:
                ip = forwarded_for.decode().split(",")[0].strip()
            else:
                client = scope.get("client")
                ip = client[0] if client else None
            set_mcp_request_context(ip=ip, method=scope.get("method"))

        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)


ACCESS_LOG_RETENTION_DAYS = 90


async def _cleanup_access_logs_loop():
    # 存取歷史只留 90 天，沒有另外掛排程服務，開一個背景 task 每天跑一次清舊資料。
    while True:
        cutoff = datetime.utcnow() - timedelta(days=ACCESS_LOG_RETENTION_DAYS)
        with SessionLocal() as db:
            db.query(AccessLog).filter(AccessLog.created_at < cutoff).delete(synchronize_session=False)
            db.commit()
        await asyncio.sleep(24 * 60 * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    cleanup_task = asyncio.create_task(_cleanup_access_logs_loop())
    async with _mcp_server.session_manager.run():
        yield
    cleanup_task.cancel()


app = FastAPI(title="PBI Credential 申請程式", version="0.1.0", lifespan=lifespan)


# OAuth/MCP 這幾條路徑本來就要給不特定第三方（使用者的瀏覽器、Claude 的伺服器）連，
# 不可能限制在內網——安全性靠 OAuth 本身（PKCE + 登入 + 同意畫面）把關，不是靠 IP。
# 其餘路徑（含 /admin/*、/auth/*）維持原本「僅限內網」的設計，不在這個排除清單內。
_IP_WHITELIST_EXEMPT_PREFIXES = ("/oauth/", "/.well-known/", "/mcp")


@app.middleware("http")
async def ip_whitelist(request: Request, call_next):
    if ALLOWED_IPS and not request.url.path.startswith(_IP_WHITELIST_EXEMPT_PREFIXES):
        forwarded_for = request.headers.get("X-Forwarded-For")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "")
        if client_ip not in ALLOWED_IPS:
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    # OAuth/MCP 端點（DCR、authorize、token、metadata）設計上就是要給任意第三方 OAuth
    # client（例如 claude.ai 的瀏覽器端 JS）跨網域呼叫，不能只鎖 admin-frontend 這個
    # 已知來源；這幾支端點本身用 PKCE + 使用者登入 + 同意畫面把關，CORS 在這裡本來就
    # 不是主要防線，所以乾脆全域放開。
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(credential.router)
app.include_router(admin.router)
app.include_router(oauth.router)


app.mount("/mcp", _mcp_server.streamable_http_app())


@app.get("/health")
def health():
    return {"status": "ok"}


FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "admin-frontend", "dist")

if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        if full_path.startswith(("api/", "auth/", "health", "oauth/", ".well-known/", "mcp")):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(
            os.path.join(FRONTEND_DIST, "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )


# 一定要包在所有路由/掛載都註冊完之後：往下轉發給 FastAPI 的 router 前，先攔截
# 裸路徑 "/mcp"，讓它補上尾斜線後才進入路由比對（見 _McpTrailingSlashFix 說明）。
app = _McpTrailingSlashFix(app)
