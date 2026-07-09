# PBI Credential 申請程式

管理使用者身份、發放 Power BI 存取憑證，並集中管理語意模型分發的 FastAPI 服務，附帶 Vue 3 管理後台與使用者自助頁面。

## 架構概覽

```
FastAPI 後端
  /auth/*       → 使用者自助（註冊、登入、領取 PBI_MASK_KEY）
  /api/*        → Skill 呼叫（取得 Azure AD token & 語意模型）
  /api/admin/*  → 管理後台 API（CRUD、模型上傳）

Vue 3 SPA（同一 origin）
  /login, /register, /dashboard  → 使用者頁面
  /admin/login, /admin/*         → 管理員後台
```

前端頁面路徑 `/admin/*` 與後端管理 API 路徑 `/api/admin/*` 刻意分開，避免整頁重整／直接輸入網址時，請求被同名後端路由攔截而拿到 JSON 而非 SPA 頁面。

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
| `SERVER_JWT_SECRET` | 主要金鑰，64 字元隨機 hex。JWT 簽發 + AES-256-GCM key derivation |
| `ADMIN_SECRET` | 管理後台登入密碼 |
| `DATABASE_URL` | 資料庫連線字串（預設 `sqlite:///./credential.db`） |
| `ALLOWED_IPS` | IP 白名單，逗號分隔。留空表示不限制（例：`1.2.3.4,5.6.7.8`） |

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

Skill 用 `access_token` + `workspace_id` + `dataset_id` 直接對 Power BI Execute Queries API 執行 DAX 查詢。詳見 [docs/skill-integration.md](docs/skill-integration.md)。

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

## Docker 部署

```bash
# 建立資料目錄（SQLite 持久化）
mkdir -p data

# 設定環境變數
cp .env.example .env
# 編輯 .env

# 啟動
docker compose up -d

# 查看 log
docker compose logs -f
```

更新部署：
```bash
git pull
docker compose up --build -d
docker image prune -f
```

## 專案結構

```
├── app/
│   ├── main.py           FastAPI 入口（CORS、SPA 靜態服務、DB migration、IP 白名單）
│   ├── database.py       SQLAlchemy 設定
│   ├── models.py         ORM 資料模型
│   ├── security.py       密碼 hash、JWT 簽發、AES 加解密
│   └── routers/
│       ├── auth.py       /auth 路由（使用者）
│       ├── credential.py /api 路由（Skill）
│       └── admin.py      /api/admin 路由（管理員）
├── admin-frontend/       Vue 3 SPA（Element Plus + Pinia）
├── scripts/
│   └── chunk_model.py    PBI JSON 解析核心（後端 import + CLI 兩用）
├── docs/
│   └── skill-integration.md  Skill 串接指南
├── Dockerfile
├── docker-compose.yml
├── package.json          concurrently dev script（npm run dev）
├── requirements.txt
└── .env.example
```

> 開發者請參閱 [CLAUDE.md](CLAUDE.md) 取得認證設計、關鍵安全細節與啟動流程。
