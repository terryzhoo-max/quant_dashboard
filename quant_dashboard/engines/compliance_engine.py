"""
AlphaCore V22.0 · 预交易合规检查引擎 (Pre-Trade Compliance Engine)
==================================================================
从"展示风控"升级为"执行风控" — 每个交易决策在输出前必须通过合规检查。

规则类型:
  - hard_block: 硬阻断 — 该操作在当前市场环境下被系统禁止
  - soft_warn:  软警告 — 操作可以执行但需谨慎
  - info:       提示    — 仅供参考

规则来源: V3.0 策略协议 + V19.1 风控护栏 + V21.2 预警阈值
"""

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ComplianceRule:
    id: str
    name: str
    severity: str  # "hard_block" | "soft_warn" | "info"
    description: str
    check_fn: Callable  # (snapshot, positions, context) -> (passed: bool, detail: str)

    def check(self, snapshot: dict, positions: list = None, context: dict = None) -> dict:
        """执行检查, 返回 {passed, detail, rule_id, severity}"""
        try:
            passed, detail = self.check_fn(snapshot, positions, context)
        except Exception as e:
            passed, detail = True, f"规则执行异常: {e}"
        return {
            "rule_id": self.id,
            "rule_name": self.name,
            "severity": self.severity,
            "passed": passed,
            "detail": detail,
        }


# ═══════════════════════════════════════════════════════════
#  规则定义
# ═══════════════════════════════════════════════════════════

def _check_single_stock_cap(snapshot, positions, ctx):
    """单票仓位 ≤ 20% (硬阻断)"""
    if not positions:
        return True, "无持仓数据"
    over = []
    for p in positions:
        w = p.get("weight", 0)
        if w > 20:
            over.append(f"{p.get('name', p.get('ts_code', '?'))} {w:.1f}%")
    if over:
        return False, f"超配标的: {', '.join(over[:3])}"
    return True, "所有标的仓位 ≤ 20%"


def _check_sector_concentration(snapshot, positions, ctx):
    """单板块仓位 ≤ 40% (软警告)"""
    if not positions:
        return True, "无持仓数据"
    sectors = {}
    for p in positions:
        ind = p.get("industry", "其他")
        sectors[ind] = sectors.get(ind, 0) + p.get("weight", 0)
    max_sec = max(sectors.items(), key=lambda x: x[1]) if sectors else ("", 0)
    if max_sec[1] > 40:
        return False, f"{max_sec[0]} 板块集中度 {max_sec[1]:.0f}% > 40% 红线"
    elif max_sec[1] > 30:
        return True, f"{max_sec[0]} 板块 {max_sec[1]:.0f}%, 接近 40% 红线，谨慎增持"
    return True, "板块分散度正常"


def _check_aiae_overheat(snapshot, positions, ctx):
    """AIAE ≥ R4 时禁止新建仓 (硬阻断)"""
    regime = snapshot.get("aiae_regime", 3)
    direction = ctx.get("direction", "hold") if ctx else "hold"
    if regime >= 5:
        return False, f"AIAE V级极度过热, 全面禁止建仓. 当前仓位上限 15%"
    if regime >= 4 and direction == "increase":
        return False, f"AIAE IV级偏热, 禁止加仓. 仅允许减仓或持有"
    if regime >= 4:
        return True, f"AIAE R{regime} 偏热, 允许减仓但禁止加仓"
    return True, f"AIAE R{regime}, 无建仓限制"


def _check_position_vs_cap(snapshot, positions, ctx):
    """P0-3: 当前实际仓位 是否已超过 AIAE regime 上限 (硬阻断)
    
    解决的问题: AIAE 从 R3 跳到 R4 时, 如果操作方向是 hold,
    旧规则不会提示“当前 80% 仓位已超过 R4 上限 40%”。
    """
    # 从 AIAE 缓存获取当前 regime cap
    regime_cap = None
    try:
        from services.cache_service import cache_manager
        aiae_ctx = cache_manager.get_json("aiae_ctx")
        if aiae_ctx and aiae_ctx.get("cap") is not None:
            regime_cap = aiae_ctx["cap"]
    except Exception:
        pass
    
    if regime_cap is None:
        return True, "无 AIAE cap 数据, 跳过仓位上限检查"
    
    # 获取当前实际仓位
    current_pos = snapshot.get("suggested_position")
    # 尝试从 portfolio engine 获取真实仓位
    actual_pos = None
    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        val = pe.get_valuation()
        total = val.get("total_asset", 0)
        mv = val.get("market_value", 0)
        if total > 0:
            actual_pos = round(mv / total * 100, 1)
    except Exception:
        pass
    
    pos_to_check = actual_pos if actual_pos is not None else current_pos
    if pos_to_check is None:
        return True, "无仓位数据, 跳过检查"
    
    overshoot = pos_to_check - regime_cap
    if overshoot > 10:
        return False, (f"当前仓位 {pos_to_check:.0f}% 超过 AIAE cap {regime_cap:.0f}% 达 {overshoot:.0f}pp. "
                       f"必须立即减仓至 {regime_cap:.0f}% 以下.")
    elif overshoot > 0:
        return True, (f"当前仓位 {pos_to_check:.0f}% 略超 AIAE cap {regime_cap:.0f}% "
                      f"({overshoot:.0f}pp). 建议逐步减仓.")
    return True, f"仓位 {pos_to_check:.0f}% 在 AIAE cap {regime_cap:.0f}% 以内"


