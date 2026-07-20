# PBI Credential 申請程式

管理使用者身份、發放 Power BI 存取憑證，並集中管理語意模型分發的 FastAPI 服務，附帶 Vue 3 管理後台與使用者自助頁面。

## 架構概覽

```
FastAPI 後端
  /auth/*       → 使用者自助（註冊、登入、領取 PBI_MASK_KEY，legacy 流程用）
  /api/*        → Skill 呼叫（取得 Azure AD token & 語意模型，legacy 流程，逐步淘汰中）
  /api/admin/*  → 管理後台 API（CRUD、模型上傳）
  /oauth/*      → OAuth 2.1 授權伺服器（給 MCP connector 用，DCR/authorize/token）
  /.well-known/*→ OAuth / MCP metadata（RFC 8414、RFC 9728）
  /mcp          → MCP server（Streamable HTTP，OAuth Bearer token 保護）

Vue 3 SPA（同一 origin）
  /login, /register, /dashboard  → 使用者頁面
  /admin/login, /admin/*         → 管理員後台
```

前端頁面路徑 `/admin/*` 與後端管理 API 路徑 `/api/admin/*` 刻意分開，避免整頁重整／直接輸入網址時，請求被同名後端路由攔截而拿到 JSON 而非 SPA 頁面。

**Skill 端的兩種整合方式**：
- **MCP（推薦，新開發用這個）**：Claude／其他支援 MCP 的 client 透過 `/mcp` 走 OAuth 連線，不需要使用者手動申請、複製、貼上任何金鑰。詳見 [docs/skill-integration.md](docs/skill-integration.md)。
- **REST API + PBI_MASK_KEY（legacy）**：`/api/*` 這組端點仍保留運作，但屬於舊流程，新 skill 開發不建議再串這條路——在 Claude Apps 的 sandbox 環境下，本機寫入的 `PBI_MASK_KEY` 每次對話都會消失，這正是導入 MCP 的原因。

### 安全設計重點

- 每位使用者各自持有 Azure AD Service Principal 憑證（Tenant ID / Client ID / Client Secret）
- Client Secret 以 AES-256-GCM 加密儲存，**不以任何形式傳送給 Skill**
- Skill 呼叫 `/api/token` 時，Server 代為向 Azure AD 換取 access token，Client Secret 不離開 Server
- PBI_MASK_KEY 明文僅在領取時顯示一次，DB 只存 SHA-256 hash

## 快速啟動

**環境需求：** Python 3.11+、Node.js 18+

### 第一次設定

```bash
# Python 虛擬環境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt

# 環境變數
cp .env.example .env
# 編輯 .env，填入 SERVER_JWT_SECRET 與 ADMIN_SECRET

# Node（前端 + concurrently）
cd admin-frontend && npm install && cd ..
npm install
```

### 開發（一行啟動）

```bash
npm run dev
```

同時啟動後端（`http://localhost:8000`）與前端 Vite dev server（`http://localhost:5173`）。
API 文件：`http://localhost:8000/docs`

### 正式部署（Docker）

```bash
docker compose up -d
```

