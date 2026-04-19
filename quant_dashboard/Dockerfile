FROM python:3.10-slim

# 设置时区为亚洲/上海，对量化数据的日期对齐极其重要
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 设置工作目录
WORKDIR /app

# 优先安装依赖，利用 Docker 缓存层加速后续构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制代码
COPY . .

# 暴露仪表盘端口
EXPOSE 8000

# P2-3: 健康检查 (每60秒检测一次, 3次失败则标记 unhealthy)
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/dashboard-data')" || exit 1

# 启动后端服务 (生产模式: 2 workers)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
