# 申請程式開發計畫

> 此文件為申請程式的獨立專案規劃。申請程式負責管理使用者身份、發放 Power BI 存取憑證，並集中管理語意模型分發。

---

## 專案定位

| 項目 | 說明 |
|------|------|
| 使用者 | 持有 nl-to-dax Skill 的內部人員 |
| 管理員 | 負責開通資格、維護語意模型與 PBI 連線設定 |
| 與 Skill 的關係 | 提供兩支 API，Skill 透過 `PBI_MASK_KEY` 自動拉取憑證與模型 |

---

## 與 nl-to-dax Skill 的 API 合約

> 此合約由兩側共同遵守，變更需同步通知。

### `GET /api/credential`
```
Authorization: Bearer <PBI_MASK_KEY>

回傳：
{
  "jwt": "<HS256 signed JWT>"
}

JWT Payload：
{
  "tenant_id":    "...",
  "client_id":    "...",
  "client_secret":"...",
  "workspace_id": "...",
  "dataset_id":   "...",
  "model_version": 3,
  "iss": "pbi-skill-provider",
  "iat": <unix timestamp>,
  "exp": <unix timestamp>
}
```

### `GET /api/model`
```
Authorization: Bearer <PBI_MASK_KEY>

回傳：
{
  "model_version": 3,
  "relationships": { ...relationships.json 內容... },
  "tables": [
    { ...table_TableName.json 內容... },
    ...
  ]
}
```

---

## 系統架構

```
申請程式
├── 前端（Web UI）
│   ├── 使用者頁面
│   │   ├── 註冊 / 登入
│   │   ├── 領取 PBI_MASK_KEY（僅顯示一次，需自行保存）
│   │   └── 查看 credential 狀態與過期時間
│   └── 管理員頁面
│       ├── 使用者清單（開通 / 撤銷資格）
│       ├── PBI 連線設定（tenant_id、client_id、workspace_id、dataset_id）
│       └── 語意模型管理（上傳 JSON → 自動拆分 → 遞增 model_version）
│
├── 後端 API
│   ├── GET  /api/credential     （Skill 呼叫）
│   ├── GET  /api/model          （Skill 呼叫）
│   ├── POST /auth/register      （使用者註冊）
│   ├── POST /auth/login         （使用者登入）
│   └── POST /admin/model/upload （管理員上傳語意模型）
│
└── 資料庫
    ├── users        （使用者帳號與 PBI_MASK_KEY）
    ├── pbi_config   （PBI 連線設定，全局唯一或按群組）
    └── model_chunks （拆分後的語意模型，含 model_version）
```

---

## 資料模型

### users
| 欄位 | 型別 | 說明 |
|------|------|------|
| id | UUID | 主鍵 |
| email | string | 使用者帳號 |
| password_hash | string | bcrypt hash |
| mask_key_hash | string | PBI_MASK_KEY 的 hash（用於驗證 API 請求） |
| is_active | bool | 是否有資格取得 credential |
| created_at | timestamp | |
| expires_at | timestamp | credential 過期時間（影響 JWT exp） |

### pbi_config
| 欄位 | 型別 | 說明 |
|------|------|------|
| id | UUID | 主鍵 |
| tenant_id | string | Azure AD 租用戶 |
| client_id | string | 服務主體 App ID |
| client_secret | string | 加密儲存 |
| workspace_id | string | Power BI 工作區 |
| dataset_id | string | 語意模型（資料集）|

### model_chunks
| 欄位 | 型別 | 說明 |
|------|------|------|
| id | UUID | 主鍵 |
| model_version | int | 每次上傳遞增 |
| relationships | JSON | relationships.json 內容 |
| tables | JSON | 所有 table_*.json 的陣列 |
| uploaded_at | timestamp | |

---

## 核心邏輯

### PBI_MASK_KEY 產生與儲存
- 使用者完成註冊並由管理員開通後，系統產生 `secrets.token_hex(32)`
- 明文只在產生當下回傳給使用者一次，之後僅儲存 hash
- 驗證 API 請求時：對請求 header 的 Bearer token 做 hash，比對資料庫

### JWT 簽發（`GET /api/credential`）
1. 驗證 PBI_MASK_KEY hash → 確認使用者 `is_active`
2. 從 `pbi_config` 取出連線設定
3. 從 `model_chunks` 取出最新 `model_version`
4. 以使用者的 PBI_MASK_KEY 明文（不儲存，需使用者提供？）簽發 HS256 JWT

> ⚠️ 待決策：JWT 用統一的 server secret 簽發，還是用各使用者的 PBI_MASK_KEY 簽發？
> - 統一 server secret：後端可驗證所有 JWT，但 Skill 需另外拿到驗證金鑰
> - 各用戶 PBI_MASK_KEY：與現有 Skill 設計相容，但後端驗簽需重新 hash 比對

### 語意模型上傳（`POST /admin/model/upload`）
1. 接收原始語意模型 JSON
2. 執行 `chunk_model.py` 邏輯（移植自 nl-to-dax Skill）
3. 將拆分結果存入 `model_chunks`，`model_version` + 1
4. 舊版本保留或清除（待決定）

---

## 技術選型考量

| 面向 | 選項 | 備註 |
|------|------|------|
| 後端框架 | Python FastAPI / Node.js Express | FastAPI 與現有 Python 腳本語言一致 |
| 資料庫 | PostgreSQL / SQLite | 初期 SQLite 夠用，之後遷移 PostgreSQL |
| 認證 | 自建帳密 + session / JWT | 簡單場景用 session 即可 |
| 部署 | Docker + 單機 / Cloud Run | 依使用規模決定 |

---

## 開發計畫

> 完成的項目直接刪除。

### 優先（API 合約先上，讓 Skill 開發可以對接 mock）
- [ ] 建立專案骨架與資料庫 schema
- [ ] 實作 `GET /api/credential`（含 PBI_MASK_KEY 驗證與 JWT 簽發）
- [ ] 實作 `GET /api/model`（回傳最新版 chunks）
- [ ] 提供 mock server 給 nl-to-dax Skill 開發期使用

### 次優先（使用者與管理功能）
- [ ] 使用者註冊 / 登入 / PBI_MASK_KEY 領取頁面
- [ ] 管理員開通 / 撤銷使用者介面
- [ ] PBI 連線設定管理介面
- [ ] 語意模型上傳介面（整合 chunk_model 邏輯）

### 待決策
- [ ] JWT 簽發策略：統一 server secret vs. 各用戶 PBI_MASK_KEY
- [ ] 舊版 model_chunks 是否保留（rollback 需求）
- [ ] credential 過期時間策略（固定天數 vs. 管理員手動設定）
