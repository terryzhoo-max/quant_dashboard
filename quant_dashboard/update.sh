#!/bin/bash
# ============================================================
#  AlphaCore 一键更新脚本 v3.1 (生产级)
#  用法: bash update.sh
#
#  v3.1 修复 (2026-05-23):
#    - 修复: 管道吞退出码 (PIPESTATUS)
#    - 修复: 健康检查必须等到 status=ok
#    - 修复: SIGINT/SIGTERM 安全中断
#    - 优化: build 日志只记摘要, 不写全量输出
#    - 优化: 回滚前备份 docker-compose.yml
#
#  v3.0 特性:
#    - 先构建后切换: 镜像构建成功后才停旧容器 (最小化停机)
#    - 健康检查轮询: 最多等 60s, 每 3s 检查一次
#    - 自动回滚: 健康检查失败时回退到旧镜像
#    - 磁盘预检: 剩余 <2G 时拒绝更新
#    - 并发锁: 防止同时执行多个 update
#    - 旧镜像自动清理: 部署成功后清理悬空镜像
#    - 全程日志: 同时输出到终端和日志文件
# ============================================================

set -o pipefail  # 管道中任一命令失败则整个管道失败

# ── 配置 ──
APP_DIR="/root/quant_dashboard"
CODE_DIR="${APP_DIR}/quant_dashboard"
IMAGE_NAME="quant_dashboard-quant_dashboard"
LOCK_FILE="/tmp/alphacore_update.lock"
LOG_FILE="/root/backups/update.log"
HEALTH_URL="http://localhost:8000/health"
HEALTH_TIMEOUT=240      # 健康检查最大等待秒数（Dashboard 预热默认 120s 后才开始）
HEALTH_INTERVAL=3       # 检查间隔
MIN_DISK_MB=2048        # 最低剩余磁盘 (2 GB)

# ── 状态追踪 (安全中断用) ──
CONTAINER_REMOVED=false
OLD_IMAGE_ID=""

# ── 日志函数 ──
mkdir -p "$(dirname "$LOG_FILE")"
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

# ── 安全清理 (EXIT / INT / TERM) ──
cleanup() {
    local exit_code=$?
    rm -f "$LOCK_FILE"

    # 如果在容器已删但新服务未通过健康检查时被中断, 自动恢复
    if [ "$CONTAINER_REMOVED" = true ] && [ "$exit_code" -ne 0 ]; then
        echo ""
        log "⚠️  检测到异常退出 (code=$exit_code), 尝试恢复服务..."
        if [ -n "$OLD_IMAGE_ID" ]; then
            docker tag "$OLD_IMAGE_ID" "$IMAGE_NAME" 2>/dev/null || true
        fi
        cd "$CODE_DIR" 2>/dev/null || true
        docker rm -f quant_dashboard_app 2>/dev/null || true
        docker compose up -d 2>/dev/null || true
        log "  🔄 服务已恢复 (请手动验证: curl localhost:8000/health)"
    fi
}
trap cleanup EXIT
trap 'log "⚠️  收到中断信号, 安全退出..."; exit 130' INT TERM

# ── 并发锁 ──
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        log "❌ 另一个更新进程正在运行 (PID: $LOCK_PID), 退出"
        exit 1
    else
        log "⚠️  发现过期锁文件 (PID: $LOCK_PID 已不存在), 清理后继续"
        rm -f "$LOCK_FILE"
    fi
fi
echo $$ > "$LOCK_FILE"

# ── 开始 ──
log ""
log "╔══════════════════════════════════════════════╗"
log "║   AlphaCore 一键更新 v3.1 (生产级)           ║"
log "╚══════════════════════════════════════════════╝"
log ""

START_TIME=$(date +%s)

# ══════════════════════════════════════════════════
#  Step 0: 预检
# ══════════════════════════════════════════════════
log "⏳ [0/5] 环境预检..."

# 磁盘空间检查
AVAIL_MB=$(df --output=avail -m / | tail -1 | tr -d ' ')
if [ "$AVAIL_MB" -lt "$MIN_DISK_MB" ]; then
    log "❌ 磁盘剩余 ${AVAIL_MB}MB < ${MIN_DISK_MB}MB, 请先清理磁盘!"
    log "   运行: docker system prune -a -f && docker builder prune -a -f"
    exit 1
