#!/bin/bash
# ============================================================
#  AlphaCore SSL 初始化脚本
#  用途: 首次部署时生成自签证书 (Nginx 启动需要)
#        之后由 certbot 替换为 Let's Encrypt 真实证书
#
#  用法: bash nginx/init-ssl.sh
# ============================================================

SSL_DIR="./nginx/ssl"

mkdir -p "$SSL_DIR"

# 检查是否已有证书
if [ -f "$SSL_DIR/fullchain.pem" ] && [ -f "$SSL_DIR/privkey.pem" ]; then
    echo "✅ SSL 证书已存在, 跳过生成"
    echo "   如需重新生成, 请删除 $SSL_DIR/ 目录后重新运行"
    exit 0
fi

echo "⏳ 生成自签 SSL 证书 (首次部署用, 后续由 certbot 替换)..."

openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "$SSL_DIR/privkey.pem" \
    -out "$SSL_DIR/fullchain.pem" \
    -subj "/C=CN/ST=Shanghai/L=Shanghai/O=AlphaCore/CN=localhost" \
    2>/dev/null

if [ $? -eq 0 ]; then
    echo "✅ 自签证书已生成:"
    echo "   证书: $SSL_DIR/fullchain.pem"
    echo "   私钥: $SSL_DIR/privkey.pem"
    echo ""
    echo "⚠️  生产环境请运行 certbot 获取 Let's Encrypt 真实证书:"
    echo "   docker compose run --rm certbot certonly --webroot -w /var/www/certbot -d your-domain.com"
else
    echo "❌ 证书生成失败! 请检查 openssl 是否安装"
    exit 1
fi
