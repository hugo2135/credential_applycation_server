# CLAUDE.md — 開發者快速指南

## 專案定位

PBI Credential 申請程式：管理使用者身份、發放 Power BI 存取憑證、集中管理語意模型。
供 nl-to-dax Skill 透過 PBI_MASK_KEY 呼叫兩支核心 API。

## 架構

```
FastAPI 後端          Vue 3 SPA（同一 origin）
  /auth/*  → 使用者自助（註冊、登入、領取 key）
  /api/*   → Skill 呼叫（憑證 & 語意模型）
  /admin/* → 管理後台（CRUD、模型上傳）
```

## 認證設計

| 對象 | 方式 |
|------|------|
| 管理員 SPA | POST /admin/login（ADMIN_SECRET） → 1 hr HS256 JWT，Bearer |
| 使用者 SPA | POST /auth/token（帳密） → user session JWT，Bearer |
| Skill API | Authorization: Bearer \<PBI_MASK_KEY\>（SHA-256 hash 存 DB） |

## 關鍵安全細節

- `SERVER_JWT_SECRET`：**動態讀取**（`_get_secret()`），禁止 module-level 常數，避免 .env 載入時序問題。
- `datetime.now(timezone.utc)`：JWT 時間戳**必須**用這個，`utcnow()` 在 UTC+8 環境會讓 exp 提前 7 小時失效。
- `client_secret` 以 AES-256-GCM 加密存 DB，key 衍生自 `SERVER_JWT_SECRET`。
- PBI_MASK_KEY 明文只在產生時回傳一次，DB 只存 SHA-256 hash。

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
| `SERVER_JWT_SECRET` | 主金鑰，64 字元隨機 hex。JWT 簽發 + AES-256 key derivation |
| `ADMIN_SECRET` | 管理後台登入密碼 |
| `DATABASE_URL` | 預設 `sqlite:///./credential.db` |

## 目錄結構

```
app/
  main.py          FastAPI 入口（CORS、SPA static）
  security.py      JWT、密碼、AES
  models.py        SQLAlchemy ORM
  database.py      SQLAlchemy 設定
  routers/
    auth.py        /auth（使用者）
    credential.py  /api（Skill）
    admin.py       /admin（管理員）
admin-frontend/    Vue 3 SPA（Element Plus + Pinia）
scripts/
  chunk_model.py   離線工具：將原始 PBI JSON 拆分成 relationships + tables
docs/
  plan.md          初期規劃文件（歷史參考）
```

## 前端路由規劃

```
/login          管理員登入
/users          使用者管理（管理員）
/pbi-configs    PBI 設定管理（管理員）
/model          語意模型管理（管理員）
--- 待開發 ---
/register       使用者自助註冊
/dashboard      使用者登入後首頁（查看憑證狀態、領取 key）
```

## Docker 部署

```dockerfile
# 建置前端
RUN npm ci --prefix admin-frontend && npm run build --prefix admin-frontend
# 啟動後端（會自動 serve dist/）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`admin-frontend/dist/` 存在時，FastAPI 自動 mount 靜態檔案並加 catch-all 回傳 `index.html`。
