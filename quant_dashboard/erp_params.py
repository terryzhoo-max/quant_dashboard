# ⚠️ DEPRECATED: 此文件仅为兼容性代理, 请直接 import engines/strategies 子模块.
# 计划在 V27.0 移除. 请更新引用: from engines.erp_params import xxx
"""
⚠️ 兼容 shim — 此文件已迁移至 engines/erp_params.py
=======================================================
保留此 shim 确保旧 import 路径继续工作。
迁移完成后可安全删除。
"""
from engines import erp_params as _impl
from engines.erp_params import *  # noqa: F401,F403


def reload_runtime_params():
    """Reload implementation values and refresh immutable shim exports."""
    params = _impl.reload_runtime_params()
    globals().update({
        "BUY_THRESHOLD": _impl.BUY_THRESHOLD,
        "SELL_THRESHOLD": _impl.SELL_THRESHOLD,
        "ERP_WINDOW": _impl.ERP_WINDOW,
        "STOP_LOSS": _impl.STOP_LOSS,
        "WEIGHTS": _impl.WEIGHTS,
        "OPTIMIZER_DEFAULTS": _impl.OPTIMIZER_DEFAULTS,
    })
    return params
