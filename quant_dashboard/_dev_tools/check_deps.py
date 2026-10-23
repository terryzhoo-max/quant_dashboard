"""启动器依赖检查 (2026-10-23).

原 启动服务器.bat 为 18 个依赖各起一个 python 进程并真实 import (akshare/sklearn/yfinance
等重型库), 单此一步耗时约 30~60 秒. 这里用 importlib.util.find_spec 只定位、不执行导入,
一个进程 <1 秒完成. 输出缺失包的 pip 名 (空格分隔), 无缺失则输出空行.
"""
import importlib.util

MODS = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "pandas": "pandas", "numpy": "numpy",
    "pyarrow": "pyarrow", "simplejson": "simplejson", "tushare": "tushare",
    "multipart": "python-multipart", "scipy": "scipy", "requests": "requests",
    "dotenv": "python-dotenv", "fredapi": "fredapi", "redis": "redis",
    "apscheduler": "apscheduler", "sklearn": "scikit-learn", "yfinance": "yfinance",
    "akshare": "akshare", "httpx": "httpx", "xlrd": "xlrd", "openpyxl": "openpyxl",
}

missing = []
for mod, pip_name in MODS.items():
    try:
        if importlib.util.find_spec(mod) is None:
            missing.append(pip_name)
    except Exception:
        missing.append(pip_name)
print(" ".join(missing))
