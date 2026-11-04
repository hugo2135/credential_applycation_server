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

### 要使用者手動填「OAuth 用戶端 ID」的 MCP client（例如 Gemini 網頁版）

有些 client 支援 OAuth 登入，但不會自己打 `/oauth/register` 註冊，而是要使用者在設定畫面填「OAuth 用戶端 ID／用戶端密鑰」。這種情況請使用者：

1. 登入申請程式，`/dashboard` → 「前往 MCP 連線設定」進到 `/mcp-tokens`
2. 在 client 的設定畫面複製它的「重新導向 URI」，貼到「取得 OAuth 用戶端 ID」區塊，按下取得
3. 把拿到的 client ID 填進「用戶端 ID」，**「用戶端密鑰」留空**，MCP 伺服器網址填 `https://<SITE_DOMAIN>/mcp`
4. 按繼續後會跳到申請程式的登入頁，之後跟一般 OAuth 流程完全一樣

同一個重新導向 URI 一律拿到同一個 client ID，所以同一種 client 的所有使用者其實共用一個 ID——client ID 只代表「哪個應用程式」，身份仍由每個人自己登入決定。`/oauth/token` 也接受 client 把 client ID 放在 HTTP Basic 標頭（`client_secret_basic`）送來，密鑰會被忽略，安全性靠 PKCE。

### 不支援完整 OAuth 流程的 MCP client（例如 Antigravity）

有些 MCP client 不會自動走上面的 OAuth 註冊/授權流程，而是要求使用者在它自己的 MCP 設定裡手動貼上一組固定的 `Authorization: Bearer <token>`。這種情況請使用者：

1. 登入申請程式的 `/dashboard`，點選「前往 MCP 連線設定」進到 `/mcp-tokens` 頁面
2. 點「新增 Token」產生一組 Personal Access Token（`pat_` 開頭，只顯示一次，請立即複製）
3. 依照該 MCP client 自己的說明，把這組 token 貼到它的 MCP server 設定裡（通常是一個 Authorization / Bearer token 欄位），server 網址一樣填 `https://<SITE_DOMAIN>/mcp`

這組 token 跟 legacy 流程的 `PBI_MASK_KEY` 是不同機制、互不相通：`PBI_MASK_KEY` 是給 REST API（`/api/models`、`/api/token`）用的，這組 token 只認 MCP 端點。Token 沒有到期時間，直到使用者自己或管理員在 `/admin/users` 該使用者的「設定」彈窗裡撤銷為止。此路徑能不能讓特定 client（如 Antigravity）真的連上，仍需在該 client 實際設定完成後測試才能確認——我們這邊只保證 server 端支援用這組 token 通過 MCP 的身份驗證。

---

## MCP Tools

