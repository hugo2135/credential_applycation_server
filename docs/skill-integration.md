# Skill 整合指南

本文件說明如何讓你的 nl-to-dax Skill 與 PBI Credential Server 串接。

有兩種整合方式：

| 方式 | 適用情境 | 狀態 |
|------|----------|------|
| **MCP（本文件主要內容）** | Claude Apps／Claude Code／其他支援 MCP 的 client | ✅ 推薦，新開發請用這個 |
| REST API + PBI_MASK_KEY | 舊版 skill 尚未遷移完成前的過渡 | ⚠️ Legacy，見文末，不建議新串接 |

**為什麼要換成 MCP**：Claude Apps 的 skill 執行環境是「一個對話一個 sandbox」，本機寫入的 `PBI_MASK_KEY` 設定檔每次對話結束就消失，使用者得每次重新申請、貼上金鑰。MCP connector 的 OAuth token 由 Anthropic 的 connector 機制在**帳號層級**保管，跟對話 sandbox 無關，連過一次之後每次對話都能直接用。Claude Code 因為不是 sandbox 環境，理論上兩種方式都能跑，但我們決定新舊 skill 一律統一改用 MCP，不維護兩條並行路徑。

---

## 前置條件

跟 legacy 流程一樣，MCP 這層**不會繞過帳號審核**，使用者必須先完成：

1. 使用者自行到申請程式網站 `/register` 完成註冊
2. 管理員在 `/admin/users` 開通帳號
3. 管理員設定該使用者的 Azure AD 憑證（Tenant ID / Client ID / Client Secret）
4. 管理員在 `/admin/users` 指派一或多個語意模型（PBI 設定）給該使用者

完成以上步驟後，使用者才能在 MCP 的 OAuth 登入畫面成功登入。**不需要再手動申請/複製/貼上 PBI_MASK_KEY**——這步驟被 OAuth 連線取代了。

---

## 使用者怎麼連線

1. 使用者在 Claude（claude.ai 或 Claude Code）的 Settings → Connectors 加入這個 MCP server 的網址：`https://<SITE_DOMAIN>/mcp`
2. Claude 會自動打 `/oauth/register` 註冊自己成為 OAuth client，然後導向 `/oauth/authorize`
3. 使用者在該頁面用**申請程式的帳密**（跟登入 `/dashboard` 一樣）登入，並同意授權
4. Claude 保存 access token（1 小時效期）與 refresh token（90 天效期，每次刷新會輪換），之後每次對話自動使用，使用者不需要再做任何事

---

## MCP Tools

Server 端固定回傳 JSON（透過 MCP 的 content/structuredContent 傳遞），以下是三個 tool 的完整 input/output 定義：

### `list_models`

列出目前使用者被授權存取的所有 PBI 語意模型，**輕量版**（不含完整 relationships/tables，先讓使用者/Claude 挑要查哪個模型）。

**輸入**：無參數。

**輸出**：`list[dict]`，每筆：
```json
{
  "pbi_config_id": "550e8400-e29b-41d4-a716-446655440000",
  "pbi_config_name": "財務模型 A",
  "model_version": 5,
  "model_description": "以 Markdown 撰寫的模型概覽說明，管理員填的，可能是 null",
  "table_count": 12
}
```

### `get_model_detail`

取得指定 PBI 設定的完整語意模型結構，DAX 生成前查表格/欄位/量值用。

**輸入**：`pbi_config_id: str`

**輸出**：`dict`
```json
{
  "pbi_config_id": "550e8400-e29b-41d4-a716-446655440000",
  "pbi_config_name": "財務模型 A",
  "model_version": 5,
  "relationships": {
    "relationships": [
      {
        "fromTable": "Sales", "fromColumn": "ProductKey",
        "toTable": "Product", "toColumn": "ProductKey",
        "cardinality": "ManyToOne", "crossFilterDirection": "Single", "isActive": true
      }
    ]
  },
  "tables": [
    {
      "table": "Sales",
      "description": "",
      "columns": [{ "column": "SalesAmount", "dataType": "decimal", "description": "" }],
      "measures": [{ "measure": "Total Sales", "expression": "SUM(Sales[SalesAmount])", "description": "" }]
    }
  ]
}
```
使用者沒有這個 `pbi_config_id` 的存取權時回 tool error（不會洩漏該設定是否存在）。

### `run_dax_query`

對指定 PBI 設定執行 DAX 查詢。**Server 端會直接完成「向 Azure AD 換 token → 呼叫 Power BI executeQueries」整個流程，Skill 端從頭到尾不會拿到、也不需要處理任何 Azure AD access token。**

**輸入**：`pbi_config_id: str`, `dax: str`（完整 `EVALUATE` 查詢語法，跟 legacy 流程一樣的 DAX 撰寫規則）

**輸出**：`list[dict]`，Power BI `executeQueries` 回傳的查詢結果列（`results[0].tables[0].rows`）。

**失敗情況**（皆為 tool error，訊息會說明原因）：
- 使用者沒有該 `pbi_config_id` 的存取權
- 使用者的 Azure AD 憑證尚未由管理員設定（`tenant_id`/`client_id`/`client_secret` 任一缺失）
- PBI 工作區（workspace_id/dataset_id）尚未設定完成
- Azure AD 驗證失敗、或 Power BI 查詢本身出錯（DAX 語法錯誤等）

