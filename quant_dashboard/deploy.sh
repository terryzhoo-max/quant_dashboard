#!/bin/bash
# ============================================================
#  AlphaCore 一键部署脚本
#  用法: 把整个 quant_dashboard 文件夹上传到服务器后执行:
#        cd /root/quant_dashboard && bash deploy.sh
# ============================================================

set -e

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   AlphaCore 一键部署 v2.0                    ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: 检查 .env ──
if [ ! -f ".env" ]; then
    echo "❌ 错误: 找不到 .env 文件!"
    echo "   请确保 .env 文件已上传到当前目录"
    exit 1
fi
echo "✅ .env 文件存在"

# ── Step 2: 检查 Docker ──
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，正在自动安装..."
    curl -fsSL https://get.docker.com | sh
    systemctl start docker
    systemctl enable docker
fi
echo "✅ Docker 就绪"

if ! command -v docker-compose &> /dev/null; then
    echo "⏳ 安装 docker-compose..."
    pip3 install docker-compose -q 2>/dev/null || pip install docker-compose -q
fi
echo "✅ docker-compose 就绪"

# ── Step 3: 确保 data_lake 目录存在 ──
mkdir -p data_lake/daily_prices
echo "✅ data_lake 目录就绪"

# ── Step 4: 停掉旧容器 (如果有) ──
echo ""
echo "⏳ 停止旧容器..."
docker-compose down 2>/dev/null || true
echo "✅ 旧容器已清理"

# ── Step 5: 重建并启动 ──
echo ""
echo "⏳ 构建新镜像 (首次约3-5分钟, 请耐心等待)..."
echo "────────────────────────────────────────────"
docker-compose up -d --build
echo "────────────────────────────────────────────"

# ── Step 6: 等待启动 ──
echo ""
echo "⏳ 等待服务启动 (15秒)..."
sleep 15

# ── Step 7: 验证 ──
echo ""
echo "════════════════ 启动验证 ════════════════"

# 检查容器状态
if docker ps | grep -q quant_dashboard_app; then
    echo "✅ 容器运行中"
else
    echo "❌ 容器未运行!"
    echo "   查看错误: docker logs quant_dashboard_app"
    exit 1
fi

# 检查 API 响应
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ HTTP 服务正常 (200 OK)"
else
    echo "⚠️  HTTP 状态码: $HTTP_CODE (服务可能还在预热, 稍等片刻)"
fi

# 安全检查
PY_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/config.py 2>/dev/null || echo "000")
if [ "$PY_CODE" = "404" ]; then
    echo "✅ 安全拦截生效 (config.py → 404)"
else
    echo "⚠️  安全拦截异常: config.py 返回 $PY_CODE"
fi

# 获取服务器公网IP
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "8.219.112.184")

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🎉 部署成功!                               ║"
echo "╠══════════════════════════════════════════════╣"
echo "║                                              ║"
echo "   访问地址: http://${PUBLIC_IP}:8000/"
echo "║                                              ║"
echo "║   常用命令:                                   ║"
echo "║   查看日志: docker logs -f quant_dashboard_app║"
echo "║   重启服务: docker-compose restart            ║"
echo "║   停止服务: docker-compose down               ║"
echo "║                                              ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
