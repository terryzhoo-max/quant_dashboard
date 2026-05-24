# AlphaCore 服务器运维手册

> 基于阿里云 ECS (40G 系统盘) + Docker Compose 部署方案  
> 最后更新: 2026-05-23 · 基于实际生产排障经验编写  
> 当前版本: AlphaCore V26.0.0 · update.sh v3.1

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
| `/root/backups/` | 自动备份 + update.log 更新日志 |
| `/etc/docker/daemon.json` | Docker 守护进程配置 (DNS + 日志限制) |

### 关键脚本

| 脚本 | 版本 | 用途 |
|------|------|------|
| `update.sh` | v3.1 | 一键更新 (拉取→构建→切换→健康检查→回滚) |
| `deploy.sh` | v4.0 | 首次部署 (含 Nginx/SSL/API Key 验证) |
| `backup.sh` | v1.0 | 定时备份 (data_lake + Redis + .env) |

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

### 3.1 一键更新 (推荐)

```bash
cd /root/quant_dashboard/quant_dashboard
bash update.sh
```

update.sh v3.1 自动完成以下全流程:

```
Step 0: 预检 (磁盘≥2GB / Docker运行 / .env存在)
  ↓ 失败 → 立即退出, 无副作用
Step 1: git pull 拉取最新代码
  ↓ 失败 → 自动恢复, 退出
Step 2: docker build --network=host (旧容器继续服务)
  ↓ 失败 → 旧服务不受影响, 退出
Step 3: rm + compose up (最短停机窗口, ~2s)
  ↓ 失败 → 自动回滚到旧镜像
Step 4: 健康检查轮询 (每3s, 最多60s, 必须 status=ok)
  ↓ 失败 → 自动回滚 + 打印容器日志
Step 5: 清理悬空镜像, 输出完整报告
```

**生产级保护特性:**
- 先 build 后切换 (构建失败不影响运行中的服务)
- 自动回滚 (健康检查失败时恢复旧镜像 + 验证回滚结果)
- 并发锁 (防止同时执行多个 update)
- 中断安全 (Ctrl+C 时自动恢复服务)
- 全程日志 (`/root/backups/update.log`)

**实际运行效果 (2026-05-23 验证):**

```
[15:52:32] ⏳ [0/5] 环境预检...
[15:52:32]   ✅ 磁盘: 剩余 30GB
[15:52:32]   ✅ Docker: 运行中
[15:52:32]   ✅ .env: 存在
[15:52:33]   ✅ 代码: 356906c
[15:52:34]   ✅ 镜像构建完成 (1s)
[15:52:36]   ✅ 容器已切换
[15:52:43]   ✅ 健康检查通过 (6s)
[15:52:43] ╔══════════════════════════════════════════════╗
[15:52:43] ║   ✅ 更新成功                                ║
[15:52:43]   📦 版本: AlphaCore V26.0.0
[15:52:43]   🗄️ 缓存: redis
[15:52:43]   ⏱️ 耗时: 11s (构建 1s)
[15:52:43]   💾 磁盘: 剩余 30GB
[15:52:43] ╚══════════════════════════════════════════════╝
```

### 3.2 手动流程 (仅在 update.sh 异常时使用)

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

> **警告**: 不要用 `docker compose up -d --build`，  
> 其 BuildKit 网络隔离会导致构建时 DNS 超时。  
> 必须用 `docker build --network=host` 单独构建。

### 3.3 从本地电脑到服务器的完整流程

```bash
# 本地 (Windows):
cd d:\FIONA\google AI\quant_dashboard
git add -A
git commit -m "update: 功能描述"
git push

# 服务器 (SSH):
cd /root/quant_dashboard/quant_dashboard
bash update.sh
```

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
> **实战案例**: 2026-05-23 发现 59 个废弃镜像占了 34.6 GB, 清理后释放 32 GiB。

