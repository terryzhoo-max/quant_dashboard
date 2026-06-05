# ⚠️ DEPRECATED: 此文件仅为兼容性代理, 请直接 import engines/strategies 子模块.
# 计划在 V27.0 移除. 请更新引用: from strategies.mr_per_regime_optimizer import xxx
"""
⚠️ 兼容 shim — 此文件已迁移至 strategies/mr_per_regime_optimizer.py
=======================================================
保留此 shim 确保旧 import 路径继续工作。
迁移完成后可安全删除。
"""
from strategies.mr_per_regime_optimizer import *  # noqa: F401,F403
