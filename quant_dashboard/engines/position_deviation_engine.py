"""
AlphaCore · 持仓偏差分析引擎 V1.0
===================================
对比实盘持仓 vs AIAE 仓位建议, 量化偏差并生成调仓建议。

核心功能:
  1. 总仓位偏差: 实际仓位 vs AIAE 矩阵建议仓位
  2. AIAE ETF 覆盖度: 8 只核心 ETF 的持有情况
  3. 单票集中度告警: >10% 预警, >15% 警告, >20% 红线
  4. 首批减仓候选: 占比>10% AND (浮盈>30% OR regime>=4)
  5. 实盘健康度评分: 0-100 综合评分

V1.0 2026-05-26
"""

import os
import json
import math
import threading
from datetime import datetime
from typing import Optional, Dict, List

CACHE_DIR = "data_lake"

# AIAE ETF 核心标的池 (与 aiae_engine.py AIAE_ETF_POOL 保持一致)
AIAE_ETF_POOL = [
    {"ts_code": "510300.SH", "name": "沪深300ETF"},
    {"ts_code": "510050.SH", "name": "上证50ETF"},
    {"ts_code": "510500.SH", "name": "中证500ETF"},
    {"ts_code": "159915.SZ", "name": "创业板ETF"},
    {"ts_code": "512100.SH", "name": "中证1000ETF"},
    {"ts_code": "510880.SH", "name": "红利ETF"},
    {"ts_code": "515100.SH", "name": "红利低波100"},
    {"ts_code": "159905.SZ", "name": "深红利ETF"},
]
AIAE_ETF_CODES = {e["ts_code"] for e in AIAE_ETF_POOL}

# 集中度阈值
CONCENTRATION_WARNING = 10.0    # >10% 预警
CONCENTRATION_ALERT = 15.0      # >15% 警告
CONCENTRATION_REDLINE = 20.0    # >20% 审计红线

# 减仓候选触发条件
REDUCTION_MIN_PCT = 10.0        # 最低占比阈值
REDUCTION_MIN_PNL = 30.0        # 最低浮盈率阈值
REDUCTION_REGIME_TRIGGER = 4    # 档位触发阈值


def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [DEVIATION] {msg}")


