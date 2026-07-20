#!/bin/bash
# Oracle Cloud Ubuntu VM 初始化腳本
# 用法：bash setup-vm.sh
set -e

REPO="git@github.com:hugo2135/credential_applycation_server.git"
APP_DIR="$HOME/credential_applycation_server"

echo_step() { echo ""; echo "==== $1 ===="; }

# ── 1. Swap ───────────────────────────────────────────────────────────────────
echo_step "設定 Swap (2GB)"
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo "Swap 已建立"
else
  echo "Swap 已存在，跳過"
fi

# ── 2. Docker ─────────────────────────────────────────────────────────────────
echo_step "安裝 Docker"
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo ""
  echo "[!] Docker 已安裝，需要重新登入才能不用 sudo 執行 docker。"
  echo "    請登出後重新 SSH，再執行一次本腳本。"
  exit 0
else
  echo "Docker 已安裝，跳過"
fi

# ── 3. 防火牆 ─────────────────────────────────────────────────────────────────
echo_step "設定 iptables (port 80/443)"
for PORT in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT -p tcp --dport "$PORT" -j ACCEPT
  fi
done
if ! dpkg -l | grep -q iptables-persistent; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
fi
sudo netfilter-persistent save
echo "防火牆設定完成（Caddy 需要 80/443 對外可連才能完成 Let's Encrypt 驗證）"

# ── 4. GitHub SSH Key ─────────────────────────────────────────────────────────
echo_step "GitHub SSH Key"
if [ ! -f ~/.ssh/id_ed25519 ]; then
  ssh-keygen -t ed25519 -C "oracle-vm" -f ~/.ssh/id_ed25519 -N ""
  echo ""
  echo "[!] 請將以下公鑰加入 GitHub → Settings → SSH and GPG keys → New SSH key："
  echo ""
  cat ~/.ssh/id_ed25519.pub
  echo ""
  read -rp "加入完成後按 Enter 繼續..."
else
  echo "SSH key 已存在，跳過"
fi

# 確認 GitHub 連線
ssh -o StrictHostKeyChecking=no -T git@github.com 2>&1 | grep -q "successfully authenticated" \
  && echo "GitHub 連線成功" \
  || { echo "[!] GitHub SSH 連線失敗，請確認公鑰已加入 GitHub"; exit 1; }

# ── 5. Clone 專案 ─────────────────────────────────────────────────────────────
echo_step "Clone 專案"
if [ ! -d "$APP_DIR" ]; then
  git clone "$REPO" "$APP_DIR"
else
  echo "專案已存在，執行 git pull"
  git -C "$APP_DIR" pull
fi

# ── 6. 環境變數 ───────────────────────────────────────────────────────────────
echo_step "設定 .env"
cd "$APP_DIR"
if [ ! -f .env ]; then
  echo ""
  read -rp "SERVER_JWT_SECRET（留空自動產生 64 字元 hex）: " JWT_SECRET
  if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "已自動產生：$JWT_SECRET"
  fi
  read -rp "ADMIN_SECRET（管理後台登入密碼）: " ADMIN_SECRET
  read -rp "ALLOWED_IPS（辦公室 IP，逗號分隔，留空不限制）: " ALLOWED_IPS

  PUBLIC_IP_HINT=$(curl -s --max-time 5 ifconfig.me || echo "<你的公網IP>")
  DASHED_IP=$(echo "$PUBLIC_IP_HINT" | tr '.' '-')
  echo ""
  echo "SITE_DOMAIN 是 Caddy 拿來自動申請 HTTPS 憑證用的網域，不能是裸 IP。"
  echo "如果還沒有正式網域，可以先用免費的 ${DASHED_IP}.sslip.io（之後買了網域再換掉即可）。"
  read -rp "SITE_DOMAIN: " SITE_DOMAIN

  cat > .env <<EOF
SERVER_JWT_SECRET=$JWT_SECRET
ADMIN_SECRET=$ADMIN_SECRET
DATABASE_URL=sqlite:////app/data/credential.db
ALLOWED_IPS=$ALLOWED_IPS
SITE_DOMAIN=$SITE_DOMAIN
EOF
  echo ".env 已建立"
else
  echo ".env 已存在，跳過（如需修改請手動編輯 $APP_DIR/.env）"
fi

# ── 7. 資料目錄 ───────────────────────────────────────────────────────────────
echo_step "建立資料目錄"
mkdir -p "$APP_DIR/data"
echo "data/ 已就緒"

# ── 8. 啟動服務 ───────────────────────────────────────────────────────────────
echo_step "建置並啟動服務"
cd "$APP_DIR"
docker compose up --build -d
docker image prune -f

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
SITE_DOMAIN=$(grep "^SITE_DOMAIN=" .env | cut -d= -f2-)
echo "部署完成！"
echo "服務網址：https://${SITE_DOMAIN}"
echo "管理後台：https://${SITE_DOMAIN}/admin/login"
echo "（Caddy 第一次簽發憑證需要幾秒到幾十秒，如果馬上連線失敗請稍等重試）"
echo "========================================"
