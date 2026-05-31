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
    POSITION_CONFIG, MR_SCORE_GATE, MR_STOP_LOSS,
    MOMENTUM_LOOKBACK, MOMENTUM_VOL_MIN, MOMENTUM_GROUP_CAP,
    AUDIT_CONFIG,
)

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

    return {
        "version": "V5.2",
        "position": POSITION_CONFIG,
        "mr": {
            "score_gate": MR_SCORE_GATE,
            "stop_loss": MR_STOP_LOSS,
            "pos_cap": POSITION_CONFIG["mr_regime_cap"],
            "asset_params": asset_params,
        },
        "momentum": {
            "lookback": MOMENTUM_LOOKBACK,
            "vol_min": MOMENTUM_VOL_MIN,
            "group_cap": MOMENTUM_GROUP_CAP,
        },
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
