# PBI Credential 申請程式

管理使用者身份、發放 Power BI 存取憑證，並集中管理語意模型分發的 FastAPI 服務，附帶 Vue 3 管理後台與使用者自助頁面。

## 架構概覽

```
FastAPI 後端
  /auth/*   → 使用者自助（註冊、登入、領取 PBI_MASK_KEY）
  /api/*    → Skill 呼叫（憑證 JWT & 語意模型）
  /admin/*  → 管理後台 API（CRUD、模型上傳）

Vue 3 SPA（同一 origin）
  /login, /register, /dashboard  → 使用者頁面
  /admin/login, /admin/*         → 管理員後台
```

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

### 正式部署（前端由後端統一服務）

```bash
cd admin-frontend && npm run build && cd ..
uvicorn app.main:app
```

`admin-frontend/dist/` 存在時，後端自動 serve 靜態檔案，開啟 `http://localhost:8000` 即可。

## 環境變數

| 變數 | 說明 |
|------|------|
| `SERVER_JWT_SECRET` | 主要金鑰，64 字元隨機 hex。JWT 簽發 + AES-256-GCM key derivation |
| `ADMIN_SECRET` | 管理後台登入密碼 |
| `DATABASE_URL` | 資料庫連線字串（預設 `sqlite:///./credential.db`） |

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
| `/admin/users` | 管理員 | 使用者管理（開通、指派 PBI 設定） |
| `/admin/pbi-configs` | 管理員 | PBI 連線設定管理 |
| `/admin/model` | 管理員 | 語意模型版本管理（上傳、改名、刪除） |

## API 端點

### Skill API（需 `Authorization: Bearer <PBI_MASK_KEY>`）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/credential` | 回傳含 PBI 連線資訊的 HS256 JWT |
| GET | `/api/model` | 回傳最新版語意模型（relationships + tables） |

`GET /api/credential` 回傳格式：
```json
{
  "jwt": "<HS256 signed JWT>"
}
```

JWT Payload：
```json
{
  "tenant_id": "...",
  "client_id": "...",
  "client_secret": "...",
  "workspace_id": "...",
  "dataset_id": "...",
  "model_version": 3,
  "iss": "pbi-skill-provider",
  "iat": 1700000000,
  "exp": 1702592000
}
```

### 使用者 API（`/auth/*`）

| 方法 | 路徑 | 驗證 | 說明 |
|------|------|------|------|
| POST | `/auth/register` | 無 | 註冊新帳號 |
| POST | `/auth/login` | 無 | 帳密登入，回傳 8 小時 user session JWT |
| GET | `/auth/me` | Bearer user JWT | 查看帳號狀態與 key 領取狀況 |
| POST | `/auth/mask-key` | Bearer user JWT | 領取 PBI_MASK_KEY（僅顯示一次） |

### 管理員 API（`/admin/*`）

| 方法 | 路徑 | 驗證 | 說明 |
|------|------|------|------|
| POST | `/admin/login` | 無 | 輸入 ADMIN_SECRET，回傳 1 小時 admin JWT |
| GET | `/admin/users` | Bearer admin JWT | 列出所有使用者 |
| PATCH | `/admin/users/activate` | Bearer admin JWT | 開通／停用、指派 PBI 設定、設到期日 |
| GET | `/admin/pbi-configs` | Bearer admin JWT | 列出所有 PBI 設定 |
| POST | `/admin/pbi-configs` | Bearer admin JWT | 建立 PBI 設定 |
| PATCH | `/admin/pbi-configs/{id}` | Bearer admin JWT | 更新 PBI 設定 |
| POST | `/admin/model/upload` | Bearer admin JWT | 上傳語意模型（接受原始 PBI JSON） |
| GET | `/admin/model/versions` | Bearer admin JWT | 列出所有版本（含張表數、關聯數） |
| GET | `/admin/model/versions/{v}` | Bearer admin JWT | 取得指定版本的表名清單 |
| PATCH | `/admin/model/versions/{v}` | Bearer admin JWT | 更新版本名稱 |
| DELETE | `/admin/model/versions/{v}` | Bearer admin JWT | 刪除指定版本 |

## 使用者開通流程

```
1. 使用者前往 /register 申請帳號
2. 管理員在 /admin/users 開通帳號並指派 PBI 設定
3. 使用者前往 /dashboard 領取 PBI_MASK_KEY（僅顯示一次）
4. 將 PBI_MASK_KEY 填入 nl-to-dax Skill 環境設定
5. Skill 自動呼叫 /api/credential 與 /api/model 取得憑證與語意模型
```

## 語意模型上傳

管理員在 `/admin/model` 頁面可：
- 上傳原始 Power BI JSON（`clientDataModel` 格式）或簡化語意格式，後端自動解析
- 為版本命名，方便識別
- 展開查看各版本包含的資料表
- 雙擊版本名稱改名
- 刪除不需要的版本

本地測試／驗證解析結果：
```bash
python scripts/chunk_model.py path/to/model.json
# 輸出至 ./output/relationships.json 與 ./output/tables/
```

## 資料模型

| 資料表 | 說明 |
|--------|------|
| `users` | 帳號、密碼 hash、mask_key hash、啟用狀態、PBI 設定指派、到期時間 |
| `pbi_config` | Power BI 連線設定（client_secret 以 AES-256-GCM 加密儲存） |
| `model_chunks` | 語意模型版本（版本號、名稱、relationships JSON、tables JSON） |

## 專案結構

```
├── app/
│   ├── main.py           FastAPI 入口（CORS、SPA 靜態服務、DB migration）
│   ├── database.py       SQLAlchemy 設定
│   ├── models.py         ORM 資料模型
│   ├── security.py       密碼 hash、JWT 簽發、AES 加解密
│   └── routers/
│       ├── auth.py       /auth 路由（使用者）
│       ├── credential.py /api 路由（Skill）
│       └── admin.py      /admin 路由（管理員）
├── admin-frontend/       Vue 3 SPA（Element Plus + Pinia）
├── scripts/
│   └── chunk_model.py    PBI JSON 解析核心（後端 import + CLI 兩用）
├── docs/
│   └── plan.md           初期規劃文件（歷史參考）
├── package.json          concurrently dev script（npm run dev）
├── requirements.txt
└── .env.example
```

> 開發者請參閱 [CLAUDE.md](CLAUDE.md) 取得認證設計、關鍵安全細節與啟動流程。
