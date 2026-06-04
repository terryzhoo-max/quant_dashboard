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
_IS_PRODUCTION = os.getenv("ALPHACORE_ENV", "development").lower() in ("production", "prod")

# P1-1: 启动时强制提醒 API Key 未配置风险
if not API_SECRET_KEY:
    _level = "CRITICAL" if _IS_PRODUCTION else "WARNING"
    logger.log(
        50 if _IS_PRODUCTION else 30,
        "⚠️ API_SECRET_KEY 未设置! %s。请在 .env 中配置 API_SECRET_KEY。",
        "生产模式下所有写入操作将被拒绝" if _IS_PRODUCTION else "开发模式下写入操作将免认证放行",
    )

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
    "/api/v1/decision/alerts",      # V21.2: 预警已读操作 (前端用户按钮)
    "/api/v1/decision/simulate",    # V23.0: 情景模拟 (纯数学推演, 无副作用)
    "/api/v1/decision/shock",       # V23.0: 冲击传播 (纯数学推演, 无副作用)
    "/api/v1/decision/param-snapshot",  # V23.0: 参数快照 (用户操作)
    "/api/v1/decision/narrative",   # V8.2: 叙事报告重新生成 (仪表盘按钮)
    "/api/v1/intelligence/scan",    # V8.1: 情报扫描 (仪表盘内置按钮触发)
    "/api/v1/assistant/chat",       # V27.0: AI 助手对话 (前端用户交互, 无副作用)
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
            # P1-1: 生产环境 fail-closed — 拒绝所有未认证写入
            if _IS_PRODUCTION:
                logger.error(
                    "生产模式 API_SECRET_KEY 未配置, 拒绝写入: %s %s",
                    request.method, path,
                )
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "error",
                        "message": "服务未正确配置认证密钥，写入操作不可用。",
                    },
                )
            # 开发模式: 放行但记录警告
            logger.warning(
                "API_SECRET_KEY 未设置! 写入操作 %s %s 未经认证放行 (开发模式)。",
                request.method, path,
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
