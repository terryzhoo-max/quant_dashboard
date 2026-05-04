# AlphaCore 量化终端 · 部署与运维手册

> **版本**: V21.2 · 最后更新: 2026-05-04
> **服务器**: 阿里云轻量应用服务器 · `iZrj9hm8oe9aow6jr63lngZ`
> **技术栈**: Python 3.12 + FastAPI + Redis + Docker + SQLite

---

## 目录

1. [系统架构总览](#1-系统架构总览)
2. [目录结构说明](#2-目录结构说明)
3. [首次部署 (从零开始)](#3-首次部署)
4. [日常更新部署](#4-日常更新部署)
5. [环境变量配置](#5-环境变量配置)
6. [定时任务一览](#6-定时任务一览)
7. [备份与恢复](#7-备份与恢复)
8. [监控与健康检查](#8-监控与健康检查)
9. [常用运维命令](#9-常用运维命令)
10. [故障排除手册](#10-故障排除手册)
11. [安全注意事项](#11-安全注意事项)

---

## 1. 系统架构总览

```
┌──────────────────────────────────────────────────┐
│                   公网访问                        │
│           http://<服务器IP>:8000                  │
└──────────────────┬───────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────┐
│  Docker Network: quant_dashboard_default         │
│                                                  │
│  ┌────────────────────┐   ┌──────────────────┐   │
│  │ quant_dashboard_app│   │  alphacore_redis  │   │
│  │ (FastAPI + Uvicorn)│◀──│  (Redis 7 Alpine) │   │
│  │ Port: 8000         │   │  256MB LRU        │   │
│  │ Worker: 1          │   │  RDB + AOF 持久化  │   │
│  └────────┬───────────┘   └──────────────────┘   │
│           │                                      │
│  ┌────────▼───────────┐                          │
│  │    data_lake/      │  ← 宿主机 Volume 挂载    │
│  │  (Parquet 缓存)    │    容器销毁数据不丢失      │
│  └────────────────────┘                          │
└──────────────────────────────────────────────────┘
```

### 关键组件

| 组件 | 说明 | 端口 |
|:-----|:-----|:-----|
| **FastAPI App** | 量化终端主服务 (1 Worker, 2GB 内存限制) | 8000 |
| **Redis 7** | L1 缓存层 (256MB LRU, RDB 持久化) | 6379 (内部) |
| **SQLite** | 交易记录 + AIAE 历史 + ERP 日志 + 信号预警 (WAL 模式) | 文件存储 |
| **APScheduler** | 10 个定时任务 (盘中/收盘/早间/FRED/AIAE/波段/日报/预警) | 内嵌 |
| **Tushare Pro** | A股数据源 (有频率限制: 20次/分钟) | 外部 API |
| **FRED API** | 美国经济数据 (利率/VIX) | 外部 API |
| **Finnhub** | 美股/日股实时数据 | 外部 API |
| **Server酱** | 微信推送通道 (V21.2 信号预警) | 外部 API |
| **QQ SMTP** | 邮件推送通道 (V21.2 信号预警) | 外部 SMTP |

---

## 2. 目录结构说明

### ⚠️ 重要: 嵌套目录问题

由于 Git 仓库结构，服务器上存在**目录嵌套**：

```
/root/quant_dashboard/              ← Git 仓库根目录
├── quant_dashboard/                ← 实际代码目录
│   ├── main.py                     ← 应用入口
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── .env                        ← 环境变量 (不入 Git!)
│   ├── backup.sh
│   ├── deploy.sh
│   ├── audit.html / index.html     ← 前端页面
│   ├── static/                     ← JS/CSS/图片
│   ├── routers/                    ← API 路由
│   ├── services/                   ← 缓存/日志/认证
│   ├── data_lake/                  ← Parquet 数据 (Volume 挂载)
│   └── ...
├── backup.sh → (软链接)            ← 指向 quant_dashboard/backup.sh
├── Dockerfile → (软链接)            ← 指向 quant_dashboard/Dockerfile
└── docker-compose.yml → (软链接)    ← 指向 quant_dashboard/docker-compose.yml
```

**关键路径映射**：

| 用途 | 路径 |
|:-----|:-----|
| Git 操作 | `cd /root/quant_dashboard` |
| Docker 构建 | `cd /root/quant_dashboard/quant_dashboard` |
| 应用代码 | `/root/quant_dashboard/quant_dashboard/*.py` |
| 环境变量 | `/root/quant_dashboard/quant_dashboard/.env` |
| 数据文件 | `/root/quant_dashboard/quant_dashboard/data_lake/` |
| 备份存储 | `/root/backups/quant_dashboard/` |

---

## 3. 首次部署

### 3.1 前置条件

```bash
# 确保 Docker 已安装
docker --version     # 需要 20.10+
docker-compose --version  # 如果版本 < 2.0, 用 docker run 替代 (见下方)

# 确保 Git 已安装
git --version
```

### 3.2 克隆仓库

```bash
cd /root
git clone https://github.com/terryzhoo-max/quant_dashboard.git
cd quant_dashboard
```

### 3.3 创建环境变量

```bash
cat > /root/quant_dashboard/quant_dashboard/.env << 'EOF'
# AlphaCore 环境变量 (此文件不入 Git)
TUSHARE_TOKEN=<你的 Tushare Token>
FRED_API_KEY=<你的 FRED API Key>

# API Key 认证 (所有 POST/PUT/DELETE 请求必须携带 X-API-Key)
API_SECRET_KEY=<生成一个 64 位随机字符串>

# CORS 白名单
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
EOF
```

> 💡 **生成随机 API Key**: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

### 3.4 建立软链接

```bash
cd /root/quant_dashboard
ln -sf /root/quant_dashboard/quant_dashboard/Dockerfile ./Dockerfile
ln -sf /root/quant_dashboard/quant_dashboard/docker-compose.yml ./docker-compose.yml
ln -sf /root/quant_dashboard/quant_dashboard/backup.sh ./backup.sh
```

### 3.5 启动服务

#### 方式 A: docker-compose (推荐, 需要 v2.0+)

```bash
cd /root/quant_dashboard/quant_dashboard
docker-compose up -d --build
```

#### 方式 B: docker run (兼容旧版 docker-compose 1.29)

如果遇到 `ContainerConfig` 错误，使用原生 Docker 命令：

```bash
# 1. 构建镜像
cd /root/quant_dashboard/quant_dashboard
DOCKER_BUILDKIT=0 docker build --network host -t quant_dashboard_quant_dashboard .

# 2. 启动 Redis
docker run -d \
  --name alphacore_redis \
  --restart unless-stopped \
  --network quant_dashboard_default \
  redis:7-alpine redis-server \
    --maxmemory 256mb \
    --maxmemory-policy allkeys-lru \
    --appendonly yes \
    --save 900 1 --save 300 10

# 3. 等待 Redis 就绪
sleep 3

# 4. 启动 App
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
```

> ⚠️ **首次创建网络**: 如果 `quant_dashboard_default` 不存在:
> `docker network create quant_dashboard_default`

### 3.6 验证部署

```bash
# 等待 30 秒预热
sleep 30

# 健康检查
curl -s http://localhost:8000/health | python3 -m json.tool

# 期望输出包含:
#   "status": "ok"
#   "cache_backend": "redis"
#   "scheduler": {"running": true, "job_count": 7}
```

### 3.7 注册定时备份

```bash
# 编辑 crontab
crontab -e

# 添加这一行 (每天凌晨 3:00 自动备份):
0 3 * * * bash /root/quant_dashboard/backup.sh >> /root/backups/backup.log 2>&1
```

---

## 4. 日常更新部署

### 4.1 标准更新流程

在**本地开发机**推送代码后，在服务器上执行：

```bash
# ── Step 1: 拉取最新代码 ──
cd /root/quant_dashboard
git pull

# ── Step 2: 重建镜像 ──
cd /root/quant_dashboard/quant_dashboard
DOCKER_BUILDKIT=0 docker build --no-cache --network host \
  -t quant_dashboard_quant_dashboard .

# ── Step 3: 重启容器 ──
docker rm -f quant_dashboard_app 2>/dev/null
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

# ── Step 4: 验证 ──
sleep 15 && curl -s http://localhost:8000/health | python3 -m json.tool
```

### 4.2 仅前端更新 (无需重建镜像)

如果只改了 HTML/JS/CSS，可以直接复制文件到容器内：

```bash
# 拉取代码
cd /root/quant_dashboard && git pull

# 热更新前端文件到运行中的容器
docker cp quant_dashboard/audit.html quant_dashboard_app:/app/audit.html
docker cp quant_dashboard/static/ quant_dashboard_app:/app/static/

# 无需重启! 刷新浏览器即可看到更新
```

### 4.3 仅依赖更新 (requirements.txt 变更)

```bash
# 必须重建镜像
cd /root/quant_dashboard/quant_dashboard
DOCKER_BUILDKIT=0 docker build --no-cache --network host \
  -t quant_dashboard_quant_dashboard .

# 然后按 4.1 的 Step 3-4 重启
```

---

## 5. 环境变量配置

文件位置: `/root/quant_dashboard/quant_dashboard/.env`

```ini
# ── 数据源 API ──
TUSHARE_TOKEN=<Tushare Pro Token>       # 必填! A股数据源
FRED_API_KEY=<FRED API Key>             # 必填! 美国经济数据

# ── 安全认证 ──
API_SECRET_KEY=<64位随机字符串>           # 必填! 所有写入 API 的认证密钥

# ── 跨域配置 ──
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000

# ── Redis (由 docker run -e 注入, 不写在 .env 中) ──
# REDIS_HOST=redis     ← 通过 docker run -e 传入
# REDIS_PORT=6379      ← 通过 docker run -e 传入
```

> ⚠️ **此文件绝对不能提交到 Git!** 已在 `.gitignore` 中排除。

---

## 6. 定时任务一览

### 6.1 系统级 Cron (crontab)

| 时间 | 任务 | 日志 |
|:-----|:-----|:-----|
| 每天 03:00 | `backup.sh` 自动备份 | `/root/backups/backup.log` |
| 每天 17:15 | ACME SSL 证书续签 | `/dev/null` |

### 6.2 应用内 APScheduler (容器内自动运行)

| ID | 触发时间 | 功能 |
|:---|:---------|:-----|
| `hot_data` | 每 2 分钟 | 盘中热点数据刷新 |
| `daily_warmup` | 周一至五 15:35 | 收盘预热 (ERP+AIAE+因子+Dashboard+组合快照+信号扫描) |
| `morning_warmup` | 周一至五 08:30 | 盘前数据补偿 + 信号扫描 |
| `fred_daily` | 周一至五 18:30 | FRED 利率数据刷新 |
| `us_aiae` | 周二至六 06:30 | 美股 AIAE 预热 + 全球对比更新 |
| `jp_aiae` | 周一至五 15:30 | 日股 AIAE 预热 + 全球对比更新 |
| `aaii_crawl` | 每周五 09:00 | AAII 情绪指数爬取 |
| `swing_guard` | 周一至五 15:40 | 波段守卫 7 大 ETF 信号刷新 |
| `daily_report` | 周一至五 16:35 | V21.0 投委会日报自动生成 |
| `alert_scan` | 每 10 分钟 | V21.2 信号预警扫描 (JCS/VIX 三通道推送) |

> 💡 查看调度器状态: `curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['scheduler'], indent=2))"`

---

## 7. 备份与恢复

### 7.1 备份内容

每次备份包含：

| 内容 | 说明 |
|:-----|:-----|
| `data_lake/` | 所有 Parquet 缓存 (ERP/PE/Yield/日线等) |
| `redis_dump.rdb` | Redis 内存快照 |
| `.env` | 环境变量 (含 API Keys) |
| `docker-compose.yml` | 部署配置 |
| `Dockerfile` | 镜像定义 |
| `git_commit.txt` | 当前代码版本号 |
| `docker_status.txt` | 容器运行状态 |
| `health_snapshot.json` | 应用健康快照 |

### 7.2 手动执行备份

```bash
bash /root/quant_dashboard/backup.sh
```

### 7.3 查看备份历史

```bash
ls -lh /root/backups/quant_dashboard/
tail -50 /root/backups/backup.log
```

### 7.4 从备份恢复

```bash
# 1. 解压目标备份
cd /root/backups/quant_dashboard
tar -xzf alphacore_20260425_220824.tar.gz

# 2. 恢复 data_lake
cp -r alphacore_20260425_220824/data_lake/* \
  /root/quant_dashboard/quant_dashboard/data_lake/

# 3. 恢复 .env
cp alphacore_20260425_220824/.env \
  /root/quant_dashboard/quant_dashboard/.env

# 4. 恢复 Redis 数据
docker cp alphacore_20260425_220824/redis_dump.rdb \
  alphacore_redis:/data/dump.rdb
docker restart alphacore_redis

# 5. 回退代码到备份时的版本
cd /root/quant_dashboard
COMMIT=$(head -1 /root/backups/quant_dashboard/alphacore_20260425_220824/git_commit.txt)
git reset --hard $COMMIT

# 6. 重建并重启
cd /root/quant_dashboard/quant_dashboard
DOCKER_BUILDKIT=0 docker build --no-cache --network host \
  -t quant_dashboard_quant_dashboard .
docker rm -f quant_dashboard_app
# (然后执行 4.1 Step 3 的 docker run 命令)
```

### 7.5 备份保留策略

- **保留天数**: 30 天
- **自动清理**: `backup.sh` 会自动删除 30 天前的 `.tar.gz`
- **当前大小**: 约 3-5 MB / 次

---

## 8. 监控与健康检查

### 8.1 健康检查 API

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

**关键字段解读**:

| 字段 | 正常值 | 异常处理 |
|:-----|:-------|:---------|
| `status` | `"ok"` | 如果是 `"starting"` 等待 1 分钟 |
| `cache_backend` | `"redis"` | 如果是 `"memory"` 检查 Redis |
| `scheduler.running` | `true` | 如果 `false` 需重启容器 |
| `scheduler.job_count` | `7` | 少于 7 说明有任务注册失败 |
| `database.backend` | `"SQLite (WAL)"` | WAL 模式确保读写并发 |

### 8.2 Docker 容器监控

```bash
# 容器状态
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# App 实时日志
docker logs -f --tail 50 quant_dashboard_app

# Redis 内存使用
docker exec alphacore_redis redis-cli info memory | grep used_memory_human

# Redis 缓存 Key 数量
docker exec alphacore_redis redis-cli dbsize
```

### 8.3 资源监控

```bash
# 容器资源占用
docker stats --no-stream

# 磁盘使用
df -h /
du -sh /root/quant_dashboard/quant_dashboard/data_lake/
du -sh /root/backups/
```

---

## 9. 常用运维命令

### 9.1 服务控制

```bash
# 查看容器状态
docker ps

# 重启 App (不重建镜像)
docker restart quant_dashboard_app

# 停止 App
docker stop quant_dashboard_app

# 启动已停止的 App
docker start quant_dashboard_app

# 重启 Redis
docker restart alphacore_redis

# 查看 App 日志 (最近 100 行)
docker logs --tail 100 quant_dashboard_app

# 实时跟踪日志
docker logs -f quant_dashboard_app

# 进入容器调试
docker exec -it quant_dashboard_app bash
```

### 9.2 Redis 操作

```bash
# 进入 Redis CLI
docker exec -it alphacore_redis redis-cli

# 查看所有 Key
docker exec alphacore_redis redis-cli keys '*'

# 清空缓存 (强制重新预热)
docker exec alphacore_redis redis-cli flushall

# 手动触发 RDB 持久化
docker exec alphacore_redis redis-cli bgsave
```

### 9.3 数据管理

```bash
# 查看 data_lake 大小
du -sh /root/quant_dashboard/quant_dashboard/data_lake/*

# 查看 ERP 文件新鲜度
ls -lt /root/quant_dashboard/quant_dashboard/data_lake/erp_*.parquet | head -10

# 查看日线数据文件数量
ls /root/quant_dashboard/quant_dashboard/data_lake/daily_prices/ | wc -l
```

### 9.4 Git 操作

```bash
# 查看当前版本
cd /root/quant_dashboard && git log --oneline -5

# 强制同步到远程最新
git fetch origin && git reset --hard origin/main
```

---

## 10. 故障排除手册

### 10.1 容器启动失败

```bash
# 查看错误日志
docker logs quant_dashboard_app

# 常见原因:
# 1. .env 文件不存在 → 创建 .env (见 §5)
# 2. Redis 未就绪 → docker restart alphacore_redis
# 3. 端口被占用 → lsof -i :8000
```

### 10.2 `ContainerConfig` 错误

**原因**: docker-compose 1.29.2 与新版 Docker Engine 不兼容

**解决**: 放弃 docker-compose, 使用 docker run (见 §3.5 方式 B)

```bash
docker rm -f quant_dashboard_app
# 然后执行 docker run 命令
```

### 10.3 Tushare 频率限制

```
[Retry] _call_pro_yc failed: 访问接口频率超限(20次/分钟)
```

**处理**: 这是正常现象，系统有自动重试机制 (2s → 4s → 8s 指数退避)。预热期间会集中触发，等待 5-10 分钟即可自动恢复。

### 10.4 数据质量审计失败

```bash
# 在浏览器中访问审计页面
http://<服务器IP>:8000/audit.html

# 或通过 API 查看
curl -s http://localhost:8000/audit/ | python3 -m json.tool
```

### 10.5 Redis 连接失败 (降级为内存缓存)

```bash
# 检查 Redis 容器
docker ps | grep redis
docker logs alphacore_redis

# 确认网络连通
docker exec quant_dashboard_app python3 -c "import redis; r=redis.Redis(host='redis'); print(r.ping())"

# 重启 Redis
docker restart alphacore_redis
docker restart quant_dashboard_app
```

### 10.6 git pull 报 "Already up to date" 但代码没更新

**原因**: 本地和服务器使用了不同的 Git 仓库

```bash
# 检查远程地址
git remote -v

# 如果显示的不是你推送的仓库, 修改:
git remote set-url origin https://github.com/terryzhoo-max/quant_dashboard.git
git pull
```

### 10.7 磁盘空间不足

```bash
# 清理 Docker 无用镜像
docker image prune -a

# 清理旧备份
find /root/backups -name "*.tar.gz" -mtime +15 -delete

# 查看大文件
du -sh /root/quant_dashboard/quant_dashboard/data_lake/*
```

---

## 11. 安全注意事项

### 11.1 已实施的安全措施

| 措施 | 说明 |
|:-----|:-----|
| **API Key 认证** | 所有 POST/PUT/DELETE 必须携带 `X-API-Key` Header |
| **预警端点白名单** | `/api/v1/decision/alerts` 免认证 (前端 ack 操作) |
| **CORS 白名单** | 仅允许配置的域名跨域访问 |
| **GZip 压缩** | 减少传输体积，提高响应速度 |
| **静态文件拦截** | `.py`/`.env` 等敏感文件返回 404 |
| **DNS 配置** | 容器使用 8.8.8.8 + 223.5.5.5 避免 DNS 污染 |
| **推送凭据隔离** | Server酱 SendKey + SMTP 密码存于 `config/alert_config.json` |

### 11.2 严禁入库的文件

- `.env` — 包含所有 API Token
- `nginx/ssl/` — SSL 证书私钥
- `data_lake/` — 交易数据

### 11.3 API Key 使用示例

```bash
# 无 Key → 401 拒绝
curl -X POST http://localhost:8000/api/v1/sync/industry

# 带 Key → 正常执行
curl -X POST http://localhost:8000/api/v1/sync/industry \
  -H "X-API-Key: <你的 API_SECRET_KEY>"
```

---

## 附录: 一键更新脚本

将以下内容保存为 `/root/update.sh`，以后更新只需执行 `bash /root/update.sh`:

```bash
#!/bin/bash
set -e
echo "═══ AlphaCore 一键更新 ═══"

# 拉取代码
cd /root/quant_dashboard && git pull
echo "✅ 代码已更新: $(git log --oneline -1)"

# 重建镜像
cd /root/quant_dashboard/quant_dashboard
DOCKER_BUILDKIT=0 docker build --no-cache --network host \
  -t quant_dashboard_quant_dashboard .
echo "✅ 镜像已重建"

# 重启容器
docker rm -f quant_dashboard_app 2>/dev/null
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

# 验证
sleep 15
STATUS=$(curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','FAIL'))" 2>/dev/null)
if [ "$STATUS" = "ok" ]; then
  echo "✅ 健康检查通过"
else
  echo "⚠️  状态: $STATUS (可能还在预热, 请稍等)"
fi

echo "═══ 更新完成 ═══"
```

```bash
# 创建并授权
chmod +x /root/update.sh
```

---

## 12. V21.0-V21.2 新增功能速查

| 版本 | 功能 | 配置 |
|:-----|:-----|:-----|
| V20.0 | 相关性热力图 + MCTR 风险贡献 | 自动 (风险矩阵 Tab) |
| V21.0 | 投委会日报自动生成 (16:35) | 自动 (APScheduler) |
| V21.2 | 三通道信号预警 (浏览器/微信/邮件) | `config/alert_config.json` |
| V21.2 | 数据新鲜度状态栏 | 自动 (决策中枢标题下方) |
| V21.2 | 启动竞态修复 (ThreadPoolExecutor 分层启动) | 自动 |

### 预警阈值配置

| 规则 | 触发条件 | 级别 | Cooldown |
|:-----|:---------|:-----|:---------|
| JCS 低信心 | JCS < 25 | ⚠️ Warning | 8 小时 |
| VIX 恐慌 | VIX > 30 | 🚨 Warning | 4 小时 |
| VIX 极端 | VIX > 35 | 🛑 Critical | 2 小时 |

### 推送通道配置 (`config/alert_config.json`)

```json
{
  "wechat": { "enabled": true, "send_key": "SCTxxxxx" },
  "email": {
    "enabled": true,
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "sender": "magas@qq.com",
    "password": "<SMTP授权码>",
    "recipients": ["magas@qq.com"]
  }
}
```

---

> 📌 **维护者备忘**: 本手册对应 V21.2。如果架构发生重大变更（如迁移到 K8s、切换数据库等），请同步更新此文档。
