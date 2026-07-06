# Skill 整合指南

本文件說明如何讓你的 nl-to-dax Skill 與 PBI Credential Server 串接。

---

## 前置條件

向管理員申請帳號並完成以下步驟後，才能開始整合：

1. 管理員開通你的帳號
2. 管理員為你設定 Azure AD 憑證（Tenant ID / Client ID / Client Secret）
3. 管理員為你分配一或多個語意模型（PBI 設定）
4. 你在使用者 Dashboard 自行領取 **PBI_MASK_KEY**（只顯示一次，請妥善保存）

---

## 身份識別

所有 API 呼叫都需在 HTTP Header 帶上 PBI_MASK_KEY：

```
Authorization: Bearer <PBI_MASK_KEY>
```

沒有此 Header 或 Key 無效時，Server 回傳 `401 Unauthorized`。

---

## API 端點

Base URL 由部署方提供。以下路徑皆需附上 Authorization Header。

---

### GET /api/models

**取回所有可存取的語意模型**

使用者觸發 Skill 時呼叫此端點。Server 根據 PBI_MASK_KEY 自動判斷該使用者有哪些模型存取權，一次回傳所有最新版本，無需帶任何參數。

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

---

### GET /api/token?pbi_config_id=\<id\>

**取得指定 dataset 的 Power BI Access Token**

當 Skill 確定要查詢哪個 dataset 後呼叫此端點。Server 以使用者的 Azure AD 憑證向 Microsoft 換取 access token，**Azure AD 憑證不會出現在回應中**。

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

---

## 典型呼叫流程

```
使用者觸發 Skill
       │
       ▼
GET /api/models          ← 取回所有可用模型（含 pbi_config_id、model_version、tables、relationships）
       │
       ├─ 比對 model_version → 更新本地快取（如有新版本）
       │
       ▼
Skill 分析使用者問題，決定要查哪個 dataset（pbi_config_id）
       │
       ▼
GET /api/token?pbi_config_id=<id>   ← Server 向 Azure AD 換取 access token
       │                               Azure AD 憑證不離開 Server
       ▼
用 access_token + workspace_id + dataset_id 直接對 Power BI 執行 DAX 查詢
       │
       ▼
Power BI 回傳查詢結果
```

---

## 錯誤碼

| 狀態碼 | 說明 |
|--------|------|
| `401` | PBI_MASK_KEY 無效或未提供 |
| `403` | 帳號已停用、憑證已過期，或無該 PBI 設定的存取權 |
| `404` | 該 PBI 設定尚未上傳語意模型 |
| `502` | Azure AD 驗證失敗，請聯絡管理員確認憑證設定 |
| `503` | Azure AD 憑證或 PBI 工作區尚未由管理員設定完成 |
