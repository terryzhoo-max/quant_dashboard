# AlphaCore 服务器运维手册

> 基于阿里云 ECS (40G 系统盘) + Docker Compose 部署方案  
> 最后更新: 2026-05-23 · 基于实际生产排障经验编写

---

## 1. 服务器架构

```
┌──────────────── 阿里云 ECS (40G 系统盘) ────────────────┐
│                                                          │
│  Docker Compose                                          │
│  ┌──────────────────────┐  ┌────────────────────────┐    │
│  │  quant_dashboard_app │  │   alphacore_redis      │    │
│  │  Python 3.12-slim    │  │   Redis 7-alpine       │    │
│  │  FastAPI + Uvicorn   │  │   maxmemory 256mb      │    │
│  │  Port: 8000          │  │   AOF + RDB 持久化     │    │
│  └──────────┬───────────┘  └────────────────────────┘    │
│             │                                            │
│  ┌──────────▼───────────────────────────────────────┐    │
│  │  ./data_lake:/app/data_lake (Volume 挂载)         │    │
│  │  daily_prices/*.parquet  (~55 ETF, ~7 MB)         │    │
│  │  financials/*.parquet    (~30 股票, ~2 MB)         │    │
│  │  erp_*.parquet / aiae_*.json / gem_*.json          │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  Cron Jobs:                                              │
│  ├─ 每天 03:00  备份 (backup.sh)                         │
│  ├─ 每周日 03:00  Docker 清理 + 日志清理                  │
│  └─ 每天 17:15  acme.sh SSL 续期                         │
└──────────────────────────────────────────────────────────┘
```

### 关键路径

| 路径 | 内容 |
|------|------|
| `/root/quant_dashboard/` | Git 仓库根目录 |
| `/root/quant_dashboard/quant_dashboard/` | 应用代码 + Dockerfile + docker-compose.yml |
| `/root/quant_dashboard/quant_dashboard/data_lake/` | 运行时数据 (Volume 挂载, 不入镜像) |
| `/root/quant_dashboard/quant_dashboard/.env` | 环境变量 (API Token, 严禁入库) |
| `/root/backups/` | 自动备份存储目录 |
| `/etc/docker/daemon.json` | Docker 守护进程配置 (DNS + 日志限制) |

---

## 2. 首次部署

### 2.1 前置配置 (只需执行一次)

```bash
# Docker daemon 配置: DNS 解析 + 日志轮转
cat > /etc/docker/daemon.json << 'EOF'
{
  "dns": ["223.5.5.5", "8.8.8.8"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
systemctl restart docker
```

> **重要**: `log-opts` 限制每个容器最多 3 个日志文件, 每个 10MB, 防止日志撑爆磁盘。

### 2.2 部署流程

```bash
cd /root/quant_dashboard/quant_dashboard

# 确认 .env 存在
cat .env

# 构建镜像 (必须 --network=host, 见"已知问题"章节)
docker build --network=host -t quant_dashboard-quant_dashboard .

# 启动服务
docker compose up -d

# 验证
docker ps
curl -s http://localhost:8000/health | python3 -m json.tool
```

### 2.3 注册定时任务

```bash
# 自动备份 (每天 03:00) + Docker 清理 (每周日 03:00)
(crontab -l 2>/dev/null; \
 echo "0 3 * * * bash /root/quant_dashboard/backup.sh >> /root/backups/backup.log 2>&1"; \
 echo "0 3 * * 0 docker system prune -f --filter 'until=72h' && journalctl --vacuum-size=50M" \
) | crontab -

# 验证
crontab -l
```

---

## 3. 日常更新部署

### 3.1 标准流程 (推荐)

```bash
# Step 1: 拉取代码
cd /root/quant_dashboard
git stash --include-untracked -q 2>/dev/null || true
git pull
git stash drop -q 2>/dev/null || true

# Step 2: 构建镜像
cd /root/quant_dashboard/quant_dashboard
docker build --network=host -t quant_dashboard-quant_dashboard .

# Step 3: 重启容器
docker rm -f quant_dashboard_app
docker compose up -d

# Step 4: 验证
sleep 10
curl -s http://localhost:8000/health | python3 -m json.tool
```

### 3.2 一键脚本

```bash
bash /root/quant_dashboard/quant_dashboard/update.sh
```

> **警告**: 不要用 `docker compose up -d --build`，  
> 其 BuildKit 网络隔离会导致构建时 DNS 超时。  
> 必须用 `docker build --network=host` 单独构建。

---

## 4. 磁盘清理

### 4.1 诊断流程

```bash
# 全盘概览
df -h /

# 各目录占用 Top 20
sudo du -xh --max-depth=2 / 2>/dev/null | sort -rh | head -20

# Docker 专项
docker system df
```

### 4.2 清理优先级

#### P0: Docker 清理 (通常释放 5-30 GiB)