```bash
# 查看 Docker 占用详情
docker system df -v

# 删除所有未使用的镜像、停止的容器、构建缓存
docker system prune -a -f
docker builder prune -a -f

# 重新构建应用镜像 + 重启
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

> data_lake/daily_prices/ 中的主缓存文件不建议全部删除。  
> 策略运行时会自动从 Tushare API 重建, 但会消耗 API 调用额度。

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

## 5. 自动化防护

### 已部署的 Cron 任务

```
15 17 * * *   acme.sh SSL 证书自动续期
0  3  * * *   备份 (data_lake + Redis + .env + Git commit)
0  3  * * 0   Docker 清理 (72h 前的废弃资源) + 日志清理
```

### Docker 日志限制 (/etc/docker/daemon.json)

```json
{
  "dns": ["223.5.5.5", "8.8.8.8"],
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
```

每个容器最多 30MB 日志 (3 × 10MB), 自动轮转。

### update.sh 内置防护

| 防护 | 机制 |
|------|------|
| 磁盘预检 | 剩余 <2GB 拒绝更新 |
| 构建失败保护 | 旧容器不动, 安全退出 |
| 健康检查 | 轮询最多 60s, 必须 status=ok |
| 自动回滚 | 失败时恢复旧镜像 + 验证 |
| 并发锁 | PID 锁文件防重复执行 |
| 中断安全 | Ctrl+C 时自动恢复服务 |
| 悬空镜像清理 | 每次部署后自动清理 |

---

## 6. 常见故障排查

### 6.1 磁盘满 (Use% > 90%)

```bash
df -h / && docker system df
docker system prune -a -f && docker builder prune -a -f
sudo apt clean && sudo journalctl --vacuum-size=50M

# 重建服务
cd /root/quant_dashboard/quant_dashboard
bash update.sh
```

### 6.2 Docker 构建 DNS 超时

```
Failed to establish a new connection: [Errno -3] Temporary failure in name resolution
```

原因: BuildKit bridge 网络隔离, 容器内无法解析 DNS。  
解决: `docker build --network=host` (update.sh 已内置)。  
**不要用** `docker compose build` (不支持 --network 参数)。

### 6.3 容器名冲突

```bash
docker rm -f quant_dashboard_app && docker compose up -d
```

### 6.4 服务无响应

```bash
docker ps -a
docker logs --tail 50 quant_dashboard_app
ss -tlnp | grep 8000
docker compose restart
```

### 6.5 update.sh 无输出

原因: Windows 换行符 (CRLF) 导致 bash 解析失败。  
诊断: `file update.sh` — 若显示 "CRLF" 则有问题。  
修复:
```bash
sed -i 's/\r$//' update.sh
bash update.sh
```

### 6.6 update.sh 自动回滚触发

查看更新日志定位失败原因:
```bash
tail -50 /root/backups/update.log
docker logs --tail 100 quant_dashboard_app
```

---

## 7. 备份与恢复

### 自动备份内容 (每天 03:00)

| 项目 | 说明 |
|------|------|
| data_lake/ | Parquet 缓存 + JSON 配置 |
| Redis RDB + AOF | 快照 + 增量日志 |
| .env | 环境变量 (含 API Token) |
| docker-compose.yml | 容器编排配置 |
| git_commit.txt | 代码版本号 |

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

## 8. 40G 系统盘容量预算

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
> 构建 50 次就吃掉 35GB。每周 cron + update.sh 内置清理是双重防线。

---

## 9. 长期建议

### 方案 A: 数据盘分离 (推荐, ¥3/月)

```bash
# 1. 阿里云控制台创建 20G ESSD 云盘, 挂载到 ECS
# 2. 格式化并挂载
mkfs.ext4 /dev/vdb
mkdir -p /data
mount /dev/vdb /data
echo '/dev/vdb /data ext4 defaults 0 2' >> /etc/fstab

# 3. 迁移 data_lake + backups
mv /root/quant_dashboard/quant_dashboard/data_lake /data/data_lake
ln -s /data/data_lake /root/quant_dashboard/quant_dashboard/data_lake
mv /root/backups /data/backups
ln -s /data/backups /root/backups
```

### 方案 B: 系统盘在线扩容

```bash
# 阿里云控制台扩容 40G → 60G 后:
growpart /dev/vda 3
resize2fs /dev/vda3
df -h /
```

---

## 快速命令速查

```bash
# ── 一键更新 (推荐) ──
cd /root/quant_dashboard/quant_dashboard && bash update.sh

# ── 状态检查 ──
docker ps && curl -s localhost:8000/health | python3 -m json.tool

# ── 查看日志 ──
docker logs --tail 20 quant_dashboard_app   # 应用日志
tail -30 /root/backups/update.log           # 更新日志

# ── 磁盘诊断 ──
df -h / && docker system df

# ── 紧急清理 ──
docker system prune -a -f && docker builder prune -a -f

# ── 手动备份 ──
bash /root/quant_dashboard/backup.sh
```