Server 端固定回傳 JSON（透過 MCP 的 content/structuredContent 傳遞），以下是查詢相關三個 tool 的完整 input/output 定義（書籤的三個 tool 見後面「書籤」一節）：

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
  "table_count": 12,
  "query_modes": [
    { "mode_id": "summary", "name": "摘要模式", "description": "只看高階彙總表，可能是 null" }
  ]
}
```
`query_modes` 是管理員在 `/admin/pbi-configs/{id}` 詳情頁設定的「資料曝光範圍模式」，沒設定時是空陣列 `[]`。**如果某個 `pbi_config_id` 底下有多個 `query_modes`，Skill 應該先問使用者要用哪一個**（例如列出 `name`/`description` 讓使用者選），再把選到的 `mode_id` 帶進 `get_model_detail`；只有一個或沒有的話不需要問，直接照原本流程走即可。

### `get_model_detail`

取得指定 PBI 設定的完整語意模型結構，DAX 生成前查表格/欄位/量值用，**也是查詢這個模型所需的 `workspace_id`/`dataset_id`、篩選規則 `filters`、欄位別名 `column_aliases` 的來源**。

**輸入**：`pbi_config_id: str`，`mode_id: str`（選填，來自 `list_models` 的 `query_modes`）

**輸出**：`dict`
```json
{
  "pbi_config_id": "550e8400-e29b-41d4-a716-446655440000",
  "pbi_config_name": "財務模型 A",
  "model_version": 5,
  "workspace_id": "e6833b06-998f-45c2-a6c7-43a402d6e12e",
  "dataset_id": "2097b78b-b3df-40f9-9478-680e324acd50",
  "query_mode_id": "summary",
  "filters": [
    {
      "filterId": "exclude-return-orders",
      "name": "排除退貨單",
      "description": "預設查詢排除退貨訂單",
      "alwaysApply": true,
      "overrideDefaults": false,
      "contextKeywords": [],
      "filters": [
        { "description": "排除退貨單", "expression": "Orders[order_type] <> \"return_order\"", "requiredTable": null }
      ]
    }
  ],
  "column_aliases": [
    {
      "table": "Orders",
      "column": "region",
      "values": [
        { "value": "North", "aliases": ["北區", "北部"] },
        { "value": "South", "aliases": ["南區", "南部"] }
      ]
    }
  ],
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
使用者沒有這個 `pbi_config_id` 的存取權時回 tool error（不會洩漏該設定是否存在）。帶了不存在的 `mode_id` 也是 tool error。`filters`/`query_modes`/`column_aliases` 由管理員在 `/admin/pbi-configs/{id}` 詳情頁集中維護，沒設定時是空陣列 `[]`。

**篩選規則的比對邏輯**（Skill 拿到 `filters` 陣列後，在生成 DAX 前依序執行——這段邏輯不因為有沒有帶 `mode_id` 而改變，模式篩選只是多一筆 `alwaysApply` 的設定檔混進同一個陣列裡）：

1. **收集預設篩選**：把所有 `alwaysApply = true` 的設定檔的 `filters` 合併為「預設篩選集」。
2. **比對情境設定檔**：掃描所有 `alwaysApply = false` 的設定檔，檢查其 `contextKeywords` 是否出現在使用者的需求文字中，符合的收集為「命中設定檔清單」。
3. **決定最終篩選集**：
   - 命中設定檔中若有 `overrideDefaults = true`，該設定檔的 `filters` 完全取代預設篩選集（命中多個時以最後命中者優先）。
   - 否則把命中設定檔的 `filters` 追加到預設篩選集後面。
4. 套用到 DAX 時要確認每條規則的 `requiredTable`（如有）——該資料表不在本次查詢範圍內就跳過這條規則。若最終篩選集為空，正常生成 DAX、不加篩選條件即可，不需要額外詢問使用者。

**`mode_id` 對回應內容的影響**：帶了 `mode_id` 時，`tables` 只會回該模式設定的表名子集（該模式沒設 `tables` 則不限制、回全部）；同時 `filters` 陣列裡會多一筆 `filterId` 是 `mode:<mode_id>` 的 `alwaysApply` 設定檔，內容是該模式自己的篩選規則——**照上面同一套比對邏輯處理即可，不用特別區分**。

**`column_aliases` 的使用方式**：這不受 `mode_id` 影響，固定回傳整個 PBI 設定的欄位別名對照。生成 DAX 前，先掃描使用者的需求文字，如果提到某個 `aliases` 裡的詞（例如「北部」），比對邏輯上就把它當成對應的 `value`（例如 `"North"`）寫進 DAX 篩選條件，而不是直接把使用者的原始用詞當成欄位值——這樣可以避免 DAX 因為值不存在資料裡而查不到結果。沒有比對到任何別名時，正常使用使用者的原始用詞即可。

### `get_query_ticket`

> 🔴 **Breaking change（2026-08）**：這支 tool 取代了原本的 `get_powerbi_token`。舊的 tool 已移除，呼叫它會得到 unknown tool 錯誤。Skill 端必須配合修改，見下方「Skill 端要怎麼改」。

取得執行 DAX 查詢用的**一次性 ticket**。這支 tool **不再直接回傳 access token**。

**為什麼要改**：實測發現舊設計會讓 access token 完整進入對話上下文——tool 回傳值本身就會被記錄，而且 Skill 若把 token 寫成檔案（`Write` 工具），token 又會在工具呼叫裡再出現一次。等於一個有效一小時的 Power BI 憑證留在對話紀錄裡，對話被匯出、共享或存進第三方時就會外流。改成發 ticket 之後，真正的 token 只存在於查詢腳本的行程記憶體，不會進上下文、也不落地。

**輸入**：`pbi_config_id: str`

**輸出**：`dict`
```json
{
  "ticket": "隨機亂數字串（不含任何語意）",
  "redeem_url": "https://<SITE_DOMAIN>/api/ticket/redeem",
  "expires_in": 300
}
```

**ticket 的性質**：
- **單次使用**——兌換過就失效，不能重複用
- **會過期**——效期見回傳的 `expires_in`（預設 300 秒，由 server 端的 `MCP_TICKET_TTL_SECONDS` 決定，不要寫死）
- **不含任何語意**——純隨機字串，「是誰、哪個 `pbi_config_id`」全部存在 server 端，DB 也只存 hash

> ⏱ **請在真正要執行查詢的前一刻才呼叫這支 tool。** 所有澄清、選項確認、DAX 生成都完成之後再拿 ticket——中間若還要跟使用者來回確認，等回來時它可能已經過期。
>
> 要注意的是，**這段延遲不只來自 AI 主動提問**：Claude Code／Claude Desktop 執行 Bash 前常常需要使用者按下權限確認，那段等待完全落在「拿到 ticket」與「腳本兌換」之間，而且不是 Skill 能控制的。所以除了把 `get_query_ticket` 放到最後一刻，**也一定要實作下面的重試**。
>
> **過期就重拿**：腳本兌換時若收到 `401`「ticket 已過期，請重新取得」，直接重新呼叫 `get_query_ticket` 拿一張新的再跑一次即可。這很便宜、沒有副作用，也是使用者中途離開時唯一的救援路徑。

**失敗情況**（皆為 tool error，訊息會說明原因）：
- 使用者沒有該 `pbi_config_id` 的存取權
- 使用者的 Azure AD 憑證尚未由管理員設定（刻意在發 ticket 這一步就擋，而不是等到兌換才失敗）

### `POST /api/ticket/redeem`（一般 HTTP，不是 MCP tool）

由 **Skill 的查詢腳本自己呼叫**，用 ticket 換真正的 access token。

**Request**
```
POST https://<SITE_DOMAIN>/api/ticket/redeem
Content-Type: application/json

{ "ticket": "<剛剛拿到的 ticket>" }
```

**Response 200**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...",
  "token_type": "Bearer",
  "expires_in": 3599
}
```
（不含 `workspace_id`/`dataset_id`，那兩個從 `get_model_detail` 拿，避免重複回傳同一份靜態資料。）

這支端點不需要其他身份驗證——ticket 本身就是憑證。

**失敗回應**

| 狀態 | `detail` | 意義 | 腳本該怎麼做 |
|------|----------|------|--------------|
| `401` | `ticket 無效` / `ticket 已使用過，請重新取得` / `ticket 已過期，請重新取得` | ticket 本身的問題 | 回報給 Claude，請它重新呼叫 `get_query_ticket` 後重跑 |
| `403` | `使用者不存在` / `帳號已停用` / `憑證已過期，請聯絡管理員` | 帳號層級被擋 | 請使用者聯絡管理員，重試沒有意義 |
| `502` | `Azure AD 驗證失敗：<原始訊息>` | 跟 Azure AD 換 token 失敗（多半是 client secret 過期或填錯） | 把原始訊息完整帶出來，管理員需要它才能修 |
| `503` | `PBI 設定不存在，請聯絡管理員` | 設定在發 ticket 之後被刪掉 | 請使用者聯絡管理員 |

> ⚠️ **這支端點回的所有錯誤，body 一定是 `{"detail": "<中文訊息>"}` 這個形狀。**
>
> 如果你收到一個 `403` 但 body **不是**這個形狀（HTML 錯誤頁、`Tunnel connection failed`、空 body、其他 JSON 結構），那它**不是我們發的**——是沙盒的 network egress proxy 或中間的其他網路設備擋下來的，請求根本沒到我們的伺服器。詳見文末「疑難排解」。
>
> 這兩種 403 的處理方式完全相反（一個要找管理員改帳號，一個要改使用者自己的 Claude 網路設定），**所以絕對不能只看狀態碼就決定錯誤訊息**。

### Skill 端要怎麼改

**關鍵原則：ticket 可以進上下文，token 不行。** 所以兌換動作一定要發生在**腳本內部**，不能由 Claude 拿到 token 之後再傳給腳本——那樣 token 就又回到上下文裡了。

```
Claude ──MCP──> get_query_ticket(pbi_config_id)  →  { ticket, redeem_url, expires_in }
Claude ──────>  execute_dax_query.py <ticket> <workspace_id> <dataset_id> <dax檔> <輸出檔>
                        │
                        ├─ ① POST {redeem_url}  {"ticket": ...}   →  access_token（只在記憶體）
                        └─ ② POST api.powerbi.com/.../executeQueries  用 ① 的 token
                        
                        腳本只回傳查詢結果，token 從頭到尾不外流
