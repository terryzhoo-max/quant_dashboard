"""
⚠️ 兼容 shim — 此文件代理至 engines/dual_momentum_engine.py
=======================================================
保留此 shim 确保 routers/ 等模块的 import 路径兼容。
"""
from engines.dual_momentum_engine import *  # noqa: F401,F403
