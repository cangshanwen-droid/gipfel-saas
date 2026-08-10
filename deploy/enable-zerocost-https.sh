#!/bin/bash
# ============================================================
# Gipfel 零成本 HTTPS 升级脚本 — DuckDNS + Let's Encrypt
# 服务器：106.54.26.86 (Ubuntu 20.04)
# 用法：sudo bash enable-zerocost-https.sh <域名> <邮箱>
#   例：sudo bash enable-zerocost-https.sh gipfel.duckdns.org you@example.com
# 前置：1) DuckDNS 已注册子域名且 A 记录指向 106.54.26.86
#       2) 腾讯云安全组已放行 80/443
# ============================================================
set -e

DOMAIN="${1:?用法: sudo bash $0 <域名> <邮箱>}"
EMAIL="${2:?用法: sudo bash $0 <域名> <邮箱>}"
echo "==> 域名: $DOMAIN | 邮箱: $EMAIL"

# 0. 备份现有配置
cp /etc/nginx/sites-available/gipfel /etc/nginx/sites-available/gipfel.bak-selfsigned-$(date +%Y%m%d)
echo "==> 已备份 nginx 配置"

# 1. 安装 certbot
echo "==> 安装 certbot..."
apt-get update -qq
apt-get install -y -qq certbot python3-certbot-nginx

# 2. 验证 DNS 指向本机
SERVER_IP=$(curl -s -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
DOMAIN_IP=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1)
echo "    服务器 IP: $SERVER_IP"
echo "    域名解析: $DOMAIN_IP"
if [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
  echo "!! 域名未指向本服务器。请先在 DuckDNS 设置 A 记录: $DOMAIN -> $SERVER_IP"
  echo "   并等待 DNS 生效（dig +short $DOMAIN）"
  exit 1
fi

# 3. 先放行 /.well-known 挑战路径（当前配置 80 全站 301，挑战会失败）
echo "==> 调整 nginx 80 块以支持 ACME 挑战..."
cat > /etc/nginx/sites-available/gipfel.acme <<'EOF'
# Gipfel — ACME 挑战临时配置（certbot 会接管）
server {
    listen 80;
    listen [::]:80;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
EOF
# 仅当当前配置没有 acme 放行时插入
if ! grep -q "acme-challenge" /etc/nginx/sites-available/gipfel; then
  # 在当前 80 server 块的 return 301 前插入 location
  sudo sed -i 's|return 301 https://\$host\$request_uri;|location /.well-known/acme-challenge/ { root /var/www/certbot; }\n    return 301 https://$host$request_uri;|' /etc/nginx/sites-available/gipfel
fi
mkdir -p /var/www/certbot
nginx -t && systemctl reload nginx
echo "==> ACME 挑战路径已放行"

# 4. certbot 签发（nginx 插件自动改 443 配置 + 配续期）
echo "==> 申请 Let's Encrypt 证书..."
certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --redirect --non-interactive || {
  echo "==> nginx 插件失败，回退 webroot 方式..."
  certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --non-interactive
}

# 5. 检查证书
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
if [ ! -f "$CERT_DIR/fullchain.pem" ]; then
  echo "!! 证书申请失败，检查 DNS/邮箱后重试"
  exit 1
fi
echo "==> 证书已就绪: $CERT_DIR"

# 6. 确保 nginx 443 使用正式证书
if ! grep -q "letsencrypt" /etc/nginx/sites-available/gipfel; then
  echo "==> 手动替换证书路径..."
  sed -i "s|ssl_certificate     /etc/ssl/gipfel.crt;|ssl_certificate     $CERT_DIR/fullchain.pem;|" /etc/nginx/sites-available/gipfel
  sed -i "s|ssl_certificate_key /etc/ssl/gipfel.key;|ssl_certificate_key $CERT_DIR/privkey.pem;|" /etc/nginx/sites-available/gipfel
  sed -i "s|server_name _;|server_name $DOMAIN;|g" /etc/nginx/sites-available/gipfel
  nginx -t && systemctl reload nginx
fi

# 7. 测试续期
echo "==> 测试自动续期..."
certbot renew --dry-run 2>&1 | tail -3

echo ""
echo "======================================================"
echo "✅ HTTPS 升级完成！"
echo "   浏览器访问 https://$DOMAIN 应为绿锁（Let's Encrypt）"
echo ""
echo "下一步（桌面端）:"
echo "  1. 替换 8 处 https://106.54.26.86 -> https://$DOMAIN"
echo "  2. 删除 src/main/index.ts 的 setCertificateVerifyProc 特判"
echo "  3. 重新 npm run package"
echo "======================================================"