```

必須做到：

- ❌ **不要**把 token 寫進檔案（`.access_token` 這類做法要移除）——`Write` 工具的內容會完整進上下文，而且檔案會留在使用者的專案資料夾裡，有被 git commit／備份／同步出去的風險
- ❌ **不要**把 token 當成 command-line 參數傳——指令列一樣會進上下文
- ✅ ticket 當 argv 傳沒問題（短效、單次使用，就算外流價值也極低）
- ✅ 同一次腳本執行內要連續查好幾次的話，兌換一次、在記憶體裡重複用即可

**Token 快取指引已反轉**：舊版指引要求「同一個對話內快取 token、不要每次查詢都呼叫 tool」。改用 ticket 之後**相反**——ticket 是單次使用的，**每次要執行查詢前都要重新呼叫 `get_query_ticket` 拿新的**，不需要也不應該快取。

#### 錯誤處理：不要把狀態碼翻譯成猜測

兌換失敗時，**一定要把 HTTP 回應的 body 原樣帶進錯誤訊息**，不要只憑狀態碼自行改寫成人話。

原因見上面那張表的警告：同一個 `403`，可能是「帳號被停用」（要找管理員），也可能是「沙盒 egress proxy 擋下來，請求根本沒送出去」（要改使用者自己的 Claude 網路設定）。只看狀態碼的話，這兩種情況會被說成同一句話，而那句話對其中一種是完全錯誤的指引——實務上這會讓人往錯的方向查很久。

```python
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='replace')
    if e.code == 401:
        raise TicketExpired(f"ticket 無效、已使用或已過期，需重新取得：{body}")
    # 401 以外一律帶上狀態碼與 body，由讀訊息的人（或 Claude）判斷是哪一種
    raise RuntimeError(f"ticket 兌換失敗 (HTTP {e.code})：{body}")
