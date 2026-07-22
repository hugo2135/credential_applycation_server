# CLAUDE.md — 開發者快速指南

## 專案定位

PBI Credential 申請程式：管理使用者身份、發放 Power BI 存取憑證、集中管理語意模型。
供 nl-to-dax Skill 呼叫，主要透過 **MCP（OAuth 保護）**，legacy 流程用 PBI_MASK_KEY 呼叫 REST API。

## 架構

```
FastAPI 後端                 Vue 3 SPA（同一 origin）
  /auth/*        → 使用者自助（註冊、登入、領取 key，legacy）
  /api/*         → Skill legacy 呼叫（憑證 & 語意模型，逐步淘汰中）
  /api/admin/*   → 管理後台 API（CRUD、模型上傳）
  /oauth/*       → OAuth 2.1 authorization server（DCR/authorize/token，給 MCP 用）
  /.well-known/* → OAuth/MCP metadata（RFC 8414、RFC 9728）
  /mcp           → MCP server（Streamable HTTP，Bearer token 保護）
```

前端頁面路徑 `/admin/*`（`/admin/login`、`/admin/users` 等）與後端管理 API 路徑 `/api/admin/*` **刻意分開**，避免整頁重整 / 直接輸入網址時，瀏覽器的 GET 請求被同名的後端 API route 攔截而拿到 JSON 而非 SPA。

## 認證設計

| 對象 | 方式 |
|------|------|
| 管理員 SPA | POST /api/admin/login（ADMIN_SECRET） → 1 hr HS256 JWT，Bearer |
| 使用者 SPA | POST /auth/login（帳密） → user session JWT，Bearer |
| MCP connector | OAuth 2.1 + PKCE（`/oauth/authorize` 沿用使用者帳密登入）→ 1 hr access JWT + 90 天 refresh token（每次使用輪換，只存 hash） |
| MCP connector（不支援 OAuth，如 Antigravity） | 使用者在 `/mcp-tokens` 自助產生 Personal Access Token（`pat_` 開頭），貼進該 client 設定當固定 Bearer，無到期時間，只能撤銷 |
| Skill API（legacy） | Authorization: Bearer \<PBI_MASK_KEY\>（SHA-256 hash 存 DB） |

## 關鍵安全細節

- `SERVER_JWT_SECRET`：**動態讀取**（`_get_secret()`），禁止 module-level 常數，避免 .env 載入時序問題。也是 MCP access token 的簽章金鑰。
- `datetime.now(timezone.utc)`：JWT 時間戳**必須**用這個，`utcnow()` 在 UTC+8 環境會讓 exp 提前 7 小時失效。
- `client_secret` 以 AES-256-GCM 加密存 DB，key 衍生自 `SERVER_JWT_SECRET`。
- PBI_MASK_KEY 明文只在產生時回傳一次，DB 只存 SHA-256 hash；OAuth refresh token、MCP Personal Access Token（`personal_access_tokens` 表）比照辦理，只存 hash。`mcp.py` 的 `_JwtTokenVerifier` 驗證時先試 OAuth JWT，失敗再退回查 PAT hash——兩種 token 都能通過 `/mcp` 的身份驗證。
- MCP tool（`get_powerbi_token`）只負責在 server 端跟 Azure AD 換 token，**查詢本身由呼叫端拿 token 直接打 Power BI executeQueries**，server 不代理查詢——這是刻意設計，早期版本讓 server 代跑查詢，同步阻塞的網路呼叫在並發時會卡住整個 event loop（MCP tool 沒有 FastAPI 那種自動 thread pool offload）。`get_powerbi_token` 內部用 `anyio.to_thread.run_sync` 包住 MSAL 呼叫，避免同樣問題。
- `acquire_powerbi_token()`（`credential.py`）每次呼叫都重建 `ConfidentialClientApplication`，MSAL 內建的 token cache 因此沒作用；已知但暫緩優化，見函式內 TODO 註記。
- OAuth client 一律走 Dynamic Client Registration + PKCE（public client，不核發 client_secret）。
- `/auth/login`、`/oauth/authorize` 的登入共用 `security.authenticate_user()`，累積 5 次密碼錯誤鎖定帳號（`User.failed_login_attempts`），只能由管理員在 `/admin/users` 解鎖，沒有自動過期解鎖。兩個入口共用同一組計數，其中一邊被鎖另一邊也會被鎖。
- `PbiConfig.filters` 是管理員在 `/admin/pbi-configs` 維護的篩選規則（JSON 陣列），透過 `get_model_detail` 交給 skill 端，取代原本 skill 本機 `filters/*.json` 的設計，格式與比對邏輯見 `docs/skill-integration.md`。
- 裸路徑 `/mcp`（沒有尾斜線）**不能**用 HTTP 307 轉址到 `/mcp/` 處理——部分 MCP client（例如 Gemini）跟隨轉址重新發送請求時不會保留 `Authorization` header，會導致認證失敗。`main.py` 的 `_McpTrailingSlashFix` 改成在 ASGI 層、Starlette Router 判斷路由之前，直接把路徑內部改寫成 `/mcp/`，同一個請求處理完，client 端完全不會看到任何轉址；這個 wrapper 必須包住整個 `app`（不能只包 `/mcp` 掛載的 sub-app），因為 Router 判斷要不要進到 Mount 這一步，發生在 sub-app 被呼叫之前。
- 存取歷史（`access_logs` 表）在三個既有身份驗證點各自補一行寫入（`auth.py` 的 `_require_user`、`mcp.py` 的 `_JwtTokenVerifier`、`credential.py` 的 `_resolve_user`），共用 `app/access_log.py` 的 `record_access()`，只記錄驗證成功的請求。`/mcp` 這個點沒有 `Request` context 可用（`TokenVerifier.verify_token()` 介面只給 token 字串），所以 IP／HTTP method 這兩欄位在 MCP 的紀錄裡會是空的。只留 90 天，`main.py` 的 lifespan 開一個背景 task 每天清一次舊資料，沒有另外掛排程服務。

