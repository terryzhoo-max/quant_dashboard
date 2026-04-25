FROM python:3.12-slim

# 设置时区为亚洲/上海，对量化数据的日期对齐极其重要
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 设置工作目录
WORKDIR /app

# 优先安装依赖，利用 Docker 缓存层加速后续构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# 复制代码
COPY . .

# 暴露仪表盘端口
EXPOSE 8000

# 健康检查 (指向 Batch 3 新增的 /health 端点)
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 启动后端服务 (单 Worker: 2GB 内存服务器限制)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