```

同樣的原則適用於 `executeQueries` 的失敗——Power BI 的錯誤 body 裡有 `error.code`（例如 `PowerBINotAuthorizedException`），那是判斷「服務主體沒被加進 workspace」的唯一線索，吞掉就查不出來了。

**拿到 `access_token` 之後，腳本自己直接打**：
```
POST https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/executeQueries
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "queries": [{ "query": "<DAX>" }],
  "serializerSettings": { "includeNulls": true }
}
```

> ⚠️ **這支 tool 不執行查詢**。查詢是 Skill 自己直接對 Power BI 的 `executeQueries` REST API 發請求——這是刻意的設計，不是漏做：如果讓 server 代為執行查詢並等待/轉發結果，並發多個查詢時會讓 server 端的同步網路呼叫互相卡住（甚至拖垮整個服務的回應能力，包含跟這次查詢完全無關的其他使用者）。
>
> **前提：使用者的 Claude 執行環境要放行兩個網域**。Claude Apps 的 code execution 沙盒（以及 Claude Desktop 的 local agent mode）預設會擋未知網域的對外連線，需要使用者自行到 Claude Settings → Capabilities → Network egress 加入白名單：
> - `api.powerbi.com`（執行 DAX 查詢）
> - `<SITE_DOMAIN>`（兌換 ticket）← **改用 ticket 後新增的需求**
>
> 漏掉的症狀是類似 `Tunnel connection failed: 403 Forbidden` 的錯誤，而且 MCP tool 本身仍會成功（那是走 MCP 連線，不受沙盒網路限制影響），很容易誤判成憑證問題。這兩項請寫進 Skill 的安裝教學。
>
> **注意 `<SITE_DOMAIN>` 這一項即使寫進安裝教學也常常出事**，因為它的失敗長得跟帳號問題一模一樣。請一併參考文末的「疑難排解：ticket 拿得到、但兌換失敗」，那裡有分辨兩者的方法。

---

## 書籤（v1.1 新增）

使用者常用的查詢可以存在 server 的帳號裡，換電腦、換 client、開新對話都還在。使用者也能在申請程式的 `/bookmarks` 頁面查看、刪除、匯出分享給同事。舊版 skill 不接這三個 tool 也完全不受影響。

**執行書籤時沒有任何新的取得 token 路徑**：書籤只是存起來的 DAX 字串，執行流程跟一般查詢一樣——`get_query_ticket` 拿 ticket，再把書籤的 `dax` 交給查詢腳本。

### `list_bookmarks`

**Input**：`pbi_config_id`（選填，只看某個模型的書籤）

**Output**（陣列，依更新時間新到舊）
```json
[
  {
    "id": "b1c2...",
    "pbi_config_id": "d6a5ec24-...",
    "pbi_config_name": "業務銷售總表",
    "title": "上月各區銷售額",
    "dax": "EVALUATE SUMMARIZECOLUMNS(...)",
    "question": "上個月各區的銷售額是多少",
    "model_version": 3,
    "current_model_version": 4,
    "possibly_outdated": true,
    "created_at": "2026-10-28T03:00:00",
    "updated_at": "2026-10-28T03:00:00"
  }
]
```

- 只會列出**目前仍被指派**的模型的書籤。管理員取消指派後書籤會隱藏，重新指派就回來
- **`possibly_outdated: true`** 代表存檔之後語意模型升過版，DAX 引用的表/欄位可能已改名或刪除。**請不要直接執行**：先告知使用者，建議用 `question` 搭配 `get_model_detail` 重新生成 DAX

### `save_bookmark`

**Input**

| 參數 | 必填 | 說明 |
|------|------|------|
| `pbi_config_id` | ✅ | 這個 DAX 是針對哪個模型寫的 |
| `title` | ✅ | 給使用者辨識用的名稱，最多 100 字。**同一模型下不可重複** |
| `dax` | ✅ | 完整的 DAX 查詢，最多 20000 字 |
| `question` | 建議帶 | 使用者原本的自然語言問題，最多 2000 字。模型改版後可據此重新生成 |
| `overwrite` | | 預設 `false`，見下方 |

**同名時的處理（必須照做）**

第一次一律用 `overwrite=false` 呼叫。若同名書籤已存在，server **不會覆蓋**，而是回傳：

```json
{
  "saved": false,
  "conflict": true,
  "message": "已有同名書籤，請先詢問使用者是否覆蓋；同意後帶 overwrite=true 再呼叫一次",
  "existing": { "...既有書籤的完整內容，格式同 list_bookmarks 的一筆..." }
}
```

這時 skill **必須先把既有書籤的內容告訴使用者，詢問是否覆蓋**：
- 使用者同意 → 帶 `overwrite=true` 再呼叫一次
- 使用者不同意 → 請他換一個標題

**不可以未經使用者同意就自行帶 `overwrite=true`。**

成功時回傳 `{"saved": true, "conflict": false, "status": "created" 或 "overwritten", "bookmark": {...}}`。

**限制**：每位使用者最多 100 筆書籤（覆蓋既有的不算新增）。超過時會回 tool error，請使用者到 `/bookmarks` 刪除不需要的。

### `delete_bookmark`

**Input**：`bookmark_id`（從 `list_bookmarks` 取得）。刪除前請先跟使用者確認。

成功回傳 `{"deleted": true}`，找不到時回 tool error。

### 匯出檔格式（給使用者分享用，skill 端不需要處理）

使用者在 `/bookmarks` 匯出的檔案長這樣，同事匯入時以 `pbi_config_id` 為準，沒有該模型存取權的會被略過並告知原因：

```json
{
  "format": "nl-to-dax-bookmarks",
  "version": 1,
  "exported_at": "2026-10-28T03:00:00Z",
  "bookmarks": [
    { "pbi_config_id": "...", "pbi_config_name": "...", "title": "...", "dax": "...", "question": "...", "model_version": 3 }
  ]
}
```

---

## 典型呼叫流程

```
使用者觸發 Skill
       │
       ▼
