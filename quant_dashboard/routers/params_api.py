"""
AlphaCore · 参数同步 API V5.2
===============================
为前端提供后端参数的只读访问，消灭前端硬编码。
所有 GET 请求，无需鉴权。

用途:
  - 前端启动时一次性拉取后端参数
  - 替代 strategy.js 中的 ASSET_PARAMS / gateMap / capMap 硬编码
  - 替代 strategy_aiae.js 中的 posValues 硬编码仓位矩阵
"""

from fastapi import APIRouter
from config import (
    POSITION_CONFIG,
    MOMENTUM_LOOKBACK, MOMENTUM_VOL_MIN, MOMENTUM_GROUP_CAP,
    AUDIT_CONFIG,
)
from services.strategy_params import get_runtime_metadata, load_runtime_config

router = APIRouter(prefix="/api/v1/params", tags=["params"])


@router.get("/strategy-config")
async def get_strategy_config():
    """
    一次性返回前端需要的全部策略参数 (只读, 无鉴权)
    前端可用 _serverParams 缓存, 页面生命周期内不再重复请求
    """
    # 延迟导入: 避免循环依赖和启动时模块加载顺序问题
    try:
        from engines.aiae_params import (
            V5_ENABLED, V5_REGIME_THRESHOLDS, V5_POSITION_MATRIX,
            REGIME_THRESHOLDS, POSITION_MATRIX, SUB_STRATEGY_ALLOC,
        )
        from engines.aiae_engine import JOINT_WEIGHTS, REGIMES

        aiae_config = {
            "v5_enabled": V5_ENABLED,
            "thresholds": V5_REGIME_THRESHOLDS if V5_ENABLED else REGIME_THRESHOLDS,
            "position_matrix": V5_POSITION_MATRIX if V5_ENABLED else POSITION_MATRIX,
            "sub_alloc": SUB_STRATEGY_ALLOC,
            "joint_weights": {
                str(k): v for k, v in JOINT_WEIGHTS.items()
            },
            "regimes": {
                str(k): {
                    "cn": v.get("cn", ""),
                    "pos_min": v.get("pos_min", 0),
                    "pos_max": v.get("pos_max", 100),
                }
                for k, v in REGIMES.items()
            },
        }
    except Exception as e:
        aiae_config = {"error": str(e), "v5_enabled": True}

    # MR 资产类别参数 (替代前端 ASSET_PARAMS 硬编码)
    try:
        from engines.mean_reversion_engine import _load_asset_params
        asset_params = _load_asset_params()
    except Exception:
        asset_params = {}

    runtime = load_runtime_config()
    strategies = runtime["strategies"]
    position_config = dict(POSITION_CONFIG)
    for key, strategy in (
        ("mr_regime_cap", "mr"),
        ("mom_regime_cap", "momentum"),
        ("gem_regime_cap", "gem"),
        ("dividend_regime_cap", "dividend"),
    ):
        position_config[key] = dict(strategies[strategy]["position_caps"])

    return {
        "version": "V5.2",
        "runtime": get_runtime_metadata(),
        "position": position_config,
        "mr": {
            "score_gate": dict(strategies["mr"]["score_gates"]),
            "stop_loss": {
                state: -float(value)
                for state, value in strategies["mr"]["stop_losses"].items()
            },
            "pos_cap": dict(strategies["mr"]["position_caps"]),
            "regimes": dict(strategies["mr"]["regimes"]),
            "asset_params": asset_params,
        },
        "momentum": {
            "lookback": MOMENTUM_LOOKBACK,
            "vol_min": MOMENTUM_VOL_MIN,
            "group_cap": MOMENTUM_GROUP_CAP,
            "pos_cap": dict(strategies["momentum"]["position_caps"]),
            "single_position_cap": dict(
                strategies["momentum"]["single_position_caps"]
            ),
            "score_gate": dict(strategies["momentum"]["score_gates"]),
            "stop_loss": {
                state: -float(value) * 100
                for state, value in strategies["momentum"]["stop_losses"].items()
            },
        },
        "gem": {"pos_cap": dict(strategies["gem"]["position_caps"])},
        "dividend": {"pos_cap": dict(strategies["dividend"]["position_caps"])},
        "erp": {"params": dict(strategies["erp"]["params"])},
        "aiae": aiae_config,
        "audit": {
            "stop_loss_stock": AUDIT_CONFIG.get("stop_loss_stock", -12),
            "stop_loss_etf": AUDIT_CONFIG.get("stop_loss_etf", -8),
            "stop_loss_broad_etf": AUDIT_CONFIG.get("stop_loss_broad_etf", -6),
            "stop_loss_overseas_etf": AUDIT_CONFIG.get("stop_loss_overseas_etf", -8),
            "single_position_limit": AUDIT_CONFIG.get("single_position_limit", 20),
            "sector_limit": AUDIT_CONFIG.get("sector_limit", 40),
            "total_position_cap": AUDIT_CONFIG.get("total_position_cap", 95),
        },
    }


@router.get("/tushare-stats")
async def get_tushare_stats():
    """Tushare 限频器运行统计 (运维用)"""
    try:
        from services.tushare_limiter import tushare_limiter
        return {"status": "ok", **tushare_limiter.stats}
    except Exception as e:
        return {"status": "error", "message": str(e)}
