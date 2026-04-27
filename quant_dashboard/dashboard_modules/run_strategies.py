"""
Dashboard Module: 三大策略引擎并行执行
======================================
并行调用 MR/DIV/MOM 三大策略引擎，返回标准化结构。
"""

import asyncio
import logging
from mean_reversion_engine import run_strategy
from dividend_trend_engine import run_dividend_strategy
from momentum_rotation_engine import run_momentum_strategy


async def run_all_strategies(executor):
    """并行运行三大策略引擎 → 返回 (mr_res, div_res, mom_res)"""
    logger = logging.getLogger("alphacore.strategies")
    logger.info("Starting Real-time Strategy Engines...")
    loop = asyncio.get_running_loop()
    mr_future = loop.run_in_executor(executor, run_strategy)
    div_future = loop.run_in_executor(executor, run_dividend_strategy)
    mom_future = loop.run_in_executor(executor, run_momentum_strategy)

    mr_res, div_res, mom_res = await asyncio.gather(mr_future, div_future, mom_future)

    # 包装 MR 裸 list 为标准结构
    if isinstance(mr_res, list):
        mr_res = wrap_mr_results(mr_res)

    return mr_res, div_res, mom_res


def wrap_mr_results(signals_list: list) -> dict:
    """把 run_strategy() 返回的裸 list 包装成前端期望的标准结构"""
    from datetime import datetime as _dt

    # 补算 suggested_position（MR引擎不输出该字段）
    for s in signals_list:
        if "suggested_position" not in s:
            sig = s.get("signal", "hold")
            score = s.get("signal_score", 0)
            if sig == "buy":
                s["suggested_position"] = 15 if score >= 85 else (10 if score >= 70 else 5)
            elif sig in ("sell", "sell_half", "sell_weak", "stop_loss", "no_entry"):
                s["suggested_position"] = 0
            else:
                s["suggested_position"] = 0

    valid = [s for s in signals_list if s.get("signal") != "error"]
    errors = [s for s in signals_list if s.get("signal") == "error"]
    buy_signals = [s for s in valid if s.get("signal") == "buy"]
    sell_signals = [s for s in valid if s.get("signal") in ("sell", "sell_half", "sell_weak")]

    # 计算 market_overview
    biases = [abs(s.get("bias", 0)) for s in valid]
    max_dev_item = max(valid, key=lambda x: abs(x.get("bias", 0)), default={})
    above_3 = sum(1 for s in valid if abs(s.get("bias", 0)) >= 3)
    total_pos = sum(s.get("suggested_position", 0) for s in buy_signals)
    divergence = "偏离中" if above_3 > 3 else "正常"

    overview = {
        "avg_deviation": round(sum(biases) / len(biases), 2) if biases else 0,
        "max_deviation": {
            "name": max_dev_item.get("name", "—"),
            "value": round(abs(max_dev_item.get("bias", 0)), 2),
        },
        "signal_count": {"buy": len(buy_signals), "sell": len(sell_signals)},
        "total_suggested_position": total_pos,
        "above_3pct": above_3,
        "market_divergence": divergence,
    }

    return {
        "status": "success",
        "timestamp": _dt.now().isoformat(),
        "data": {
            "signals": valid,
            "market_overview": overview,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "errors": errors,
        },
    }