呼叫 list_models          ← 取回可用模型清單（id、名稱、說明、表數量、query_modes）
       │
       ├─ 只有一個模型 → 自動選定；多個 → 請使用者選
       ├─ 選定的模型底下只有一個/沒有 query_mode → 不用問；多個 → 請使用者選一個 mode_id
       ▼
呼叫 get_model_detail(pbi_config_id, mode_id?)   ← 取得完整 relationships + tables + workspace_id/dataset_id + filters + column_aliases
       │
       ▼
依 filters 比對邏輯決定最終篩選集（見上方「篩選規則的比對邏輯」），並依 column_aliases 把使用者用詞轉換成實際欄位值
       │
       ▼
Skill 依現有推理邏輯（辨識資料表 → 驗證關聯 → 抽欄位/量值 → 套用篩選集 → 生成 DAX）產出 DAX 查詢
       │
       ▼
呼叫 get_query_ticket(pbi_config_id) 拿一張 ticket（每次查詢都要重拿，不要快取）
       │
       ▼
把 ticket 交給查詢腳本，腳本內部：
       ├─ ① POST {redeem_url} 用 ticket 換 access_token（只存在記憶體）
       └─ ② 直接對 Power BI executeQueries API 發送 DAX 查詢（不經過我們的 server）
       │
       ▼
