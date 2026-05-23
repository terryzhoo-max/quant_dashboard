#!/bin/bash
# ============================================================
#  AlphaCore 一键更新脚本 v2.0
#  用法: bash /root/quant_dashboard/quant_dashboard/update.sh
#  说明: 拉取代码 → 重建镜像 → 重启容器 → 健康验证
#
#  v2.0 变更 (2026-05-23):
#    - 移除 DOCKER_BUILDKIT=0 (已废弃)
#    - 使用 docker build --network=host 解决 DNS 隔离
#    - 使用 docker compose up -d 替代手动 docker run
#    - 镜像名统一为 quant_dashboard-quant_dashboard
# ============================================================

set -e

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   AlphaCore 一键更新 v2.0                    ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: 拉取代码 ──
echo "⏳ [1/4] 拉取最新代码..."
cd /root/quant_dashboard

# 服务器运行时 data_lake/*.parquet 会被应用更新,
# 导致 git pull 冲突. 先 stash 再拉取, 数据不丢失
# (因为 docker run 用 -v 挂载 data_lake, 实际数据在宿主机上).
git stash --include-untracked -q 2>/dev/null || true
git pull
git stash drop -q 2>/dev/null || true

echo "✅ 代码已更新: $(git log --oneline -1)"

# ── Step 2: 重建镜像 ──
echo ""
echo "⏳ [2/4] 重建 Docker 镜像..."
cd /root/quant_dashboard/quant_dashboard

# --network=host: 解决 BuildKit bridge 网络 DNS 隔离问题
# 不加 --no-cache: 利用 Docker 层缓存加速 (requirements.txt 未变时秒级构建)
docker build --network=host \
  -t quant_dashboard-quant_dashboard .
echo "✅ 镜像已重建"

# ── Step 3: 重启容器 ──
echo ""
echo "⏳ [3/4] 重启容器..."
docker rm -f quant_dashboard_app 2>/dev/null || true
docker compose up -d
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