## 分支策略

1. `main` 必須隨時保持可直接部署——VM 是直接 `git pull` 這個分支上線的，任何未完成/未測試的功能不上 `main`。
2. 跟目前開發中大型功能無關的一般性 bug fix、小改動，直接對 `main` 提交，不用等大型功能做完。
3. 大型功能（例如 MCP）開一個專屬 epic 分支（如 `feature/oauth-mcp`），可以橫跨多個階段、多個 session 持續累積工作，不需要每個小階段就急著合併回去。
4. Epic 分支要**定期**把 `main` merge 進來吸收無關的核心修正，避免分岔太久難合併——尤其如果 epic 分支有動到共用核心檔案（如這次 MCP 動到的 `models.py`、`main.py`、`credential.py`、`security.py`），不是獨立新檔案能完全隔開的。
5. Epic 功能穩定到可以正式提供給使用者用時，整個合併回 `main`，分支才算完成任務。
6. Commit message：涉及安全性修正時不描述具體弱點細節，一般功能改動正常描述即可。

## 開發啟動

```bash
# 第一次
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # 填入 SERVER_JWT_SECRET 與 ADMIN_SECRET
cd admin-frontend && npm install && cd ..
npm install            # 安裝 concurrently

# 日常
npm run dev            # 同時啟動 uvicorn + Vite dev server
```

## 重要環境變數（.env）

| 變數 | 說明 |
|------|------|
| `SERVER_JWT_SECRET` | 主金鑰，64 字元隨機 hex。JWT 簽發 + AES-256 key derivation，也是 MCP access token 簽章金鑰 |
| `ADMIN_SECRET` | 管理後台登入密碼 |
| `DATABASE_URL` | 預設 `sqlite:///./credential.db` |
| `SITE_DOMAIN` | 對外網域（不可為裸 IP）。Caddy 拿來申請 HTTPS 憑證，也是 OAuth issuer / MCP resource URL 的基礎 |
| `ALLOWED_IPS` | IP 白名單，逗號分隔，留空不限制 |

## 目錄結構

```
app/
  main.py          FastAPI 入口（CORS、SPA static、MCP mount + lifespan、access_logs 每日清理 task）
  security.py      JWT、密碼、AES、PKCE 驗證、MCP token 簽發
  access_log.py    存取歷史寫入共用邏輯（record_access），三個身份驗證點都呼叫這裡
  models.py        SQLAlchemy ORM（含 OAuth 三張表 + personal_access_tokens + access_logs）
  database.py      SQLAlchemy 設定
  routers/
    auth.py        /auth（使用者，含 /auth/mcp-tokens 自助 PAT CRUD）
    credential.py  /api（Skill legacy），也提供 acquire_powerbi_token 給 MCP 用
    admin.py       /api/admin（管理員）
    oauth.py       /oauth、/.well-known（OAuth 2.1 authorization server）
    mcp.py         /mcp（MCP server + tools：list_models/get_model_detail/get_powerbi_token）
admin-frontend/    Vue 3 SPA（Element Plus + Pinia）
scripts/
  chunk_model.py   離線工具：將原始 PBI JSON 拆分成 relationships + tables
tests/             pytest（OAuth flow + MCP 協定完整往返測試，跑法見 README）
docs/
  skill-integration.md  Skill 串接指南（MCP 為主，legacy REST API 為輔）
  plan.md          初期規劃文件（歷史參考）
```

## 前端路由規劃

```
/login              使用者登入
/register           使用者自助註冊
/dashboard          使用者登入後首頁（查看憑證狀態、領取 key，連結到 /mcp-tokens）
/mcp-tokens         MCP Personal Access Token 自助管理（跟 PBI_MASK_KEY UI 刻意分開，避免混淆兩種機制）

/admin              重導向至 /admin/login
/admin/login        管理員登入
/admin/users        使用者管理（管理員）
/admin/pbi-configs  PBI 設定管理（管理員）
/admin/model        語意模型管理（管理員）
/admin/access-logs  存取歷史查詢／匯出（管理員）
```

管理員與使用者的 JWT 過期時，`admin-frontend/src/api/http.ts` 的 axios response 攔截器會在收到 401 時清除 token 並導回對應登入頁（管理員 → `/admin/login`）。**修改前端後必須執行 `npm run build --prefix admin-frontend` 重新產生 `dist/`**，否則 FastAPI 會繼續 serve 舊的靜態檔案，導致行為與原始碼不一致（例如導向錯誤的登入頁）。

## Docker 部署

```dockerfile
# 建置前端
RUN npm ci --prefix admin-frontend && npm run build --prefix admin-frontend
# 啟動後端（會自動 serve dist/）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`admin-frontend/dist/` 存在時，FastAPI 自動 mount 靜態檔案並加 catch-all 回傳 `index.html`。

服務前面掛 [Caddy](https://caddyserver.com/)（見 [Caddyfile](Caddyfile)）做 TLS termination，自動跟 Let's Encrypt 要憑證並續約。`app` 容器改成 `expose`、不直接對外發布 port，對外只開 80/443，一律經過 Caddy 反向代理——**這代表 `.env` 一定要有 `SITE_DOMAIN`**（不能是裸 IP，沒域名可先用 `<IP 把 . 換成 ->.sslip.io` 頂著），Caddy 第一次啟動需要 80/443 對外可連才能完成 ACME 驗證。改動 `docker-compose.yml`/`Caddyfile`/新增 router 後要 `docker compose up --build -d`（單純 `up` 不會重建 image）。
