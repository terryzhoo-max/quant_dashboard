#!/bin/bash
# ============================================================
#  AlphaCore 定时备份脚本 v1.0
#  备份内容: data_lake + Redis + .env + 代码快照
#  保留策略: 最近 30 天
#  
#  用法:
#    手动执行: bash /root/quant_dashboard/backup.sh
#    定时执行: 脚本末尾会自动注册 cron (每天凌晨 3:00)
# ============================================================

set -e

# ── 配置 ──
APP_DIR="/root/quant_dashboard"
BACKUP_DIR="/root/backups/quant_dashboard"
KEEP_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="alphacore_${DATE}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

# ── 创建备份目录 ──
mkdir -p "${BACKUP_PATH}"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   AlphaCore 备份 · ${DATE}          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. 备份 data_lake (Parquet 缓存) ──
if [ -d "${APP_DIR}/data_lake" ]; then
    echo "⏳ [1/4] 备份 data_lake..."
    cp -r "${APP_DIR}/data_lake" "${BACKUP_PATH}/data_lake"
    DL_SIZE=$(du -sh "${BACKUP_PATH}/data_lake" | awk '{print $1}')
    echo "✅ data_lake: ${DL_SIZE}"
else
    echo "⚠️  data_lake 目录不存在, 跳过"
fi

# ── 2. 备份 Redis 数据 ──
echo "⏳ [2/4] 备份 Redis..."
if docker ps | grep -q alphacore_redis; then
    # 触发 Redis BGSAVE 确保数据落盘
    docker exec alphacore_redis redis-cli BGSAVE > /dev/null 2>&1
    sleep 2
    # 复制 RDB 快照
    docker cp alphacore_redis:/data/dump.rdb "${BACKUP_PATH}/redis_dump.rdb" 2>/dev/null && \
        echo "✅ Redis RDB 快照已保存" || \
        echo "⚠️  Redis RDB 文件不存在 (可能未触发过持久化)"
    # 复制 AOF 文件
    docker cp alphacore_redis:/data/appendonly.aof "${BACKUP_PATH}/redis_appendonly.aof" 2>/dev/null && \
        echo "✅ Redis AOF 日志已保存" || \
        echo "⚠️  Redis AOF 文件不存在"
else
    echo "⚠️  Redis 容器未运行, 跳过"
fi

# ── 3. 备份关键配置 ──
echo "⏳ [3/4] 备份配置文件..."
cp "${APP_DIR}/.env" "${BACKUP_PATH}/.env" 2>/dev/null && \
    echo "✅ .env 已保存" || echo "⚠️  .env 不存在"
cp "${APP_DIR}/docker-compose.yml" "${BACKUP_PATH}/docker-compose.yml"
cp "${APP_DIR}/Dockerfile" "${BACKUP_PATH}/Dockerfile"

# 记录当前 Git 版本号 (方便追溯)
cd "${APP_DIR}"
git rev-parse HEAD > "${BACKUP_PATH}/git_commit.txt" 2>/dev/null
git log -1 --format="%h %s (%ci)" >> "${BACKUP_PATH}/git_commit.txt" 2>/dev/null
echo "✅ Git commit: $(cat ${BACKUP_PATH}/git_commit.txt | head -1)"

# 记录系统状态快照
docker ps --format "{{.Names}}\t{{.Status}}\t{{.Image}}" > "${BACKUP_PATH}/docker_status.txt"
curl -s http://localhost:8000/health > "${BACKUP_PATH}/health_snapshot.json" 2>/dev/null || echo "{}" > "${BACKUP_PATH}/health_snapshot.json"
echo "✅ 系统状态快照已保存"

# ── 4. 压缩打包 ──
echo "⏳ [4/4] 压缩打包..."
cd "${BACKUP_DIR}"
tar -czf "${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}/"
rm -rf "${BACKUP_PATH}"
ARCHIVE_SIZE=$(du -sh "${BACKUP_NAME}.tar.gz" | awk '{print $1}')
echo "✅ 压缩完成: ${BACKUP_NAME}.tar.gz (${ARCHIVE_SIZE})"

# ── 5. 清理过期备份 ──
echo ""
echo "⏳ 清理 ${KEEP_DAYS} 天前的备份..."
DELETED=$(find "${BACKUP_DIR}" -name "alphacore_*.tar.gz" -mtime +${KEEP_DAYS} -print -delete | wc -l)
if [ "${DELETED}" -gt 0 ]; then
    echo "🗑️  已清理 ${DELETED} 个过期备份"
else
    echo "✅ 无过期备份需清理"
fi

# ── 统计 ──
TOTAL_BACKUPS=$(ls -1 "${BACKUP_DIR}"/alphacore_*.tar.gz 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | awk '{print $1}')

echo ""
echo "════════════════ 备份完成 ════════════════"
echo "  📦 文件: ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
echo "  📊 大小: ${ARCHIVE_SIZE}"
echo "  📁 累计: ${TOTAL_BACKUPS} 个备份, 共 ${TOTAL_SIZE}"
echo "  🕐 保留: 最近 ${KEEP_DAYS} 天"
echo "═══════════════════════════════════════════"
echo ""
