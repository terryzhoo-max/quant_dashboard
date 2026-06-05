"""
AlphaCore 统一 API 响应包装
===========================
所有 API 端点使用 R.ok() / R.error() 返回标准化响应，
确保前端拿到一致的 JSON 结构。
"""

from version import VERSION_SHORT

VERSION = VERSION_SHORT


def ok(data=None, message="success"):
    """成功响应"""
    resp = {
        "status": "success",
        "message": message,
        "version": VERSION,
    }
    if data is not None:
        resp["data"] = data
    return resp


def error(message: str, code: str = "ERR_UNKNOWN", data=None):
    """错误响应"""
    resp = {
        "status": "error",
        "code": code,
        "message": message,
        "version": VERSION,
    }
    if data is not None:
        resp["data"] = data
    return resp