fi
log "  ✅ 磁盘: 剩余 $((AVAIL_MB / 1024))GB"

# Docker 检查
if ! docker info >/dev/null 2>&1; then
    log "❌ Docker 未运行!"
    exit 1
fi
log "  ✅ Docker: 运行中"

# .env 检查
if [ ! -f "${CODE_DIR}/.env" ]; then
    log "❌ ${CODE_DIR}/.env 不存在!"
    exit 1
fi
log "  ✅ .env: 存在"
log ""

# ══════════════════════════════════════════════════
#  Step 1: 拉取代码
# ══════════════════════════════════════════════════
log "⏳ [1/5] 拉取最新代码..."
cd "$APP_DIR"

OLD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

git stash --include-untracked -q 2>/dev/null || true
if ! git pull 2>&1 | tee -a "$LOG_FILE"; then
    log "❌ git pull 失败!"
    git stash pop -q 2>/dev/null || true
    exit 1
fi
git stash drop -q 2>/dev/null || true

NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    log "  ℹ️  代码无变化 ($NEW_COMMIT), 继续构建以同步配置"
else
    log "  ✅ 代码: $OLD_COMMIT → $NEW_COMMIT"
    log "  📝 $(git log --oneline -1)"
fi
log ""

# ══════════════════════════════════════════════════
#  Step 2: 构建新镜像 (旧容器继续运行)
# ══════════════════════════════════════════════════
log "⏳ [2/5] 构建新镜像 (旧服务保持运行中)..."
cd "$CODE_DIR"

# 保存旧镜像 ID 用于回滚
OLD_IMAGE_ID=$(docker images -q "$IMAGE_NAME" 2>/dev/null | head -1)
if [ -n "$OLD_IMAGE_ID" ]; then
    # 给旧镜像打回滚标签 (防止被 prune 清理)
    docker tag "$OLD_IMAGE_ID" "${IMAGE_NAME}:rollback" 2>/dev/null || true
fi

BUILD_START=$(date +%s)

# 构建镜像, 只在终端显示输出, 日志只记录结果
# set -o pipefail 确保 docker build 失败时整个管道返回非零
if ! docker build --network=host -t "$IMAGE_NAME" . 2>&1; then
    BUILD_END=$(date +%s)
    log "❌ 镜像构建失败! (耗时 $((BUILD_END - BUILD_START))s)"
    log "   旧服务未受影响, 继续运行"
    exit 1
fi

BUILD_END=$(date +%s)
log "  ✅ 镜像构建完成 ($((BUILD_END - BUILD_START))s)" 
log ""

# ══════════════════════════════════════════════════
#  Step 3: 切换容器 (最小化停机窗口)
# ══════════════════════════════════════════════════
log "⏳ [3/5] 切换容器..."
cd "$CODE_DIR"

# 修复 data_lake 目录权限，防止非 root 容器用户 (alphacore: 1000) 遭遇 Permission Denied
if [ -d "${CODE_DIR}/data_lake" ]; then
    # V3.2: 迁移旧版运行时数据到 data_lake (首次部署迁移)
    for f in portfolio_store.json trade_history.json audit_enforcement_log.json; do
        if [ -f "${CODE_DIR}/${f}" ] && [ ! -f "${CODE_DIR}/data_lake/${f}" ]; then
            cp "${CODE_DIR}/${f}" "${CODE_DIR}/data_lake/${f}"
            log "  📦 迁移 ${f} → data_lake/"
        fi
    done
    chown -R 1000:1000 "${CODE_DIR}/data_lake" 2>/dev/null || true
    chmod -R 775 "${CODE_DIR}/data_lake" 2>/dev/null || true
fi

# 标记: 从这里开始旧容器将被移除
# 如果后续步骤失败或被中断, cleanup() 会自动恢复
CONTAINER_REMOVED=true

docker rm -f quant_dashboard_app 2>/dev/null || true
if ! docker compose up -d 2>&1 | tee -a "$LOG_FILE"; then
    log "❌ 容器启动失败! 自动回滚..."
    if [ -n "$OLD_IMAGE_ID" ]; then
        docker rm -f quant_dashboard_app 2>/dev/null || true
        docker tag "$OLD_IMAGE_ID" "$IMAGE_NAME" 2>/dev/null || true
        docker compose up -d 2>/dev/null || true
        log "  🔄 已回滚到旧镜像 ($OLD_IMAGE_ID)"
    fi
    exit 1