> 40G 系统盘 + Docker 部署, Docker 镜像/构建缓存是最大空间杀手。
> 每次 docker build 产生的中间层会持续累积。

```bash
# 查看 Docker 占用详情
docker system df -v

# 删除所有未使用的镜像、停止的容器、构建缓存
docker system prune -a -f
docker builder prune -a -f

# 重新构建应用镜像
cd /root/quant_dashboard/quant_dashboard
docker build --network=host -t quant_dashboard-quant_dashboard .
docker rm -f quant_dashboard_app
docker compose up -d
```

#### P1: 系统清理 (通常释放 1-3 GiB)

```bash
sudo apt clean && sudo apt autoremove -y
sudo journalctl --vacuum-size=50M
sudo find /var/log -name "*.gz" -delete
sudo find /var/log -name "*.1" -delete
sudo truncate -s 0 /var/log/syslog
sudo truncate -s 0 /var/log/kern.log
pip cache purge 2>/dev/null
```

#### P2: data_lake 清理 (通常释放 0.5-2 GiB)

```bash
cd /root/quant_dashboard/quant_dashboard
du -sh data_lake/ data_lake/daily_prices/ data_lake/financials/

# 安全删除: 回测数据 + 财务缓存 + GEM 重复缓存
rm -f data_lake/backtest_gem_*.parquet
rm -rf data_lake/financials/
rm -f data_lake/daily_prices/gem_*.parquet
```

#### P3: 备份清理

```bash
du -sh /root/backups/
find /root/backups/ -name "alphacore_*.tar.gz" -mtime +7 -delete
```

#### P4: Redis AOF 瘦身

```bash
docker exec alphacore_redis redis-cli BGREWRITEAOF
```

---

## 5. 常见故障排查

### 5.1 磁盘满 (Use% > 90%)

```bash
df -h / && docker system df
docker system prune -a -f && docker builder prune -a -f
sudo apt clean && sudo journalctl --vacuum-size=50M

# 然后重建服务
cd /root/quant_dashboard/quant_dashboard
docker build --network=host -t quant_dashboard-quant_dashboard .
docker rm -f quant_dashboard_app && docker compose up -d
```

### 5.2 Docker 构建 DNS 超时

```
Failed to establish a new connection: [Errno -3] Temporary failure in name resolution
```

原因: BuildKit bridge 网络隔离。  
解决: `docker build --network=host -t quant_dashboard-quant_dashboard .`

### 5.3 容器名冲突

```bash
docker rm -f quant_dashboard_app && docker compose up -d
```

### 5.4 服务无响应

```bash
docker ps -a
docker logs --tail 50 quant_dashboard_app
ss -tlnp | grep 8000
docker compose restart
```

---

## 6. 备份与恢复

### 手动备份

```bash
bash /root/quant_dashboard/backup.sh
```

### 恢复流程

```bash
cd /root/backups/quant_dashboard
tar -xzf alphacore_20260523_030000.tar.gz
cp -r alphacore_20260523_030000/data_lake/* /root/quant_dashboard/quant_dashboard/data_lake/
docker cp alphacore_20260523_030000/redis_dump.rdb alphacore_redis:/data/dump.rdb
docker compose restart
```

---

## 7. 40G 系统盘容量预算

| 组件 | 占用 | 说明 |
|------|------|------|
| Ubuntu 系统 | ~3 GB | 基础 OS |
| Docker Engine | ~0.5 GB | 守护进程 |
| 应用镜像 (python:3.12-slim + pip 依赖) | ~1 GB | 单一活跃镜像 |
| Redis 镜像 (7-alpine) | ~40 MB | |
| data_lake/ | ~15 MB | Parquet + JSON 缓存 |
| Redis 数据 (Volume) | ~10 MB | RDB + AOF |
| 系统日志 | ≤50 MB | journalctl 限制 |
| 容器日志 | ≤60 MB | daemon.json 限制 (2容器 × 30MB) |
| 备份 (30天) | ~300 MB | 每日压缩包 ~10MB |
| **正常总计** | **~5 GB** | **剩余 ~35 GB 余量** |

> 空间杀手: 每次 `docker build` 不清理旧镜像, 一个应用镜像 ~700MB,  
> 构建 50 次就吃掉 35GB。每周自动清理 cron 是必须的防线。

---

## 快速命令速查

```bash
# ── 部署 ──
cd /root/quant_dashboard/quant_dashboard
docker build --network=host -t quant_dashboard-quant_dashboard .
docker rm -f quant_dashboard_app && docker compose up -d

# ── 状态 ──
docker ps && curl -s localhost:8000/health | python3 -m json.tool

# ── 日志 ──
docker logs --tail 20 quant_dashboard_app

# ── 磁盘 ──
df -h / && docker system df

# ── 清理 ──
docker system prune -a -f && docker builder prune -a -f

# ── 备份 ──
bash /root/quant_dashboard/backup.sh
```