class PositionDeviationEngine:
    """实盘持仓 vs AIAE 建议偏差分析引擎"""

    VERSION = "1.0"

    def __init__(self):
        _log(f"PositionDeviationEngine V{self.VERSION} 初始化")

    def load_portfolio(self) -> Optional[dict]:
        """加载最新 portfolio_store.json"""
        fp = "portfolio_store.json"
        if not os.path.exists(fp):
            _log(f"portfolio_store.json 不存在", "WARN")
            return None
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            _log(f"portfolio 读取失败: {e}", "ERROR")
            return None

    def compute_deviation(self, portfolio: dict = None, aiae_report: dict = None) -> dict:
        """
        计算实盘持仓与 AIAE 建议的全面偏差分析。
        
        Args:
            portfolio: portfolio_store.json 格式数据, 为 None 时自动加载
            aiae_report: AIAE generate_report() 输出, 为 None 时仅做持仓分析
        
        Returns:
            含总仓位偏差、ETF覆盖度、集中度告警、减仓候选、健康度评分
        """
        if portfolio is None:
            portfolio = self.load_portfolio()
        if portfolio is None:
            return {"status": "error", "message": "无法加载持仓数据"}

        positions = portfolio.get("positions", {})
        cash = portfolio.get("cash", 0)
        total_asset = portfolio.get("broker_total_asset", 0)
        total_mv = portfolio.get("broker_ref_market_value", 0)

        if total_asset <= 0:
            # 手动计算
            total_mv = sum(p.get("broker_market_value", 0) for p in positions.values())
            total_asset = total_mv + cash

        # 1. 实际仓位
        actual_position_pct = (total_mv / total_asset * 100) if total_asset > 0 else 0

        # 2. AIAE 建议仓位
        suggested_position = None
        regime = None
        if aiae_report and aiae_report.get("position"):
            suggested_position = aiae_report["position"].get("matrix_position")
            regime = aiae_report.get("current", {}).get("regime")

        # 3. 仓位偏差
        position_gap = None
        if suggested_position is not None:
            position_gap = round(actual_position_pct - suggested_position, 1)

        # 4. AIAE ETF 覆盖度
        etf_coverage = self._compute_etf_coverage(positions)

        # 5. 单票集中度分析
        concentration = self._compute_concentration(positions, total_asset)

        # 6. 首批减仓候选
        reduction_candidates = self._find_reduction_candidates(
            positions, total_asset, regime
        )

        # 7. 持仓结构分类
        structure = self._classify_structure(positions, total_asset)

        # 8. 健康度评分
        health = self._compute_health_score(
            actual_position_pct, suggested_position,
            etf_coverage, concentration, aiae_report
        )

        result = {
            "status": "success",
            "engine_version": self.VERSION,
            "computed_at": datetime.now().isoformat(),

            "portfolio_summary": {
                "total_asset": round(total_asset, 2),
                "total_market_value": round(total_mv, 2),
                "cash": round(cash, 2),
                "holding_count": len(positions),
                "import_date": portfolio.get("import_date", "unknown"),
            },

            "position_deviation": {
                "actual_pct": round(actual_position_pct, 1),
                "suggested_pct": suggested_position,
                "gap": position_gap,
                "gap_severity": self._classify_gap_severity(position_gap),
                "regime": regime,
            },

            "etf_coverage": etf_coverage,
            "concentration": concentration,
            "reduction_candidates": reduction_candidates,
            "structure": structure,
            "health_score": health,
        }

        _log(f"偏差分析完成: 仓位={actual_position_pct:.1f}% "
             f"(建议{suggested_position}%, 偏差{position_gap}pt) "
             f"ETF覆盖={etf_coverage['coverage_pct']:.0f}% "
             f"健康度={health['score']}")
        return result

    # ────────── ETF 覆盖度 ──────────

    def _compute_etf_coverage(self, positions: dict) -> dict:
        """计算 AIAE ETF 核心标的池的持有情况"""
        held = []
        missing = []

        for etf in AIAE_ETF_POOL:
            code = etf["ts_code"]
            if code in positions:
                held.append({
                    "ts_code": code,
                    "name": etf["name"],
                    "market_value": positions[code].get("broker_market_value", 0),
                })
            else:
                missing.append({
                    "ts_code": code,
                    "name": etf["name"],
                })

        coverage_pct = len(held) / len(AIAE_ETF_POOL) * 100 if AIAE_ETF_POOL else 0

        return {
            "coverage_pct": round(coverage_pct, 1),
            "held_count": len(held),
            "total_count": len(AIAE_ETF_POOL),
            "held": held,
            "missing": missing,
            "verdict": "充分" if coverage_pct >= 75 else ("部分" if coverage_pct >= 37.5 else "严重不足"),
        }

    # ────────── 单票集中度 ──────────

    def _compute_concentration(self, positions: dict, total_asset: float) -> dict:
        """单票集中度分析, 按占比排序"""
        if total_asset <= 0:
            return {"alerts": [], "max_pct": 0, "positions": []}

        pos_list = []
        for code, pos in positions.items():
            mv = pos.get("broker_market_value", 0)
            pct = mv / total_asset * 100 if total_asset > 0 else 0
            pnl_pct = pos.get("broker_pnl_pct", 0)
            name = pos.get("name", code)

            severity = "normal"
            if pct > CONCENTRATION_REDLINE:
                severity = "redline"
            elif pct > CONCENTRATION_ALERT:
                severity = "alert"
            elif pct > CONCENTRATION_WARNING:
                severity = "warning"

            pos_list.append({
                "ts_code": code,
                "name": name,
                "market_value": round(mv, 2),
                "pct": round(pct, 2),
                "pnl_pct": round(pnl_pct, 2),
                "severity": severity,
            })

        pos_list.sort(key=lambda x: x["pct"], reverse=True)

        alerts = [p for p in pos_list if p["severity"] != "normal"]
        max_pct = pos_list[0]["pct"] if pos_list else 0

        return {
            "positions": pos_list[:10],  # Top 10
            "alerts": alerts,
            "alert_count": len(alerts),
            "max_pct": round(max_pct, 2),
            "max_name": pos_list[0]["name"] if pos_list else "",
            "verdict": "正常" if not alerts else (
                "红线违规" if any(a["severity"] == "redline" for a in alerts) else "预警"
            ),
        }

    # ────────── 首批减仓候选 ──────────

    def _find_reduction_candidates(self, positions: dict, total_asset: float,
                                    regime: int = None) -> dict:
        """
        识别首批减仓候选:
          条件: 占比 > 10% AND (浮盈率 > 30% OR regime >= 4)
          优先级 = 占比 × 0.6 + 浮盈率 × 0.004
        """
        if total_asset <= 0:
            return {"candidates": [], "count": 0}

        candidates = []
        for code, pos in positions.items():
            mv = pos.get("broker_market_value", 0)
            pct = mv / total_asset * 100
            pnl_pct = pos.get("broker_pnl_pct", 0)
            name = pos.get("name", code)

            # 触发条件
            pct_trigger = pct > REDUCTION_MIN_PCT
            pnl_trigger = pnl_pct > REDUCTION_MIN_PNL
            regime_trigger = regime is not None and regime >= REDUCTION_REGIME_TRIGGER

            if pct_trigger and (pnl_trigger or regime_trigger):
                reasons = []
                if pnl_trigger:
                    reasons.append(f"浮盈 {pnl_pct:+.1f}% (>{REDUCTION_MIN_PNL}%)")
                if regime_trigger:
                    reasons.append(f"AIAE Ⅳ-Ⅴ级 (regime={regime})")
                if pct > CONCENTRATION_ALERT:
                    reasons.append(f"集中度 {pct:.1f}% (>{CONCENTRATION_ALERT}%)")

                priority = pct * 0.6 + max(pnl_pct, 0) * 0.004
                candidates.append({
                    "ts_code": code,
                    "name": name,
                    "pct": round(pct, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "market_value": round(mv, 2),
                    "priority": round(priority, 3),
                    "reasons": reasons,
                    "tag": "🔴 首批减仓候选",
                })

        candidates.sort(key=lambda x: x["priority"], reverse=True)

        return {
            "candidates": candidates,
            "count": len(candidates),
            "total_value": round(sum(c["market_value"] for c in candidates), 2),
        }

    # ────────── 持仓结构分类 ──────────

    def _classify_structure(self, positions: dict, total_asset: float) -> dict:
        """将持仓分为: 个股 / 宽基ETF / 行业ETF / 港股 / 其他"""
        categories = {
            "individual_stocks": {"count": 0, "value": 0, "items": []},
            "broad_etf": {"count": 0, "value": 0, "items": []},
            "sector_etf": {"count": 0, "value": 0, "items": []},
            "hk_stocks": {"count": 0, "value": 0, "items": []},
            "gold_commodity": {"count": 0, "value": 0, "items": []},
            "other": {"count": 0, "value": 0, "items": []},
        }

        BROAD_ETF_KEYWORDS = ["300ETF", "500ETF", "50ETF", "创业板", "科创50", "1000ETF"]
        GOLD_KEYWORDS = ["黄金", "gold"]

        for code, pos in positions.items():
            name = pos.get("name", "")
            mv = pos.get("broker_market_value", 0)

            if code.startswith("0") and len(code) == 8 and ".HK" in code:
                cat = "hk_stocks"
            elif ".HK" in code:
                cat = "hk_stocks"
            elif any(k in name for k in GOLD_KEYWORDS):
                cat = "gold_commodity"
            elif any(k in name for k in BROAD_ETF_KEYWORDS):
                cat = "broad_etf"
            elif code.startswith("15") or code.startswith("51") or code.startswith("56") or code.startswith("58"):
                cat = "sector_etf"
            else:
                cat = "individual_stocks"

            categories[cat]["count"] += 1
            categories[cat]["value"] += mv
            categories[cat]["items"].append({"code": code, "name": name, "value": round(mv, 2)})

        # 计算占比
        for cat_data in categories.values():
            cat_data["value"] = round(cat_data["value"], 2)
            cat_data["pct"] = round(cat_data["value"] / total_asset * 100, 1) if total_asset > 0 else 0

        return categories

    # ────────── 健康度评分 ──────────

    def _compute_health_score(self, actual_pct: float, suggested_pct: float,
                               etf_coverage: dict, concentration: dict,
                               aiae_report: dict = None) -> dict:
        """
        实盘健康度综合评分 (0-100)

        权重分配:
          ① 总仓位偏差  30%: |gap| < 5pt → 100, > 20pt → 0
          ② ETF覆盖度   20%: coverage_pct 直接
          ③ 集中度       15%: 所有 < 15% → 100, 任一 > 20% → 0
          ④ 配额对齐     15%: 简化为与中位配置的距离
          ⑤ 止损纪律     10%: 占位 80 分 (未来接入实盘数据)
          ⑥ 数据新鲜度   10%: 基于 stale_data_warnings 数量
        """
        scores = {}

        # ① 仓位偏差 (30%)
        if suggested_pct is not None:
            gap = abs(actual_pct - suggested_pct)
            if gap <= 5:
                scores["position"] = 100
            elif gap >= 20:
                scores["position"] = 0
            else:
                scores["position"] = round(100 - (gap - 5) / 15 * 100)
        else:
            scores["position"] = 70  # 无建议时给中性分

        # ② ETF 覆盖度 (20%)
        scores["etf_coverage"] = round(etf_coverage.get("coverage_pct", 0))

        # ③ 集中度 (15%)
        max_pct = concentration.get("max_pct", 0)
        if max_pct <= CONCENTRATION_WARNING:
            scores["concentration"] = 100
        elif max_pct >= CONCENTRATION_REDLINE:
            scores["concentration"] = 0
        else:
            scores["concentration"] = round(100 - (max_pct - CONCENTRATION_WARNING) / (CONCENTRATION_REDLINE - CONCENTRATION_WARNING) * 100)

        # ④ 配额对齐 (15%) — 简化: 用持仓数量和分散度评估
        holding_count = len(concentration.get("positions", []))
        if holding_count >= 15:
            scores["allocation"] = 85
        elif holding_count >= 10:
            scores["allocation"] = 75
        elif holding_count >= 5:
            scores["allocation"] = 60
        else:
            scores["allocation"] = 30

        # ⑤ 止损纪律 (10%) — 占位
        scores["stop_loss"] = 80

        # ⑥ 数据新鲜度 (10%)
        if aiae_report:
            stale_count = len(aiae_report.get("stale_data_warnings", []))
            scores["freshness"] = max(0, 100 - stale_count * 25)
        else:
            scores["freshness"] = 60

        # 加权汇总
        weights = {
            "position": 0.30,
            "etf_coverage": 0.20,
            "concentration": 0.15,
            "allocation": 0.15,
            "stop_loss": 0.10,
            "freshness": 0.10,
        }

        total = sum(scores[k] * weights[k] for k in weights)
        total = round(total)

        # 评级
        if total >= 90:
            grade = "A"
        elif total >= 80:
            grade = "B+"
        elif total >= 70:
            grade = "B"
        elif total >= 60:
            grade = "C+"
        elif total >= 50:
            grade = "C"
        else:
            grade = "D"

        return {
            "score": total,
            "grade": grade,
            "breakdown": scores,
            "weights": weights,
        }

    # ────────── 辅助 ──────────

    def _classify_gap_severity(self, gap: float) -> str:
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
_dev_instance = None
_dev_lock = threading.Lock()


def get_deviation_engine() -> PositionDeviationEngine:
    global _dev_instance
    if _dev_instance is None:
        with _dev_lock:
            if _dev_instance is None:
                _dev_instance = PositionDeviationEngine()
    return _dev_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  Position Deviation Engine V1.0 · Self-Test")
    print("=" * 60)

    engine = PositionDeviationEngine()

    # 加载实盘数据
    portfolio = engine.load_portfolio()
    if not portfolio:
        print("✗ portfolio_store.json 未找到")
        sys.exit(1)

    # 不需要 AIAE report, 仅做持仓分析
    result = engine.compute_deviation(portfolio)

    print(f"\n{'─'*40}")
    print(f"  持仓数: {result['portfolio_summary']['holding_count']}")
    print(f"  总资产: ¥{result['portfolio_summary']['total_asset']:,.0f}")
    print(f"  仓位: {result['position_deviation']['actual_pct']:.1f}%")
    print(f"{'─'*40}")

    # ETF 覆盖度
    etf = result["etf_coverage"]
    print(f"\n  AIAE ETF 覆盖度: {etf['held_count']}/{etf['total_count']} ({etf['coverage_pct']:.0f}%) [{etf['verdict']}]")
    if etf["missing"]:
        print(f"  缺失: {', '.join(m['name'] for m in etf['missing'])}")

    # 集中度
    conc = result["concentration"]
    print(f"\n  最大持仓: {conc['max_name']} ({conc['max_pct']:.1f}%) [{conc['verdict']}]")
    for a in conc["alerts"][:3]:
        print(f"    ⚠️ {a['name']}: {a['pct']:.1f}% [{a['severity']}]")

    # 减仓候选
    red = result["reduction_candidates"]
    if red["candidates"]:
        print(f"\n  🔴 首批减仓候选: {red['count']} 只 (合计 ¥{red['total_value']:,.0f})")
        for c in red["candidates"]:
            print(f"    {c['name']}: 占比{c['pct']:.1f}% 浮盈{c['pnl_pct']:+.1f}%")
            for r in c["reasons"]:
                print(f"      → {r}")

    # 健康度
    h = result["health_score"]
    print(f"\n  健康度评分: {h['score']} ({h['grade']})")
    for k, v in h["breakdown"].items():
        print(f"    {k}: {v} (×{h['weights'][k]:.0%})")

    print(f"\n{'='*60}")
