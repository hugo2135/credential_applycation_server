# Stage 1: 建置 Vue 前端
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend-builder
WORKDIR /app
COPY admin-frontend/package*.json ./admin-frontend/
RUN npm ci --prefix admin-frontend
COPY admin-frontend/ ./admin-frontend/
RUN npm run build --prefix admin-frontend

# Stage 2: Python 後端
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/

# 複製前端建置結果
COPY --from=frontend-builder /app/admin-frontend/dist ./admin-frontend/dist

# 資料庫預設放 /app/data（掛 volume 用）
ENV DATABASE_URL=sqlite:////app/data/credential.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
