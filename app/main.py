from dotenv import load_dotenv
load_dotenv()

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import text
from app.database import engine, Base
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
    ]:
        try:
            _conn.execute(text(_stmt))
            _conn.commit()
        except Exception:
            pass

_mcp_server = mcp_router.get_mcp_server()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with _mcp_server.session_manager.run():
        yield


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


@app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def _mcp_no_trailing_slash(request: Request):
    # Starlette 的 Mount 只認得帶尾斜線的 "/mcp/"，裸路徑 "/mcp" 不會進到 mount，
    # 會被後面的 SPA catch-all 攔走變成 404。這裡先攔一手，307 保留 method/body 轉去 "/mcp/"。
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"/mcp/{query}", status_code=307)


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