詳見下方 [Docker 部署](#docker-部署) 章節。

## 環境變數

| 變數 | 說明 |
|------|------|
| `SERVER_JWT_SECRET` | 主要金鑰，64 字元隨機 hex。JWT 簽發 + AES-256-GCM key derivation，也是 MCP access token 的簽章金鑰 |
| `ADMIN_SECRET` | 管理後台登入密碼 |
| `DATABASE_URL` | 資料庫連線字串（預設 `sqlite:///./credential.db`） |
| `ALLOWED_IPS` | IP 白名單，逗號分隔。留空表示不限制（例：`1.2.3.4,5.6.7.8`） |
| `SITE_DOMAIN` | 對外網域（不能是裸 IP），Caddy 用來申請 HTTPS 憑證，也是 OAuth issuer / MCP resource URL 的基礎 |

產生安全的隨機金鑰：
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 前端入口

| 網址 | 對象 | 說明 |
|------|------|------|
| `/login` | 使用者 | 帳密登入，取得 8 小時 session |
| `/register` | 使用者 | 申請帳號，等待管理員開通 |
| `/dashboard` | 使用者 | 查看帳號狀態、領取 PBI_MASK_KEY |
| `/admin/login` | 管理員 | 輸入 ADMIN_SECRET，取得 1 小時 JWT |
| `/admin/users` | 管理員 | 使用者管理 |
| `/admin/pbi-configs` | 管理員 | PBI 連線設定管理 |
| `/admin/model` | 管理員 | 語意模型版本管理 |

## API 端點

### Skill API（需 `Authorization: Bearer <PBI_MASK_KEY>`）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/models` | 回傳使用者所有可存取的語意模型（最新版） |
| GET | `/api/token?pbi_config_id=<id>` | Server 向 Azure AD 換取 access token，回傳給 Skill |

`GET /api/token` 回傳格式：
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3599,
  "workspace_id": "...",
  "dataset_id": "...",
  "model_version": 5
}
```

Skill 用 `access_token` + `workspace_id` + `dataset_id` 直接對 Power BI Execute Queries API 執行 DAX 查詢。

> ⚠️ 上面這兩支是 **legacy** 端點，新的 skill 整合請改走下方的 MCP。詳見 [docs/skill-integration.md](docs/skill-integration.md)。

### OAuth（`/oauth/*`、`/.well-known/*`）— 給 MCP connector 用

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/.well-known/oauth-authorization-server` | RFC 8414 metadata |
| GET | `/.well-known/oauth-protected-resource`（含 `/mcp` 後綴版本） | RFC 9728 metadata，指向本 server 當 authorization server |
| POST | `/oauth/register` | Dynamic Client Registration（RFC 7591），public client，不需 secret |
| GET / POST | `/oauth/authorize` | 登入（沿用 `/auth/login` 帳密驗證）+ 同意畫面，核准後發 authorization code |
| POST | `/oauth/token` | `authorization_code`（PKCE S256 必要）或 `refresh_token` grant，換 access token |

Access token 是 1 小時效期的 JWT；refresh token 90 天效期、每次使用會輪換（舊的立即失效）。使用者必須先完成一般的註冊＋管理員審核流程才能在 `/oauth/authorize` 登入成功——OAuth 這層不會繞過帳號審核。

### MCP（`/mcp`，Bearer 保護）

| Tool | 參數 | 說明 |
|------|------|------|
| `list_models` | 無 | 列出使用者可存取的模型（輕量版：id、名稱、說明、表數量） |
| `get_model_detail` | `pbi_config_id` | 取得完整 relationships + tables 結構，含 `workspace_id`/`dataset_id` |
| `get_powerbi_token` | `pbi_config_id` | 核發該設定的 Power BI access token（`access_token`/`token_type`/`expires_in`），**查詢由呼叫端自己直接打 Power BI executeQueries API 執行**，server 不代理查詢本身 |

`get_powerbi_token` 內部同步呼叫 Azure AD（MSAL），用 `anyio.to_thread.run_sync` 丟到背景執行緒執行，避免併發請求時卡住 event loop（早期版本 `run_dax_query` 直接在 server 端執行查詢＋同步阻塞呼叫，並發量大時會拖垮整個服務，已改為現在這個設計）。

### 使用者 API（`/auth/*`）

| 方法 | 路徑 | 驗證 | 說明 |
|------|------|------|------|
| POST | `/auth/register` | 無 | 註冊新帳號 |
| POST | `/auth/login` | 無 | 帳密登入，回傳 8 小時 user session JWT |
| GET | `/auth/me` | Bearer user JWT | 查看帳號狀態與 key 領取狀況 |
| POST | `/auth/mask-key` | Bearer user JWT | 領取 PBI_MASK_KEY（僅顯示一次） |

### 管理員 API（`/api/admin/*`）

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/admin/login` | 輸入 ADMIN_SECRET，回傳 1 小時 admin JWT |
| GET | `/api/admin/users` | 列出所有使用者 |
| PATCH | `/api/admin/users/activate` | 開通／停用帳號、設到期日 |
| PATCH | `/api/admin/users/{id}/credentials` | 設定 Azure AD 憑證（Tenant / Client / Secret） |
| PUT | `/api/admin/users/{id}/pbi-configs` | 指派語意模型（多個） |
| POST | `/api/admin/users/{id}/reset-mask-key` | 重設 PBI_MASK_KEY（清除 hash，使用者重新領取） |
| DELETE | `/api/admin/users/{id}` | 刪除使用者 |
| GET | `/api/admin/pbi-configs` | 列出所有 PBI 設定 |
| POST | `/api/admin/pbi-configs` | 建立 PBI 設定 |
| PATCH | `/api/admin/pbi-configs/{id}` | 更新 PBI 設定 |
| DELETE | `/api/admin/pbi-configs/{id}` | 刪除 PBI 設定（含關聯語意模型） |
| POST | `/api/admin/model/upload` | 上傳語意模型（接受原始 PBI JSON） |
| GET | `/api/admin/model/versions` | 列出所有版本 |
| GET | `/api/admin/model/versions/{v}` | 取得指定版本的表名清單 |
| PATCH | `/api/admin/model/versions/{v}` | 更新版本名稱 |
| DELETE | `/api/admin/model/versions/{v}` | 刪除指定版本 |

## 使用者開通流程

```
1. 使用者前往 /register 申請帳號
2. 管理員在 /admin/users 開通帳號
3. 管理員設定 Azure AD 憑證（Tenant ID / Client ID / Client Secret）
4. 管理員指派一或多個 PBI 設定給使用者
5. 使用者前往 /dashboard 領取 PBI_MASK_KEY（僅顯示一次）
6. 將 PBI_MASK_KEY 填入 nl-to-dax Skill 環境設定
```

## 語意模型上傳

管理員在 `/admin/model` 頁面可：
- 上傳原始 Power BI JSON（`clientDataModel` 格式），後端自動解析，需指定關聯的 PBI 設定
- 為版本命名，方便識別
- 依 PBI 設定篩選版本列表
- 刪除不需要的版本

本地驗證解析結果：
```bash
python scripts/chunk_model.py path/to/model.json
# 輸出至 ./output/relationships.json 與 ./output/tables/
```

## 資料模型

| 資料表 | 說明 |
|--------|------|
| `users` | 帳號、密碼 hash、mask_key hash、Azure AD 憑證（AES-256-GCM 加密）、啟用狀態、到期時間 |
| `pbi_config` | Power BI 連線設定（workspace_id、dataset_id） |
| `user_pbi_configs` | 使用者與 PBI 設定的多對多指派關係 |
| `model_chunks` | 語意模型版本（版本號、名稱、pbi_config_id、relationships JSON、tables JSON） |
| `oauth_clients` | MCP connector 透過 DCR 註冊的 client（public client，不存 secret） |
| `oauth_authorization_codes` | 短效期一次性 authorization code（PKCE challenge、5 分鐘過期、用過即作廢） |
| `oauth_refresh_tokens` | 長效 refresh token（只存 hash，90 天效期，每次使用輪換） |

## Docker 部署

```bash
# 建立資料目錄（SQLite 持久化）
mkdir -p data

# 設定環境變數
cp .env.example .env
# 編輯 .env，記得填 SITE_DOMAIN（Caddy 用來自動申請 HTTPS 憑證，不能是裸 IP）

# 啟動
docker compose up -d

# 查看 log
docker compose logs -f
```

服務前面掛了 [Caddy](https://caddyserver.com/) 做 TLS termination，自動跟 Let's Encrypt 要憑證並自動續約（設定見 [Caddyfile](Caddyfile)）。對外只開 80/443，`app` 容器的 8000 port 不再直接對外暴露，一律經過 Caddy 反向代理。第一次啟動時 Caddy 需要 80/443 對外可連才能完成 ACME 驗證，記得 VM 防火牆/安全群組要開這兩個 port。

更新部署：
```bash
git pull
docker compose up --build -d
docker image prune -f
```

## 專案結構

```
├── app/
│   ├── main.py           FastAPI 入口（CORS、SPA 靜態服務、DB migration、IP 白名單、MCP mount + lifespan）
│   ├── database.py       SQLAlchemy 設定
│   ├── models.py         ORM 資料模型（含 OAuth 相關表）
│   ├── security.py       密碼 hash、JWT 簽發、AES 加解密、PKCE 驗證、MCP token 簽發
│   └── routers/
│       ├── auth.py       /auth 路由（使用者）
│       ├── credential.py /api 路由（Skill legacy，也提供 acquire_powerbi_token 給 MCP 用）
│       ├── admin.py      /api/admin 路由（管理員）
│       ├── oauth.py      /oauth、/.well-known 路由（OAuth 2.1 authorization server）
│       └── mcp.py        /mcp 路由（MCP server + tools）
├── admin-frontend/       Vue 3 SPA（Element Plus + Pinia）
├── scripts/
│   └── chunk_model.py    PBI JSON 解析核心（後端 import + CLI 兩用）
├── tests/                pytest 套件（OAuth flow + MCP 協定完整往返測試）
├── docs/
│   └── skill-integration.md  Skill 串接指南（MCP 為主，legacy REST API 為輔）
├── Dockerfile
├── docker-compose.yml
├── Caddyfile             TLS termination（Let's Encrypt 自動憑證）
├── package.json          concurrently dev script（npm run dev）
├── requirements.txt
├── requirements-dev.txt  requirements.txt + pytest
└── .env.example
```

## 測試

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

涵蓋完整 OAuth flow（DCR → authorize → PKCE → token → refresh 輪換 → 重放防護）與完整 MCP 協定往返（真實啟動 uvicorn + `mcp` client SDK 連線、list tools、call tool、權限檢查）。

> 開發者請參閱 [CLAUDE.md](CLAUDE.md) 取得認證設計、關鍵安全細節與啟動流程。