fi
log "  ✅ 容器已切换"
log ""

# ══════════════════════════════════════════════════
#  Step 4: 健康检查 (轮询, 最多 60s)
# ══════════════════════════════════════════════════
log "⏳ [4/5] 健康检查 (最多 ${HEALTH_TIMEOUT}s)..."

WAITED=0
HEALTHY=false
HEALTH_JSON=""

while [ "$WAITED" -lt "$HEALTH_TIMEOUT" ]; do
    RESP=$(curl -s --max-time 3 "$HEALTH_URL" 2>/dev/null || echo "")
    if [ -n "$RESP" ]; then
        STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
        if [ "$STATUS" = "ok" ]; then
            # 必须是 ok, starting 不算通过
            HEALTHY=true
            HEALTH_JSON="$RESP"
            break
        elif [ "$STATUS" = "starting" ] && [ $((WAITED % 15)) -eq 0 ] && [ "$WAITED" -gt 0 ]; then
            log "  ⏳ 服务预热中... (${WAITED}s)"
        fi
    fi
    sleep "$HEALTH_INTERVAL"
    WAITED=$((WAITED + HEALTH_INTERVAL))
done

if [ "$HEALTHY" = true ]; then
    log "  ✅ 健康检查通过 (${WAITED}s)"
    CONTAINER_REMOVED=false  # 健康通过, 取消安全恢复标记
else
    log "  ❌ 健康检查超时 (${HEALTH_TIMEOUT}s)!"
    log ""
    log "  📋 容器日志 (最近 30 行):"
    docker logs --tail 30 quant_dashboard_app 2>&1 | tee -a "$LOG_FILE"
    log ""

    # 自动回滚
    log "  🔄 自动回滚到旧镜像..."
    if [ -n "$OLD_IMAGE_ID" ]; then
        docker rm -f quant_dashboard_app 2>/dev/null || true
        docker tag "$OLD_IMAGE_ID" "$IMAGE_NAME" 2>/dev/null || true
        docker compose up -d 2>/dev/null || true

        # 验证回滚是否成功
        sleep 10
        ROLLBACK_STATUS=$(curl -s --max-time 3 "$HEALTH_URL" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
        if [ "$ROLLBACK_STATUS" = "ok" ]; then
            log "  ✅ 回滚成功, 旧版本已恢复运行"
            CONTAINER_REMOVED=false
        else
            log "  ⚠️  回滚后健康检查未通过 (status=$ROLLBACK_STATUS)"
            log "     请手动检查: docker logs quant_dashboard_app"
        fi
    else
        log "  ⚠️  无旧镜像可回滚, 请手动排查"
    fi
    exit 1
fi
log ""

# ══════════════════════════════════════════════════
#  Step 5: 清理 + 报告
# ══════════════════════════════════════════════════
log "⏳ [5/5] 清理..."

# 删除回滚标签 (部署成功, 不再需要)
docker rmi "${IMAGE_NAME}:rollback" 2>/dev/null || true

# 清理悬空镜像
PRUNED=$(docker image prune -f 2>/dev/null | grep "reclaimed" || echo "无需清理")
log "  🗑️ $PRUNED"

# 解析健康检查详情 (使用已缓存的 HEALTH_JSON, 不再额外请求)
CACHE=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('engines',{}).get('cache_backend','?'))" 2>/dev/null || echo "?")
VERSION=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")

END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))
DISK_AFTER=$(df --output=avail -m / | tail -1 | tr -d ' ')

log ""
log "╔══════════════════════════════════════════════╗"
log "║   ✅ 更新成功                                ║"
log "╠══════════════════════════════════════════════╣"
log "  📦 版本: ${VERSION}"
log "  📝 代码: ${NEW_COMMIT} · $(cd "$APP_DIR" && git log --format='%s' -1)"
log "  🗄️ 缓存: ${CACHE}"
log "  ⏱️ 耗时: ${TOTAL_TIME}s (构建 $((BUILD_END - BUILD_START))s)"
log "  💾 磁盘: 剩余 $((DISK_AFTER / 1024))GB"

PUBLIC_IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || echo "your-server-ip")
log "  🌐 访问: http://${PUBLIC_IP}:8000/"
log "╚══════════════════════════════════════════════╝"
log ""
