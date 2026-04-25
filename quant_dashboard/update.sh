#!/bin/bash
# ============================================================
#  AlphaCore 一键更新脚本 v1.0
#  用法: bash /root/update.sh
#  说明: 拉取代码 → 重建镜像 → 重启容器 → 健康验证
# ============================================================

set -e

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   AlphaCore 一键更新                        ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: 拉取代码 ──
echo "⏳ [1/4] 拉取最新代码..."
cd /root/quant_dashboard && git pull
echo "✅ 代码已更新: $(git log --oneline -1)"

# ── Step 2: 重建镜像 ──
echo ""
echo "⏳ [2/4] 重建 Docker 镜像 (约 2-3 分钟)..."
cd /root/quant_dashboard/quant_dashboard
DOCKER_BUILDKIT=0 docker build --no-cache --network host \
  -t quant_dashboard_quant_dashboard .
echo "✅ 镜像已重建"

# ── Step 3: 重启容器 ──
echo ""
echo "⏳ [3/4] 重启容器..."
docker rm -f quant_dashboard_app 2>/dev/null || true
docker run -d \
  --name quant_dashboard_app \
  --restart unless-stopped \
  --network quant_dashboard_default \
  --dns 8.8.8.8 --dns 223.5.5.5 \
  -p 8000:8000 \
  -v /root/quant_dashboard/quant_dashboard/data_lake:/app/data_lake \
  --env-file /root/quant_dashboard/quant_dashboard/.env \
  -e REDIS_HOST=redis \
  -e REDIS_PORT=6379 \
  -e AC_LOG_FORMAT=console \
  -e AC_LOG_LEVEL=INFO \
  quant_dashboard_quant_dashboard
echo "✅ 容器已重启"

# ── Step 4: 健康验证 ──
echo ""
echo "⏳ [4/4] 等待服务启动 (15s)..."
sleep 15

STATUS=$(curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','FAIL'))" 2>/dev/null || echo "UNREACHABLE")
CACHE=$(curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('engines',{}).get('cache_backend','?'))" 2>/dev/null || echo "?")
VERSION=$(curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")

echo ""
echo "════════════════ 更新结果 ════════════════"
if [ "$STATUS" = "ok" ]; then
  echo "  ✅ 状态: ${STATUS}"
else
  echo "  ⚠️  状态: ${STATUS} (可能还在预热, 请等待 1 分钟)"
fi
echo "  📦 版本: ${VERSION}"
echo "  🗄️ 缓存: ${CACHE}"
echo "  📝 代码: $(cd /root/quant_dashboard && git log --oneline -1)"

PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "your-server-ip")
echo "  🌐 访问: http://${PUBLIC_IP}:8000/"
echo "═══════════════════════════════════════════"
echo ""
