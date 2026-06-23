# PBI Credential 申請程式 — 後端 API

管理使用者身份、發放 Power BI 存取憑證，並集中管理語意模型分發的 FastAPI 服務。

## 架構概覽

```
申請程式後端
├── /auth          使用者註冊、登入、領取 PBI_MASK_KEY
├── /api           Skill 呼叫的核心 API（憑證 & 語意模型）
└── /admin         管理員介面（使用者開通、PBI 設定、模型上傳）
```

## 快速啟動

**環境需求：** Python 3.11+

```bash
# 建立虛擬環境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 安裝相依套件
pip install -r requirements.txt

# 複製並填入環境變數
cp .env.example .env
# 編輯 .env，填入 SERVER_JWT_SECRET 與 ADMIN_SECRET

# 啟動開發伺服器
uvicorn app.main:app --reload
```

伺服器預設在 `http://localhost:8000` 啟動，互動式 API 文件位於 `http://localhost:8000/docs`。

## 環境變數

| 變數 | 說明 |
|------|------|
| `SERVER_JWT_SECRET` | 用於簽發 JWT 及加密 PBI client_secret 的主要金鑰（建議 64 字元隨機 hex） |
| `ADMIN_SECRET` | 初始化用的 bootstrap 管理員 token |
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

### 管理員 API（需 `X-Admin-Token: <ADMIN_SECRET>`）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/admin/users` | 列出所有使用者 |
| PATCH | `/admin/users/activate` | 開通或停用使用者、指派 PBI 設定 |
| GET | `/admin/pbi-configs` | 列出所有 PBI 設定 |
| POST | `/admin/pbi-configs` | 建立 PBI 設定 |
| PATCH | `/admin/pbi-configs/{id}` | 更新 PBI 設定 |
| POST | `/admin/model/upload` | 上傳新版語意模型 |
| GET | `/admin/model/versions` | 列出所有模型版本 |

## 使用者開通流程

```
1. 使用者 POST /auth/register       → 建立帳號，等待開通
2. 管理員 PATCH /admin/users/activate → 開通並指派 pbi_config_id
3. 使用者 POST /auth/mask-key        → 領取 PBI_MASK_KEY（僅一次）
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
app/
├── main.py          FastAPI 入口
├── database.py      SQLAlchemy 設定
├── models.py        ORM 資料模型
├── security.py      密碼 hash、JWT 簽發、AES 加解密
└── routers/
    ├── auth.py      /auth 路由
    ├── credential.py /api 路由
    └── admin.py     /admin 路由
```
