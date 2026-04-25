"""
AlphaCore · API Key 认证中间件
================================
Batch 6 安全加固: 保护所有写入操作 (POST/PUT/DELETE)

规则:
  - GET/HEAD/OPTIONS 请求: 免认证 (仪表盘只读)
  - POST/PUT/DELETE 请求: 必须携带 X-API-Key header
  - /health, /docs, /openapi.json: 始终免认证
  - API Key 从环境变量 API_SECRET_KEY 读取

用法:
    from services.auth_middleware import ApiKeyMiddleware
    app.add_middleware(ApiKeyMiddleware)
"""

import os
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from services.logger import get_logger

logger = get_logger("auth")

# 从环境变量读取 API Key (生产环境必须设置)
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

# 始终免认证的路径 (精确匹配)
_PUBLIC_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}

# 始终免认证的路径前缀
_PUBLIC_PREFIXES = (
    "/docs",
    "/redoc",
)

# 免认证的 HTTP 方法 (只读操作)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """
    API Key 认证中间件

    仅保护写入操作 (POST/PUT/DELETE)。
    GET 请求保持免认证，确保仪表盘正常访问。
    """

    async def dispatch(self, request: Request, call_next):
        # 1. 跳过安全方法 (GET/HEAD/OPTIONS)
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        # 2. 跳过公开路径
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)

        # 3. 检查 API Key 是否已配置
        if not API_SECRET_KEY:
            # 未配置 API Key 时，记录警告但放行 (开发环境兼容)
            logger.warning(
                f"API_SECRET_KEY 未设置! 写入操作 {request.method} {path} 未经认证放行。"
                "请在 .env 中配置 API_SECRET_KEY。"
            )
            return await call_next(request)

        # 4. 校验 X-API-Key header
        provided_key = request.headers.get("X-API-Key", "")
        if not provided_key:
            logger.warning(f"拒绝未认证请求: {request.method} {path} (缺少 X-API-Key)")
            return JSONResponse(
                status_code=401,
                content={
                    "status": "unauthorized",
                    "message": "缺少 X-API-Key 请求头。请在 header 中携带有效的 API Key。",
                },
            )

        # 使用 secrets.compare_digest 防止时序攻击
        if not secrets.compare_digest(provided_key, API_SECRET_KEY):
            logger.warning(f"拒绝无效 API Key: {request.method} {path}")
            return JSONResponse(
                status_code=403,
                content={
                    "status": "forbidden",
                    "message": "API Key 无效。",
                },
            )

        # 5. 认证通过
        return await call_next(request)


def generate_api_key(length: int = 48) -> str:
    """生成一个安全的随机 API Key (供首次配置使用)"""
    return secrets.token_urlsafe(length)