Power BI 直接把查詢結果回給腳本，腳本只輸出結果（token 不外流），呈現給使用者
```

跟 legacy 流程相比，**Skill 完全不需要碰觸 PBI_MASK_KEY**（那個概念在 MCP 流程裡整個消失），也不需要寫任何本機檔案（`pbi_query/dax_query.txt`、`query_result.csv` 這類本機快取檔可以整個拿掉，除非你想保留「結果落地到使用者專案資料夾」這個體驗，那就是 Skill 自己用 Write 工具把查詢結果寫成檔案）。**唯一絕對不能落地的是 access token**——見上方「Skill 端要怎麼改」。

兩邊相同的是：**Azure AD access token 最終都是由 Skill 自己拿去直接呼叫 Power BI**，我們的 server 從不代理查詢。差別只在「怎麼拿到這個 token」——legacy 是 PBI_MASK_KEY 換，MCP 版是 OAuth 連線 + 一次性 ticket 兌換。

---

## 疑難排解：ticket 拿得到、但兌換失敗

這是改用 ticket 之後最常見、也最容易誤判的故障，**務必先讀這一段再往下查**。

### 為什麼「MCP tool 成功」不代表「腳本連得到伺服器」

兩個動作走的是**完全不同的網路路徑**：

| 動作 | 從哪裡發出 | 受什麼限制 |
|------|-----------|-----------|
| `get_query_ticket`（MCP tool） | Anthropic 的伺服器 → 我們的 `/mcp` | 不受使用者本機／沙盒的網路設定影響 |
| `POST /api/ticket/redeem`（查詢腳本） | **Claude 的執行沙盒內** | 受 Network egress 白名單管制 |

所以「ticket 拿得到，兌換卻失敗」**完全不代表憑證或帳號有問題**——最常見的原因是沙盒沒放行 `<SITE_DOMAIN>`，請求連我們的伺服器都沒碰到。

### 症狀對照

| 腳本收到什麼 | 幾乎可以確定是 |
|---|---|
| `403`，body 是 `{"detail": "帳號已停用"}` 之類 | 真的是帳號問題，找管理員 |
| `403`，body 是 HTML／`Tunnel connection failed`／空的 | **沙盒 egress 沒放行**，請求沒送出去 |
| 連線錯誤、DNS 失敗、逾時 | 網路不通或網域解析不到 |
| `401` + `{"detail": "ticket 已過期，請重新取得"}` | 中間隔了太久（多半是使用者在工具權限確認畫面停留），重拿一張即可 |

### 一行指令確認沙盒到底連不連得到

**在跑 skill 的那個 Claude 對話裡**，用它自己的 Bash 工具跑（用假 ticket，不涉及任何憑證，安全）：

```bash
curl -sS -X POST https://<SITE_DOMAIN>/api/ticket/redeem \
  -H 'Content-Type: application/json' -d '{"ticket":"bogus"}'