---

## 典型呼叫流程

```
使用者觸發 Skill
       │
       ▼
呼叫 list_models          ← 取回可用模型清單（id、名稱、說明、表數量）
       │
       ├─ 只有一個模型 → 自動選定；多個 → 請使用者選
       ▼
呼叫 get_model_detail(pbi_config_id)   ← 取得完整 relationships + tables
       │
       ▼
Skill 依現有推理邏輯（辨識資料表 → 驗證關聯 → 抽欄位/量值 → 生成 DAX）產出 DAX 查詢
       │
       ▼
呼叫 run_dax_query(pbi_config_id, dax)   ← Server 端完成 Azure AD 換 token + 呼叫 Power BI
       │
       ▼
拿到結構化查詢結果列，直接呈現給使用者
```

跟 legacy 流程相比，**Skill 完全不需要碰觸任何憑證**（PBI_MASK_KEY、Azure AD access token 都不會出現在 Skill 這端），也不需要寫任何本機檔案（`pbi_query/dax_query.txt`、`query_result.csv` 這類本機快取檔可以整個拿掉，除非你想保留「結果落地到使用者專案資料夾」這個體驗，那就是 Skill 自己用 Write 工具把 `run_dax_query` 回傳的內容寫成檔案）。

---

## OAuth 技術細節（給要處理連線失敗、想深入了解協定的人看）

- Authorization Server metadata：`GET /.well-known/oauth-authorization-server`（RFC 8414）
- Protected Resource metadata：`GET /.well-known/oauth-protected-resource`（RFC 9728）
- Dynamic Client Registration：`POST /oauth/register`（RFC 7591，public client，不需 secret）
- Authorization endpoint：`GET/POST /oauth/authorize`（PKCE S256 必要）
- Token endpoint：`POST /oauth/token`（`authorization_code` 或 `refresh_token` grant）

MCP 端點本身（`GET/POST/DELETE /mcp`）需要 `Authorization: Bearer <access_token>`，沒帶或過期會收到 `401` + `WWW-Authenticate` header 指向上面的 protected-resource metadata，讓 client 自動重新走一次 OAuth。

---

# Legacy：REST API + PBI_MASK_KEY

> ⚠️ 以下端點仍在運作，但屬於舊版流程，**不建議新的 skill 整合再使用**。既有還沒遷移到 MCP 的 skill 版本可以繼續參考。

## 身份識別

所有 API 呼叫都需在 HTTP Header 帶上 PBI_MASK_KEY：

```
Authorization: Bearer <PBI_MASK_KEY>
```

沒有此 Header 或 Key 無效時，Server 回傳 `401 Unauthorized`。

## API 端點

### GET /api/models

**取回所有可存取的語意模型**

**Request**
```
GET /api/models
Authorization: Bearer <PBI_MASK_KEY>
```

**Response 200**
```json
{
  "models": [
    {
      "pbi_config_id": "550e8400-e29b-41d4-a716-446655440000",
      "pbi_config_name": "財務模型 A",
      "model_version": 5,
      "relationships": {
        "relationships": [
          {
            "fromTable": "Sales",
            "fromColumn": "ProductKey",
            "toTable": "Product",
            "toColumn": "ProductKey",
            "cardinality": "ManyToOne",
            "crossFilterDirection": "Single",
            "isActive": true
          }
        ]
      },
      "tables": [
        {
          "table": "Sales",
          "description": "",
          "columns": [
            { "column": "SalesAmount", "dataType": "decimal", "description": "" }
          ],
          "measures": [
            { "measure": "Total Sales", "expression": "SUM(Sales[SalesAmount])", "description": "" }
          ]
        }
      ]
    }
  ]
}
```

**建議做法**：比對 `model_version`，若版本號與本地快取不同則更新，相同則沿用快取。

### GET /api/token?pbi_config_id=\<id\>

**取得指定 dataset 的 Power BI Access Token**

**Request**
```
GET /api/token?pbi_config_id=550e8400-e29b-41d4-a716-446655440000
Authorization: Bearer <PBI_MASK_KEY>
```

**Response 200**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...",
  "token_type": "Bearer",
  "expires_in": 3599,
  "workspace_id": "e6833b06-998f-45c2-a6c7-43a402d6e12e",
  "dataset_id": "2097b78b-b3df-40f9-9478-680e324acd50",
  "model_version": 5
}
```

用 `access_token` 直接對 Power BI Execute Queries API 發出 DAX 查詢：

```
POST https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/executeQueries
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "queries": [{ "query": "EVALUATE ..." }],
  "serializerSettings": { "includeNulls": true }
}
```

**`pbi_config_id` 從哪來**：從 `/api/models` 回傳的每筆模型中的 `pbi_config_id` 欄位取得。

## 錯誤碼

| 狀態碼 | 說明 |
|--------|------|
| `401` | PBI_MASK_KEY 無效或未提供 |
| `403` | 帳號已停用、憑證已過期，或無該 PBI 設定的存取權 |
| `404` | 該 PBI 設定尚未上傳語意模型 |
| `502` | Azure AD 驗證失敗，請聯絡管理員確認憑證設定 |
| `503` | Azure AD 憑證或 PBI 工作區尚未由管理員設定完成 |
