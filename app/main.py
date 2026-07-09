from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from app.database import engine, Base
from app.routers import auth, credential, admin

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

app = FastAPI(title="PBI Credential 申請程式", version="0.1.0")


@app.middleware("http")
async def ip_whitelist(request: Request, call_next):
    if ALLOWED_IPS:
        forwarded_for = request.headers.get("X-Forwarded-For")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "")
        if client_ip not in ALLOWED_IPS:
            return JSONResponse(status_code=403, content={"detail": f"IP {client_ip} 不在白名單中"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(credential.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}


FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "admin-frontend", "dist")

if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        if full_path.startswith(("api/", "auth/", "health")):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(
            os.path.join(FRONTEND_DIST, "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
