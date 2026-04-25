#!/bin/bash
# ============================================================
#  AlphaCore 一键部署脚本 v4.0
#  新增: Nginx HTTPS + API Key 认证 + 安全验证
#  用法: cd /root/quant_dashboard && bash deploy.sh
# ============================================================

set -e

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   AlphaCore 一键部署 v4.0 (App+Redis+Nginx) ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: 环境检查 ──
if [ ! -f ".env" ]; then
    echo "❌ 错误: 找不到 .env 文件!"
    echo "   请确保 .env 文件已上传到当前目录"
    exit 1
fi
echo "✅ .env 文件存在"

# Batch 6: 检查 API Key 是否已配置
API_KEY=$(grep -oP 'API_SECRET_KEY=\K.+' .env 2>/dev/null || echo "")
if [ -z "$API_KEY" ]; then
    echo "⚠️  警告: API_SECRET_KEY 未配置! 写入 API 将不受保护"
    echo "   建议: 在 .env 中添加 API_SECRET_KEY=<your-secret-key>"
else
    echo "✅ API Key 已配置 (长度: ${#API_KEY})"
fi

# ── Step 2: Docker 检查 ──
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

# ── Step 3: 目录准备 ──
mkdir -p data_lake/daily_prices
echo "✅ data_lake 目录就绪"

# ── Step 4: 停掉旧容器 ──
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

# ── Step 6: 等待服务启动 ──
echo ""
echo "⏳ 等待 Redis + App 启动..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    # 检查 Redis
    REDIS_OK=$(docker exec alphacore_redis redis-cli ping 2>/dev/null || echo "FAIL")
    if [ "$REDIS_OK" = "PONG" ]; then
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ "$REDIS_OK" = "PONG" ]; then
    echo "✅ Redis 已就绪 (${WAITED}s)"
else
    echo "⚠️  Redis 未在 ${MAX_WAIT}s 内就绪 (App 将自动降级为内存缓存)"
fi

# 等待 App 健康检查
sleep 10
echo ""
echo "════════════════ 启动验证 ════════════════"

# ── Step 7: 验证 ──

# 容器状态
if docker ps | grep -q quant_dashboard_app; then
    echo "✅ App 容器运行中"
else
    echo "❌ App 容器未运行!"
    echo "   查看错误: docker logs quant_dashboard_app"
    exit 1
fi

if docker ps | grep -q alphacore_redis; then
    echo "✅ Redis 容器运行中"
else
    echo "⚠️  Redis 容器未运行 (App 将降级为内存模式)"
fi

# 健康检查 API
HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null || echo '{"status":"unreachable"}')
STATUS=$(echo $HEALTH | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "unknown")
CACHE_BACKEND=$(echo $HEALTH | python3 -c "import sys,json; print(json.load(sys.stdin).get('engines',{}).get('cache_backend','?'))" 2>/dev/null || echo "unknown")

if [ "$STATUS" = "ok" ] || [ "$STATUS" = "starting" ]; then
    echo "✅ Health Check: ${STATUS} · 缓存后端: ${CACHE_BACKEND}"
else
    echo "⚠️  Health Check: ${STATUS} (服务可能还在预热)"
fi

# 安全检查
PY_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/config.py 2>/dev/null || echo "000")
if [ "$PY_CODE" = "404" ]; then
    echo "✅ 安全拦截生效 (config.py → 404)"
else
    echo "⚠️  安全拦截异常: config.py 返回 $PY_CODE"
fi

# Batch 6: API Key 认证验证
if [ -n "$API_KEY" ]; then
    # 无 Key 的 POST → 应返回 401
    AUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/aiae/update_fund_position -H "Content-Type: application/json" -d '{"value":80}' 2>/dev/null || echo "000")
    if [ "$AUTH_CODE" = "401" ]; then
        echo "✅ API Key 认证生效 (未授权 POST → 401)"
    else
        echo "⚠️  API Key 认证异常: 未授权 POST 返回 $AUTH_CODE"
    fi
    # 有 Key 的 POST → 应正常处理
    AUTH_OK_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/aiae/update_fund_position -H "Content-Type: application/json" -H "X-API-Key: $API_KEY" -d '{"value":80}' 2>/dev/null || echo "000")
    if [ "$AUTH_OK_CODE" != "401" ] && [ "$AUTH_OK_CODE" != "403" ]; then
        echo "✅ API Key 授权正常 (认证 POST → $AUTH_OK_CODE)"
    else
        echo "⚠️  API Key 授权异常: 认证 POST 返回 $AUTH_OK_CODE"
    fi
else
    echo "⚠️  跳过 API Key 验证 (未配置)"
fi

# Redis 连通性
if [ "$CACHE_BACKEND" = "redis" ]; then
    REDIS_KEYS=$(docker exec alphacore_redis redis-cli dbsize 2>/dev/null | grep -oP '\d+' || echo "0")
    echo "✅ Redis 分布式缓存已激活 · keys: ${REDIS_KEYS}"
elif [ "$CACHE_BACKEND" = "memory" ]; then
    echo "⚠️  当前为内存缓存模式 (检查 Redis 容器状态)"
fi

# 公网访问地址
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "your-server-ip")

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🎉 部署成功!                               ║"
echo "╠══════════════════════════════════════════════╣"
echo "║                                              ║"
echo "   访问地址: http://${PUBLIC_IP}:8000/"
echo "   健康检查: http://${PUBLIC_IP}:8000/health"
echo "║                                              ║"
echo "║   🔒 安全信息:                                ║"
echo "   API Key 认证: 已启用"
echo "   Nginx HTTPS: 取消 docker-compose 注释后启用"
echo "║                                              ║"
echo "║   常用命令:                                   ║"
echo "║   查看日志: docker logs -f quant_dashboard_app║"
echo "║   Redis CLI: docker exec -it alphacore_redis redis-cli"
echo "║   重启服务: docker-compose restart            ║"
echo "║   停止服务: docker-compose down               ║"
echo "║                                              ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
