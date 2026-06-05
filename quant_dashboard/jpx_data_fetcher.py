# ⚠️ DEPRECATED: 此文件仅为兼容性代理, 请直接 import engines/strategies 子模块.
# 计划在 V27.0 移除. 请更新引用: from data.jpx_data_fetcher import xxx
"""
⚠️ 兼容 shim — 此文件已迁移至 data/jpx_data_fetcher.py
=======================================================
保留此 shim 确保旧 import 路径继续工作。
迁移完成后可安全删除。
"""
from data.jpx_data_fetcher import *  # noqa: F401,F403