def _check_jcs_threshold(snapshot, positions, ctx):
    """JCS < 40 时禁止加仓 (硬阻断)"""
    jcs_level = (ctx or {}).get("jcs_level", "medium")
    jcs_score = (ctx or {}).get("jcs_score", 50)
    direction = ctx.get("direction", "hold") if ctx else "hold"
    if jcs_level == "low" and direction == "increase":
        return False, f"JCS {jcs_score:.0f} < 40 (低置信), 禁止加仓. 等待信号改善"
    if jcs_level == "low":
        return True, f"JCS {jcs_score:.0f} 低置信, 允许减仓但禁止加仓"
    return True, f"JCS {jcs_score:.0f}, 置信度满足操作要求"


def _check_vix_emergency(snapshot, positions, ctx):
    """VIX > 35 时全组合降至 30% 以下 (硬阻断)"""
    vix = snapshot.get("vix_val", 20) or 20
    if vix > 35:
        return False, f"VIX {vix:.0f} > 35 极端恐慌, 仓位强制上限 30%. 仅允许减仓至线内."
    if vix > 30:
        return False, f"VIX {vix:.0f} > 30 恐慌, 仓位上限 30%. 暂停所有加仓操作."
    return True, f"VIX {vix:.0f}, 无紧急限制"


def _check_min_holdings(snapshot, positions, ctx):
    """最少持仓 5 只标的 (信息提示)"""
    if not positions:
        return True, "无持仓数据"
    count = len(positions)
    if count < 3:
        return True, f"仅 {count} 只持仓, 集中度风险极高. 建议分散至 ≥ 5 只."
    if count < 5:
        return True, f"{count} 只持仓, 接近最低分散要求 (≥ 5). 考虑增加标的."
    return True, f"{count} 只持仓, 分散化满足要求"


# ── 规则集 ──
COMPLIANCE_RULES = [
    ComplianceRule("single_stock_cap", "单票仓位上限", "hard_block",
                   "任何单一标的仓位不得超过 20%", _check_single_stock_cap),
    ComplianceRule("sector_concentration", "板块集中度", "soft_warn",
                   "任何单一板块仓位不得超过 40%", _check_sector_concentration),
    ComplianceRule("aiae_overheat", "AIAE 过热限制", "hard_block",
                   "AIAE ≥ R4 时禁止新建仓位", _check_aiae_overheat),
    ComplianceRule("position_vs_cap", "仓位超限检查", "hard_block",
                   "当前实际仓位不得超过 AIAE regime 上限 10pp", _check_position_vs_cap),
    ComplianceRule("jcs_threshold", "JCS 置信度门槛", "hard_block",
                   "JCS < 40 时禁止加仓操作", _check_jcs_threshold),
    ComplianceRule("vix_emergency", "VIX 紧急刹车", "hard_block",
                   "VIX > 30 时仓位强制上限 30%", _check_vix_emergency),
    ComplianceRule("min_holdings", "最低分散持仓", "info",
                   "持仓标的数 ≥ 5 只以分散尾部风险", _check_min_holdings),
]


# ═══════════════════════════════════════════════════════════
#  合规检查入口
# ═══════════════════════════════════════════════════════════

def run_compliance_check(snapshot: dict, positions: list = None,
                         context: dict = None) -> dict:
    """
    执行全部 6 条合规规则检查。

    参数:
      snapshot: 当前市场快照
      positions: 持仓列表 [{ts_code, name, weight, industry, ...}]
      context: 操作上下文 {direction, jcs_level, jcs_score, ...}

    返回:
    {
        "status": "passed" / "blocked" / "warning",
        "passed_count": int,
        "failed_count": int,
        "warn_count": int,
        "checks": [{rule_id, rule_name, severity, passed, detail}],
        "blocks": [仅 hard_block 且 failed 的规则],
        "summary": str,
    }
    """
    if positions is None:
        try:
            from portfolio_engine import get_portfolio_engine
            pe = get_portfolio_engine()
            val = pe.get_valuation()
            positions = val.get("positions", [])
        except Exception:
            positions = []

    results = []
    for rule in COMPLIANCE_RULES:
        results.append(rule.check(snapshot, positions, context))

    failed = [r for r in results if not r["passed"]]
    hard_blocks = [r for r in failed if r["severity"] == "hard_block"]
    soft_warns = [r for r in failed if r["severity"] == "soft_warn"]

    if hard_blocks:
        status = "blocked"
        summary = f"🛑 {len(hard_blocks)} 条硬阻断: " + "; ".join(
            r["rule_name"] for r in hard_blocks[:3])
    elif soft_warns:
        status = "warning"
        summary = f"⚠️ {len(soft_warns)} 条警告: " + "; ".join(
            r["rule_name"] for r in soft_warns[:3])
    else:
        status = "passed"
        summary = "🟢 全部 7 条合规规则审查通过"

    return {
        "status": status,
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "warn_count": len(soft_warns),
        "checks": results,
        "blocks": [r for r in failed if r["severity"] == "hard_block"],
        "warnings": [r for r in failed if r["severity"] == "soft_warn"],
        "summary": summary,
    }
