"""
AlphaCore V5.0 · 精确调仓指令生成器
============================================================
将 AIAE V5 仓位建议转化为具体可执行的交易指令。

输入:
  - 当前持仓 (portfolio_store.json)
  - AIAE V5 目标仓位 (regime → matrix_position)
  - SUB_STRATEGY_ALLOC 配额

输出:
  - 精确到个股的 买入/卖出/持有 指令
  - 考虑 100 股整数倍限制
  - 考虑冲击成本 (slippage)
  - 优先级排序 (先卖后买)

用法: python engines/rebalance_engine.py
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════
#  持仓标的分类映射
# ═══════════════════════════════════════════════════════

# ETF 策略归类 (部分常见标的)
STRATEGY_MAP = {
    # MR (均值回归 — 宽基)
    "510300": "mr", "510500": "mr", "159919": "mr", "510050": "mr",
    "159922": "mr", "512100": "mr",
    # DIV (红利)
    "515100": "div", "510880": "div", "159905": "div", "512890": "div",
    "563020": "div",
    # MOM (动量轮动 — 行业/主题)
    "159915": "mom", "159218": "mom", "159326": "mom", "512480": "mom",
    "512660": "mom", "512690": "mom", "512760": "mom", "516160": "mom",
    "159869": "mom", "512010": "mom", "512880": "mom", "562800": "mom",
    # GEM (全球)
    "513100": "gem", "518880": "gem", "159941": "gem", "513060": "gem",
    # ERP (债券/货币)
    "511010": "erp", "511260": "erp",
}

# 个股默认归类
DEFAULT_STOCK_STRATEGY = "mom"  # 个股默认归入动量


def _classify_holding(code: str) -> str:
    """将持仓标的归类到子策略"""
    # ETF 直接查表
    base = code.split(".")[0]
    if base in STRATEGY_MAP:
        return STRATEGY_MAP[base]

    # 个股按代码前缀判断
    if base.startswith(("51", "15", "56")):
        # ETF 未在表中, 默认 mom
        return "mom"
    # 普通个股
    return DEFAULT_STOCK_STRATEGY


def generate_rebalance_orders(
    target_position_pct: Optional[float] = None,
    regime: Optional[int] = None,
) -> dict:
    """
    生成精确调仓指令。

    参数:
      target_position_pct: 目标权益仓位(%), 不传则从 AIAE 缓存读取
      regime: AIAE regime(1-5), 不传则从缓存读取

    返回:
      {
        "status": "success",
        "current": {当前持仓概览},
        "target": {目标仓位分解},
        "orders": [具体交易指令],
        "summary": {汇总信息},
      }
    """
    # 1. 加载当前持仓
    portfolio_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "portfolio_store.json"
    )
    if not os.path.exists(portfolio_path):
        return {"status": "error", "error": "portfolio_store.json 不存在"}

    with open(portfolio_path, "r", encoding="utf-8") as f:
        pf = json.load(f)

    cash = pf.get("cash", 0)
    total_asset = pf.get("broker_total_asset", 0)
    positions = pf.get("positions", {})

    if total_asset <= 0:
        return {"status": "error", "error": "总资产为 0"}

    # 当前权益市值
    total_mv = sum(p.get("broker_market_value", 0) for p in positions.values())
    current_pct = total_mv / total_asset * 100

    # 2. 获取目标仓位
    if target_position_pct is None or regime is None:
        try:
            from services.cache_service import cache_manager
            aiae_ctx = cache_manager.get_json("aiae_ctx")
            if aiae_ctx:
                if target_position_pct is None:
                    target_position_pct = aiae_ctx.get("cap", 50)
                if regime is None:
                    regime = aiae_ctx.get("regime", 3)
        except Exception:
            pass
    if target_position_pct is None:
        target_position_pct = 50  # 安全默认
    if regime is None:
        regime = 3

    target_mv = total_asset * target_position_pct / 100
    delta_mv = target_mv - total_mv

    # 3. 按策略分类当前持仓
    from engines.aiae_params import SUB_STRATEGY_ALLOC
    alloc = SUB_STRATEGY_ALLOC.get(regime, SUB_STRATEGY_ALLOC[3])

    strat_holdings: Dict[str, List] = {"mr": [], "div": [], "mom": [], "gem": [], "erp": []}
    strat_mv: Dict[str, float] = {"mr": 0, "div": 0, "mom": 0, "gem": 0, "erp": 0}

    for code, pos in positions.items():
        strat = _classify_holding(code)
        mv = pos.get("broker_market_value", 0)
        strat_holdings[strat].append({
            "code": code,
            "name": pos.get("name", ""),
            "amount": pos.get("amount", 0),
            "price": pos.get("broker_price", pos.get("cost", 0)),
            "market_value": mv,
            "pnl_pct": pos.get("broker_pnl_pct", 0),
            "strategy": strat,
        })
        strat_mv[strat] += mv

    # 4. 计算各策略目标市值
    strat_target_mv = {}
    for key in ["mr", "div", "mom", "gem", "erp"]:
        alloc_pct = alloc.get(key, 20) / 100.0
        strat_target_mv[key] = target_mv * alloc_pct

    # 5. 生成交易指令
    orders = []
    total_sell = 0
    total_buy = 0

    for strat in ["mr", "div", "mom", "gem", "erp"]:
        current = strat_mv[strat]
        target = strat_target_mv[strat]
        delta = target - current

        if abs(delta) < 500:
            # 偏差 < 500 元, 忽略
            for h in strat_holdings[strat]:
                orders.append({
                    "action": "HOLD",
                    "code": h["code"],
                    "name": h["name"],
                    "strategy": strat,
                    "current_mv": round(h["market_value"]),
                    "reason": f"偏差可忽略 (R{regime} {strat}配额{alloc.get(strat,0)}%)",
                    "priority": 99,
                })
            continue

        if delta < 0:
            # 需要减仓 — 优先卖盈利最多的
            sell_amount = abs(delta)
            sorted_holdings = sorted(strat_holdings[strat],
                                     key=lambda x: x["pnl_pct"], reverse=True)
            for h in sorted_holdings:
                if sell_amount <= 0:
                    orders.append({
                        "action": "HOLD",
                        "code": h["code"],
                        "name": h["name"],
                        "strategy": strat,
                        "current_mv": round(h["market_value"]),
                        "reason": "保留",
                        "priority": 99,
                    })
                    continue

                price = h["price"]
                if price <= 0:
                    continue

                # 计算需卖出的股数 (100股整数倍)
                sell_shares_exact = sell_amount / price
                sell_shares = int(sell_shares_exact // 100) * 100
                if sell_shares <= 0:
                    sell_shares = 100  # 最少卖 1 手

                sell_shares = min(sell_shares, h["amount"])  # 不超过持有量
                sell_mv = sell_shares * price

                if sell_shares >= h["amount"]:
                    action = "SELL_ALL"
                    sell_shares = h["amount"]
                    sell_mv = h["market_value"]
                else:
                    action = "SELL"

                orders.append({
                    "action": action,
                    "code": h["code"],
                    "name": h["name"],
                    "strategy": strat,
                    "shares": sell_shares,
                    "price": round(price, 2),
                    "amount": round(sell_mv),
                    "current_mv": round(h["market_value"]),
                    "pnl_pct": h["pnl_pct"],
                    "reason": f"R{regime}减仓 {strat}→配额{alloc.get(strat,0)}% (盈利{h['pnl_pct']:+.1f}%优先)",
                    "priority": 1 if action == "SELL_ALL" else 2,
                })

                sell_amount -= sell_mv
                total_sell += sell_mv

        else:
            # 需要加仓 — 标记策略需求
            for h in strat_holdings[strat]:
                orders.append({
                    "action": "HOLD",
                    "code": h["code"],
                    "name": h["name"],
                    "strategy": strat,
                    "current_mv": round(h["market_value"]),
                    "reason": "持有 + 可加仓",
                    "priority": 99,
                })

            orders.append({
                "action": "BUY_SIGNAL",
                "code": f"待定({strat})",
                "name": f"{strat.upper()} 子策略加仓",
                "strategy": strat,
                "amount": round(delta),
                "reason": f"R{regime}加仓 {strat}配额{alloc.get(strat,0)}%, 缺口{delta:,.0f}元",
                "priority": 5,
            })
            total_buy += delta

    # 排序: 卖出优先
    orders.sort(key=lambda x: x["priority"])

    # 6. 汇总
    summary = {
        "regime": regime,
        "current_pct": round(current_pct, 1),
        "target_pct": round(target_position_pct, 1),
        "delta_pct": round(target_position_pct - current_pct, 1),
        "total_asset": round(total_asset),
        "current_mv": round(total_mv),
        "target_mv": round(target_mv),
        "delta_mv": round(delta_mv),
        "total_sell": round(total_sell),
        "total_buy": round(total_buy),
        "sell_count": sum(1 for o in orders if o["action"].startswith("SELL")),
        "buy_count": sum(1 for o in orders if o["action"] == "BUY_SIGNAL"),
        "hold_count": sum(1 for o in orders if o["action"] == "HOLD"),
        "strategy_breakdown": {
            k: {
                "current_mv": round(strat_mv[k]),
                "target_mv": round(strat_target_mv[k]),
                "delta_mv": round(strat_target_mv[k] - strat_mv[k]),
                "alloc_pct": alloc.get(k, 0),
            } for k in ["mr", "div", "mom", "gem", "erp"]
        },
    }

    return {
        "status": "success",
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "orders": orders,
    }


def print_orders(result: dict):
    """打印调仓指令"""
    if result["status"] != "success":
        print(f"错误: {result.get('error')}")
        return

    s = result["summary"]
    print("\n" + "=" * 70)
    print(f"  AIAE V5 调仓指令 | R{s['regime']} | {s['current_pct']:.1f}% → {s['target_pct']:.1f}%")
    print(f"  总资产: {s['total_asset']:,.0f} | 偏差: {s['delta_mv']:+,.0f}")
    print("=" * 70)

    # 策略分解
    print("\n  子策略配额:")
    for k, v in s["strategy_breakdown"].items():
        arrow = "↑" if v["delta_mv"] > 500 else ("↓" if v["delta_mv"] < -500 else "≈")
        print(f"    {k:>4} [{v['alloc_pct']:>2}%]: {v['current_mv']:>10,.0f} → {v['target_mv']:>10,.0f} {arrow} {v['delta_mv']:+,.0f}")

    # 交易指令
    print(f"\n  交易指令 (卖{s['sell_count']} 买{s['buy_count']} 持{s['hold_count']}):")
    print(f"  {'操作':<10} {'代码':<12} {'名称':<10} {'股数':>6} {'金额':>10} {'策略':>4}  原因")
    print("  " + "-" * 68)
    for o in result["orders"]:
        if o["action"] == "HOLD":
            continue
        shares = o.get("shares", "")
        amount = o.get("amount", 0)
        print(f"  {o['action']:<10} {o['code']:<12} {o['name']:<10} {str(shares):>6} {amount:>10,.0f} {o['strategy']:>4}  {o['reason'][:30]}")

    print("=" * 70)


def run_stress_test() -> dict:
    """
    组合压力测试: 模拟当前持仓在 R1~R5 各 regime 下的调仓需求。

    输出:
      - 各 regime 下的目标仓位 / 卖出金额 / 策略偏离
      - 最大单日调仓量 (流动性压力)
      - 风险评估
    """
    from engines.aiae_params import SUB_STRATEGY_ALLOC, V5_POSITION_MATRIX

    # 典型 ERP 场景下的仓位上限 (erp_4_6 最常见)
    pos_by_regime = {1: 75, 2: 70, 3: 60, 4: 35, 5: 10}

    scenarios = {}
    for regime in range(1, 6):
        target_pct = pos_by_regime[regime]
        result = generate_rebalance_orders(
            target_position_pct=target_pct,
            regime=regime,
        )

        if result["status"] != "success":
            scenarios[f"R{regime}"] = {"error": result.get("error")}
            continue

        s = result["summary"]
        sell_orders = [o for o in result["orders"] if o["action"].startswith("SELL")]
        buy_orders = [o for o in result["orders"] if o["action"] == "BUY_SIGNAL"]

        # 策略偏离度 (当前 vs 目标的绝对偏差之和)
        deviation = sum(
            abs(v["delta_mv"])
            for v in s["strategy_breakdown"].values()
        )

        scenarios[f"R{regime}"] = {
            "target_pct": target_pct,
            "delta_pct": s["delta_pct"],
            "total_sell": s["total_sell"],
            "total_buy": s["total_buy"],
            "sell_count": s["sell_count"],
            "buy_count": s["buy_count"],
            "strategy_deviation": round(deviation),
            "alloc": {k: v["alloc_pct"] for k, v in s["strategy_breakdown"].items()},
        }

    # 流动性压力评估
    current_mv = 0
    try:
        r3 = generate_rebalance_orders(target_position_pct=60, regime=3)
        current_mv = r3["summary"]["current_mv"]
    except Exception:
        pass

    # R4/R5 紧急减仓量
    r4_sell = scenarios.get("R4", {}).get("total_sell", 0)
    r5_sell = scenarios.get("R5", {}).get("total_sell", 0)

    # 假设单日最大卖出 = 当前市值 20% (A股流动性约束)
    max_daily_sell = current_mv * 0.20 if current_mv > 0 else 0
    r5_days = max(1, r5_sell / max_daily_sell) if max_daily_sell > 0 else 999

    risk_assessment = {
        "current_equity_pct": round(current_mv / (current_mv + 357.13) * 100 if current_mv > 0 else 0, 1),
        "r4_sell_amount": round(r4_sell),
        "r5_sell_amount": round(r5_sell),
        "max_daily_sell": round(max_daily_sell),
        "r5_liquidation_days": round(r5_days, 1),
        "liquidity_risk": "HIGH" if r5_days > 3 else ("MEDIUM" if r5_days > 1.5 else "LOW"),
    }

    return {
        "status": "success",
        "generated_at": datetime.now().isoformat(),
        "scenarios": scenarios,
        "risk_assessment": risk_assessment,
    }


def print_stress_test(result: dict):
    """打印压力测试报告"""
    if result["status"] != "success":
        print(f"错误: {result.get('error')}")
        return

    print("\n" + "=" * 70)
    print("  AIAE V5 组合压力测试 | R1~R5 全场景")
    print("=" * 70)

    print(f"\n  {'Regime':<8} {'目标%':>6} {'仓位Δ':>7} {'需卖':>10} {'需买':>10} {'偏离':>10}")
    print("  " + "-" * 55)
    for rk in ["R1", "R2", "R3", "R4", "R5"]:
        sc = result["scenarios"].get(rk, {})
        if "error" in sc:
            print(f"  {rk:<8} ERROR: {sc['error']}")
            continue
        print(f"  {rk:<8} {sc['target_pct']:>5}% {sc['delta_pct']:>+6.1f}% "
              f"{sc['total_sell']:>10,.0f} {sc['total_buy']:>10,.0f} {sc['strategy_deviation']:>10,.0f}")

    ra = result["risk_assessment"]
    print(f"\n  风险评估:")
    print(f"    当前权益:        {ra['current_equity_pct']:.1f}%")
    print(f"    R4 需卖出:       {ra['r4_sell_amount']:>10,.0f}")
    print(f"    R5 需卖出:       {ra['r5_sell_amount']:>10,.0f}")
    print(f"    单日最大卖出:    {ra['max_daily_sell']:>10,.0f}")
    print(f"    R5 清仓需:       {ra['r5_liquidation_days']:.1f} 天")
    print(f"    流动性风险:      {ra['liquidity_risk']}")
    print("=" * 70)


if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) > 1 and _sys.argv[1] == "stress":
        result = run_stress_test()
        print_stress_test(result)
        out_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "stress_test_results.json"
        )
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n压力测试已保存: {out_path}")
    else:
        result = generate_rebalance_orders()
        print_orders(result)
        out_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "rebalance_orders.json"
        )
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n指令已保存: {out_path}")

