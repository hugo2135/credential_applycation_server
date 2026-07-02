# PBI Credential 申請程式

管理使用者身份、發放 Power BI 存取憑證，並集中管理語意模型分發的 FastAPI 服務，附帶 Vue 3 管理後台。

## 架構概覽

```
申請程式
├── 後端 (FastAPI)
│   ├── /auth          使用者註冊、登入、領取 PBI_MASK_KEY
│   ├── /api           Skill 呼叫的核心 API（憑證 & 語意模型）
│   └── /admin         管理員 API（登入、使用者開通、PBI 設定、模型上傳）
└── 前端 (Vue 3)
    └── admin-frontend/ 管理後台 SPA
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
| `SERVER_JWT_SECRET` | 用於簽發 JWT 及加密 PBI client_secret 的主要金鑰（建議 64 字元隨機 hex） |
| `ADMIN_SECRET` | 管理後台登入密碼 |
| `DATABASE_URL` | 資料庫連線字串（預設 `sqlite:///./credential.db`） |

產生安全的隨機金鑰：
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

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

### 使用者 API

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/auth/register` | 註冊新帳號 |
| POST | `/auth/login` | 登入，回傳帳號狀態 |
| POST | `/auth/mask-key` | 領取 PBI_MASK_KEY（僅顯示一次） |

### 管理員 API

| 方法 | 路徑 | 驗證 | 說明 |
|------|------|------|------|
| POST | `/admin/login` | 無 | 輸入 ADMIN_SECRET，回傳 1 小時有效的 JWT |
| GET | `/admin/users` | Bearer JWT | 列出所有使用者 |
| PATCH | `/admin/users/activate` | Bearer JWT | 開通或停用使用者、指派 PBI 設定 |
| GET | `/admin/pbi-configs` | Bearer JWT | 列出所有 PBI 設定 |
| POST | `/admin/pbi-configs` | Bearer JWT | 建立 PBI 設定 |
| PATCH | `/admin/pbi-configs/{id}` | Bearer JWT | 更新 PBI 設定 |
| POST | `/admin/model/upload` | Bearer JWT | 上傳新版語意模型 |
| GET | `/admin/model/versions` | Bearer JWT | 列出所有模型版本 |

## 使用者開通流程

```
1. 使用者 POST /auth/register          → 建立帳號，等待開通
2. 管理員透過後台開通並指派 PBI 設定
3. 使用者 POST /auth/mask-key          → 領取 PBI_MASK_KEY（僅一次）
4. Skill 使用 PBI_MASK_KEY 呼叫 /api/credential 與 /api/model
```

## 資料模型

| 資料表 | 說明 |
|--------|------|
| `users` | 帳號、密碼 hash、mask_key hash、啟用狀態、到期時間 |
| `pbi_config` | Power BI 連線設定（client_secret 以 AES-256-GCM 加密儲存） |
| `model_chunks` | 語意模型版本（relationships + tables JSON） |

## 專案結構

```
├── app/
│   ├── main.py           FastAPI 入口（CORS、SPA 靜態服務）
│   ├── database.py       SQLAlchemy 設定
│   ├── models.py         ORM 資料模型
│   ├── security.py       密碼 hash、JWT 簽發、AES 加解密
│   └── routers/
│       ├── auth.py       /auth 路由（使用者）
│       ├── credential.py /api 路由（Skill）
│       └── admin.py      /admin 路由（管理員）
├── admin-frontend/       Vue 3 SPA（Element Plus + Pinia）
├── scripts/
│   └── chunk_model.py    離線工具：拆分原始 PBI JSON
├── docs/
│   └── plan.md           初期規劃文件（歷史參考）
├── package.json          concurrently dev script
├── requirements.txt
└── .env.example
```

> 開發者請參閱 [CLAUDE.md](CLAUDE.md) 取得認證設計、關鍵安全細節與啟動流程。