```

- 印出 `{"detail":"ticket 無效"}` → **沙盒連得到伺服器**，問題在別處，往帳號／憑證方向查
- 印出別的東西（403 錯誤頁、連線失敗） → egress 沒放行，去 Claude Settings → Capabilities → Network egress 加入 `<SITE_DOMAIN>`

> 改完 egress 設定通常要**開一個新對話**才會套用到新的沙盒。在同一個對話裡改完就重試，很可能還是舊政策。

### 管理員這邊怎麼確認

在伺服器上看所有兌換嘗試：

```bash
docker compose logs app -t | grep "ticket/redeem"
```

`-t` 印的是 **UTC**，台灣時間要自己加 8 小時（`/admin/access-logs` 頁面則已經轉成本地時間，不用再加）。

判讀的關鍵是**有沒有那筆請求**：

- **完全沒有對應的 POST 紀錄** → 請求從未抵達，是使用者端的網路／egress 問題，伺服器沒有拒絕任何人
- **有 POST 且狀態是 403/502** → 才是伺服器這邊擋的，照上面那張錯誤表處理

注意來源 IP 一律顯示成 Caddy 的容器位址，**看不出請求從哪裡來**，所以不能靠 IP 判斷是誰打的。

另外 `/admin/access-logs` 可以查到 `path = /mcp/get_query_ticket` 的紀錄，確認是**哪個帳號**領走了那張 ticket——當使用者有多個 MCP client、或懷疑連線綁到了別的帳號時，這是唯一的判斷依據。兌換紀錄（`path = /api/ticket/redeem`，存取方式選「Ticket 兌換」）成功失敗都會留，失敗時「結果」欄會寫原因（ticket 已用過／過期、帳號停用、Azure AD 錯誤等）。唯一不留紀錄的是查無此 ticket（例如 ticket 字串被截斷），因為無法得知是誰。所以：有 `get_query_ticket` 卻**完全沒有**對應的兌換紀錄，就代表請求沒送到 server，問題在使用者端的權限或網路。

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
