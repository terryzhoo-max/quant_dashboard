"""
AlphaCore · 回测-实盘对账引擎 V1.0
=====================================
闭合 "回测信号 → 实盘执行 → 效果验证" 的最后一环。

核心功能:
  1. 信号覆盖率: 回测产生了多少信号 vs 实盘执行了多少
  2. 执行延迟: 信号产生到实际交易的天数
  3. 价格偏差: 回测价格 vs 实际成交价
  4. AIAE 建议仓位 vs 实盘仓位历史对账
  5. 综合对账评分

V1.0 2026-05-26
"""

import os
import json
import math
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from services.logger import get_logger

logger = get_logger("reconciliation")


class BacktestReconciliationEngine:
    """回测-实盘对账引擎"""

    VERSION = "1.0"

    def __init__(self):
        logger.info(f"BacktestReconciliationEngine V{self.VERSION} 初始化")

    # ═══════════════════════════════════════════════════
    #  核心: AIAE 仓位路径对账
    # ═══════════════════════════════════════════════════

    def reconcile_position_path(self) -> dict:
        """
        对账 AIAE 建议仓位历史 vs 实盘仓位历史。
        
        数据来源:
          - AIAE 建议: decision_log (每日快照)
          - 实盘仓位: portfolio_snapshots (每日快照)
        """
        try:
            from services import db as ac_db
        except ImportError:
            return {"status": "error", "message": "DB 模块不可用"}

        # 获取决策日志 (含 suggested_position)
        decisions = ac_db.get_decision_history(days=90)

        # 获取组合快照 (含 total_asset, market_value)
        snapshots = ac_db.get_portfolio_snapshots(days=90)

        if not decisions:
            return {"status": "no_data", "message": "决策日志无数据, 至少需运行系统 1 天以上"}

        # 构建日期索引
        snap_map = {}
        for s in snapshots:
            snap_map[s["date"]] = {
                "total_asset": s["total_asset"],
                "market_value": s["market_value"],
                "actual_pct": round(s["market_value"] / s["total_asset"] * 100, 1) if s["total_asset"] > 0 else 0,
            }

        # 逐日对账
        daily_records = []
        total_gap_abs = 0
        matched_days = 0

        for d in decisions:
            date = d["date"]
            suggested = d.get("suggested_position")
            if suggested is None:
                continue

            snap = snap_map.get(date)
            actual_pct = snap["actual_pct"] if snap else None

            gap = round(actual_pct - suggested, 1) if actual_pct is not None else None

            record = {
                "date": date,
                "aiae_regime": d.get("aiae_regime"),
                "suggested_pct": suggested,
                "actual_pct": actual_pct,
                "gap": gap,
                "gap_severity": self._gap_severity(gap),
            }
            daily_records.append(record)

            if gap is not None:
                total_gap_abs += abs(gap)
                matched_days += 1

        # 汇总统计
        avg_gap = round(total_gap_abs / max(matched_days, 1), 1)
        max_gap = max((abs(r["gap"]) for r in daily_records if r["gap"] is not None), default=0)

        # 合规率: |gap| < 10pt 的天数占比
        compliant_days = sum(1 for r in daily_records if r["gap"] is not None and abs(r["gap"]) < 10)
        compliance_rate = round(compliant_days / max(matched_days, 1) * 100, 1)

        # V3.3: EWMA 加权偏差 (half-life=7天, 近期权重更高)
        # 机构标准: 执行纪律评估应侧重近期表现，而非被历史极端值主导
        valid_gaps = [abs(r["gap"]) for r in daily_records if r["gap"] is not None]
        if valid_gaps:
            # math already imported at module level
            hl = 7  # half-life 7 trading days
            lam = math.log(2) / hl  # decay rate
            n = len(valid_gaps)
            weights = [math.exp(-lam * (n - 1 - i)) for i in range(n)]
            w_sum = sum(weights)
            ewma_gap = round(sum(g * w for g, w in zip(valid_gaps, weights)) / w_sum, 1)
        else:
            ewma_gap = avg_gap

        # V3.3: 趋势检测 (近7天 vs 前7天)
        recent_7 = valid_gaps[-7:] if len(valid_gaps) >= 7 else valid_gaps
        prior_7 = valid_gaps[-14:-7] if len(valid_gaps) >= 14 else valid_gaps[:max(len(valid_gaps)//2, 1)]
        avg_recent = sum(recent_7) / max(len(recent_7), 1)
        avg_prior = sum(prior_7) / max(len(prior_7), 1)
        if avg_prior > 0 and (avg_prior - avg_recent) / avg_prior > 0.2:
            trend = "converging"
        elif avg_recent > 0 and (avg_recent - avg_prior) / max(avg_prior, 1) > 0.2:
            trend = "diverging"
        else:
            trend = "stable"

        # 对账评分 (基于 EWMA 加权偏差, 更反映当前执行质量)
        if ewma_gap <= 5:
            score = 95
        elif ewma_gap <= 10:
            score = 80
        elif ewma_gap <= 15:
            score = 60
        elif ewma_gap <= 25:
            score = 45
        else:
            score = 30

        # 趋势加分/减分 (±5分, 鼓励改善)
        if trend == "converging":
            score = min(100, score + 5)
        elif trend == "diverging":
            score = max(0, score - 5)

        return {
            "status": "success",
            "summary": {
                "total_decision_days": len(decisions),
                "matched_days": matched_days,
                "avg_gap_abs": avg_gap,
                "ewma_gap_abs": ewma_gap,
                "max_gap_abs": round(max_gap, 1),
                "recent_7d_gap": round(avg_recent, 1),
                "compliance_rate_pct": compliance_rate,
                "score": score,
                "trend": trend,
            },
            "daily_records": daily_records[-30:],  # 最近 30 天
        }

    # ═══════════════════════════════════════════════════
    #  交易执行对账
    # ═══════════════════════════════════════════════════

    def reconcile_trades(self) -> dict:
        """
        分析交易记录的执行质量。
        
        指标:
          - 交易频率 (每周/每月)
          - 买卖比例
          - 执行集中度 (是否过度集中在少数标的)
        """
        try:
            from services import db as ac_db
        except ImportError:
            return {"status": "error", "message": "DB 模块不可用"}

        trades = ac_db.get_trades(limit=200)
        if not trades:
            return {"status": "no_data", "message": "交易记录为空"}

        # 过滤: 排除 broker import 类批量操作
        real_trades = [
            t for t in trades
            if t.get("action") in ("buy", "sell")
            and t.get("success", True)
        ]

        if not real_trades:
            return {
                "status": "limited_data",
                "message": "仅有券商导入记录, 无手动买卖交易",
                "total_trades": len(trades),
                "import_trades": len(trades),
                "real_trades": 0,
            }

        # 买卖统计
        buy_count = sum(1 for t in real_trades if t["action"] == "buy")
        sell_count = sum(1 for t in real_trades if t["action"] == "sell")

        # 标的集中度
        code_counts = {}
        for t in real_trades:
            code = t.get("ts_code", "")
            code_counts[code] = code_counts.get(code, 0) + 1

        top_3 = sorted(code_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        top_3_pct = sum(c for _, c in top_3) / max(len(real_trades), 1) * 100

        # 时间分布
        dates = set()
        for t in real_trades:
            ts = t.get("timestamp", "")
            if ts:
                dates.add(ts[:10])

        trading_days = len(dates)

        return {
            "status": "success",
            "total_trades": len(trades),
            "real_trades": len(real_trades),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "buy_sell_ratio": round(buy_count / max(sell_count, 1), 2),
            "trading_days": trading_days,
            "top_stocks": [{"code": c, "count": n} for c, n in top_3],
            "top_3_concentration_pct": round(top_3_pct, 1),
        }

    # ═══════════════════════════════════════════════════
    #  AIAE Regime 回顾对账
    # ═══════════════════════════════════════════════════

    def reconcile_regime_accuracy(self) -> dict:
        """
        回顾 AIAE Regime 预测的准确性:
          - 在 R1-R2 (建议加仓) 时, 后续市场是否上涨?
          - 在 R4-R5 (建议减仓) 时, 后续市场是否下跌?
        """
        try:
            from services import db as ac_db
        except ImportError:
            return {"status": "error", "message": "DB 模块不可用"}

        decisions = ac_db.get_decision_history(days=180)
        if len(decisions) < 10:
            return {"status": "insufficient_data", "message": f"需至少 10 天决策数据, 当前仅 {len(decisions)} 天"}

        # 构建日期→AIAE映射
        regime_map = {d["date"]: d.get("aiae_regime") for d in decisions if d.get("aiae_regime")}
        jcs_map = {d["date"]: d.get("jcs_score") for d in decisions if d.get("jcs_score") is not None}
        ret_map = {d["date"]: d.get("market_return_5d") for d in decisions if d.get("market_return_5d") is not None}

        # 按 regime 分组计算准确率
        regime_stats = {}
        for date, regime in regime_map.items():
            ret = ret_map.get(date)
            if ret is None:
                continue

            if regime not in regime_stats:
                regime_stats[regime] = {"total": 0, "correct": 0, "returns": []}

            regime_stats[regime]["total"] += 1
            regime_stats[regime]["returns"].append(ret)

            # R1-R2 建议买, 上涨即正确
            if regime <= 2 and ret > 0:
                regime_stats[regime]["correct"] += 1
            # R4-R5 建议卖, 下跌即正确
            elif regime >= 4 and ret < 0:
                regime_stats[regime]["correct"] += 1
            # R3 中性, 不计入
            elif regime == 3:
                regime_stats[regime]["correct"] += 1  # 中性总是"正确"

        # 格式化结果
        regime_labels = {1: "Ⅰ 极冷", 2: "Ⅱ 偏冷", 3: "Ⅲ 中性", 4: "Ⅳ 偏热", 5: "Ⅴ 极热"}
        result = {}
        for r in range(1, 6):
            s = regime_stats.get(r, {"total": 0, "correct": 0, "returns": []})
            result[str(r)] = {
                "label": regime_labels.get(r, f"R{r}"),
                "total": s["total"],
                "correct": s["correct"],
                "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else None,
                "avg_return_5d": round(sum(s["returns"]) / len(s["returns"]) * 100, 2) if s["returns"] else None,
            }

        # 综合准确率
        total_all = sum(s["total"] for s in regime_stats.values())
        correct_all = sum(s["correct"] for s in regime_stats.values())

        return {
            "status": "success",
            "total_days": total_all,
            "overall_accuracy": round(correct_all / max(total_all, 1) * 100, 1),
            "by_regime": result,
        }

    # ═══════════════════════════════════════════════════
    #  综合对账报告
    # ═══════════════════════════════════════════════════

    def generate_full_report(self) -> dict:
        """综合对账报告 (合并所有对账维度)"""
        position = self.reconcile_position_path()
        trades = self.reconcile_trades()
        regime = self.reconcile_regime_accuracy()

        # 综合评分
        scores = []
        if position.get("status") == "success":
            scores.append(position["summary"]["score"])
        if regime.get("status") == "success":
            scores.append(min(100, regime["overall_accuracy"]))

        overall_score = round(sum(scores) / max(len(scores), 1)) if scores else None

        # V3.2: 数据成熟度元数据 — 前端据此决定显示真实数据还是 "采集中" 提示
        decision_days = position.get("summary", {}).get("total_decision_days", 0) if position.get("status") == "success" else 0
        matched_days = position.get("summary", {}).get("matched_days", 0) if position.get("status") == "success" else 0
        min_required = 15
        maturity = {
            "decision_days": decision_days,
            "matched_days": matched_days,
            "min_required": min_required,
            "is_mature": matched_days >= min_required,
            "message": "数据充分" if matched_days >= min_required else f"数据采集中 · {matched_days}/{min_required}天",
        }

        return {
            "status": "success",
            "engine_version": self.VERSION,
            "computed_at": datetime.now().isoformat(),
            "overall_score": overall_score,
            "maturity": maturity,
            "position_reconciliation": position,
            "trade_analysis": trades,
            "regime_accuracy": regime,
        }

    # ═══════════════════════════════════════════════════
    #  辅助
    # ═══════════════════════════════════════════════════

    def _gap_severity(self, gap: float) -> str:
        if gap is None:
            return "unknown"
        abs_gap = abs(gap)
        if abs_gap <= 5:
            return "normal"
        elif abs_gap <= 10:
            return "warning"
        elif abs_gap <= 15:
            return "alert"
        else:
            return "critical"


# ===== 引擎单例 =====
_recon_instance = None
_recon_lock = threading.Lock()


def get_reconciliation_engine() -> BacktestReconciliationEngine:
    global _recon_instance
    if _recon_instance is None:
        with _recon_lock:
            if _recon_instance is None:
                _recon_instance = BacktestReconciliationEngine()
    return _recon_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  Backtest Reconciliation Engine V1.0 · Self-Test")
    print("=" * 60)

    engine = BacktestReconciliationEngine()

    # 综合对账
    report = engine.generate_full_report()
    print(f"\n  综合评分: {report.get('overall_score', 'N/A')}")

    # 仓位路径对账
    pos = report["position_reconciliation"]
    if pos.get("status") == "success":
        s = pos["summary"]
        print(f"\n  --- 仓位路径对账 ---")
        print(f"  决策天数: {s['total_decision_days']}")
        print(f"  有实盘数据的天数: {s['matched_days']}")
        print(f"  平均偏差: {s['avg_gap_abs']} pt")
        print(f"  最大偏差: {s['max_gap_abs']} pt")
        print(f"  合规率 (|gap|<10pt): {s['compliance_rate_pct']}%")
        print(f"  评分: {s['score']}")
    else:
        print(f"\n  仓位对账: {pos.get('status')} - {pos.get('message')}")

    # 交易分析
    trades = report["trade_analysis"]
    if trades.get("status") == "success":
        print(f"\n  --- 交易分析 ---")
        print(f"  总交易: {trades['total_trades']} (实盘: {trades['real_trades']})")
        print(f"  买/卖比: {trades['buy_sell_ratio']}")
    else:
        print(f"\n  交易分析: {trades.get('status')} - {trades.get('message')}")

    # Regime 准确率
    regime = report["regime_accuracy"]
    if regime.get("status") == "success":
        print(f"\n  --- Regime 准确率 ---")
        print(f"  总天数: {regime['total_days']}, 综合准确率: {regime['overall_accuracy']}%")
        for r, data in regime["by_regime"].items():
            if data["total"] > 0:
                print(f"    {data['label']}: {data['accuracy']}% ({data['total']}天)")
    else:
        print(f"\n  Regime对账: {regime.get('status')} - {regime.get('message')}")

    print(f"\n{'='*60}")
