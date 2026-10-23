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
    if snapshot.get("decision_locked") is True:
        return False, "AIAE 数据缺失、陈旧或质量不足，决策已锁定"
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


def _vol_budget_enforced() -> bool:
    try:
        from services.portfolio_vol import load_portfolio_vol_config
        return bool(load_portfolio_vol_config().get("enforce_in_compliance", False))
    except Exception:
        return False


def _check_vol_budget(snapshot, positions, ctx):
    """组合波动预算: 当前权益仓位 vs 目标波动对应的最大仓位.

    数据来自 Dashboard 构建时缓存的 vol_budget (或 context/snapshot 直接传入)。
    超出 10pp 以上判为不通过; 严重级别由 vol_targeting.portfolio.enforce_in_compliance 决定。
    """
    vb = (ctx or {}).get("vol_budget") or snapshot.get("vol_budget")
    if vb is None:
        try:
            from services.cache_service import cache_manager
            vb = cache_manager.get_json("vol_budget")
        except Exception:
            vb = None
    if not isinstance(vb, dict) or vb.get("max_equity_pct") is None or vb.get("invested_pct") is None:
        return True, "无组合波动预算数据, 跳过检查"
    try:
        invested = float(vb["invested_pct"])
        max_eq = float(vb["max_equity_pct"])
        pvol = float(vb.get("portfolio_vol") or 0) * 100
        tvol = float(vb.get("target_vol") or 0) * 100
    except (TypeError, ValueError):
        return True, "组合波动预算数据无效, 跳过检查"
    excess = invested - max_eq
    if excess > 10:
        return False, (f"组合年化波动 {pvol:.0f}% > 目标 {tvol:.0f}%: 当前仓位 {invested:.0f}% "
                       f"超出波动预算上限 {max_eq:.0f}% 达 {excess:.0f}pp. 禁止加仓, 按减仓草案分批降低.")
    if excess > 0:
        return True, f"仓位 {invested:.0f}% 略超波动预算上限 {max_eq:.0f}% ({excess:.0f}pp), 不宜加仓"
    return True, f"组合年化波动 {pvol:.0f}% 在目标 {tvol:.0f}% 以内"


class _VolBudgetRule(ComplianceRule):
    """严重级别随配置切换: 用户确认目标波动后 (enforce_in_compliance=true) 升级为硬阻断."""

    def check(self, snapshot: dict, positions: list = None, context: dict = None) -> dict:
        self.severity = "hard_block" if _vol_budget_enforced() else "soft_warn"
        return super().check(snapshot, positions, context)


def _trailing_breaches(snapshot, ctx):
    rep = (ctx or {}).get("trailing_stop") or snapshot.get("trailing_stop")
    if rep is None:
        try:
            from services.cache_service import cache_manager
            rep = cache_manager.get_json("trailing_stop_report")
        except Exception:
            rep = None
    if not isinstance(rep, dict) or not isinstance(rep.get("positions"), list):
        return None
    red = [p for p in rep["positions"] if p.get("status") == "RED"]
    legacy = [p for p in rep["positions"] if p.get("status") == "LEGACY"]
    return red, legacy


def _check_stop_breach_no_add(snapshot, positions, ctx):
    """越过止损线的持仓禁止加仓 (跟踪止盈引擎: RED 已触发未执行 / LEGACY 跟踪前越线未决策)。"""
    if ctx and ctx.get("direction") in ("sell", "reduce"):
        return True, "减仓操作, 不受限制"
    res = _trailing_breaches(snapshot, ctx)
    if res is None:
        return True, "无跟踪止盈数据, 跳过检查"
    red, legacy = res
    names = lambda xs: ", ".join(p.get("name", p.get("ts_code", "?")) for p in xs[:4])
    if red:
        return False, f"已触发止损未执行: {names(red)} — 先执行卖出, 禁止对其加仓"
    if legacy:
        return False, f"跟踪前已越线、尚未决策: {names(legacy)} — 先止损或重新基准化, 期间禁止加仓"
    return True, "无越线持仓"


class _StopBreachRule(ComplianceRule):
    """有已触发未执行 (RED) → 硬阻断; 仅有遗留待决 (LEGACY) → 软警告。"""

    def check(self, snapshot: dict, positions: list = None, context: dict = None) -> dict:
        res = None
        try:
            res = _trailing_breaches(snapshot, context)
        except Exception:
            pass
        self.severity = "hard_block" if (res and res[0]) else "soft_warn"
        return super().check(snapshot, positions, context)


def _drawdown_brake_state(snapshot, ctx):
    b = (ctx or {}).get("drawdown_brake") or snapshot.get("drawdown_brake")
    if b is None:
        try:
            from services.cache_service import cache_manager
            b = cache_manager.get_json("drawdown_brake")
        except Exception:
            b = None
    return b if isinstance(b, dict) and b.get("tier") is not None else None


def _dd_lag(b):
    try:
        from services.drawdown_service import is_stale
        return is_stale(b)
    except Exception:
        return None


class _DrawdownBrakeRule(ComplianceRule):
    """档位 ≥1 → 硬阻断; 数据过期 (>3 个交易日) → 软警告 (不因数据缺失而静默放行, 也不因此硬阻断)。"""

    def check(self, snapshot: dict, positions: list = None, context: dict = None) -> dict:
        b = None
        try:
            b = _drawdown_brake_state(snapshot, context)
        except Exception:
            pass
        lag = _dd_lag(b) if b else None
        self.severity = "soft_warn" if (lag is not None and lag > 3) else "hard_block"
        return super().check(snapshot, positions, context)


def _check_drawdown_brake(snapshot, positions, ctx):
    """组合级回撤刹车: 剔除资金进出的组合净值自高点回撤 ≥ 12% 起分档降仓上限, 期间禁止新增买入。"""
    if ctx and ctx.get("direction") in ("sell", "reduce"):
        return True, "减仓操作, 不受限制"
    b = _drawdown_brake_state(snapshot, ctx)
    if b is None:
        return True, "无组合回撤数据, 跳过检查"
    lag = _dd_lag(b)
    if lag is not None and lag > 3:
        return False, f"组合回撤数据已 {lag} 个交易日未更新 (截至 {b.get('as_of')}), 刹车状态不可信 — 请先「同步并重算」"
    dd = abs(b.get("dd") or 0)
    if not b.get("tier"):
        return True, f"组合回撤 {dd:.1%}, 未触发刹车"
    msg = f"组合回撤 {dd:.1%} · {b.get('label')} — 仓位上限 {b.get('cap_pct')}%, 回撤恢复前禁止新增买入"
    if b.get("reduce_value"):
        msg += f"; 当前 {b.get('invested_pct')}%, 需先降仓约 ¥{b['reduce_value']:,.0f}"
    return False, msg


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
    _VolBudgetRule("vol_budget", "组合波动预算", "soft_warn",
                   "当前仓位不得超过目标波动对应的最大仓位 10pp", _check_vol_budget),
    _StopBreachRule("stop_breach_no_add", "越线禁止加仓", "soft_warn",
                    "跌破跟踪止损线的持仓, 执行或决策前禁止加仓", _check_stop_breach_no_add),
    _DrawdownBrakeRule("drawdown_brake", "组合回撤刹车", "hard_block",
                   "组合净值回撤 ≥12/20/28% 分档降仓上限至 75/50/25%, 期间禁止加仓", _check_drawdown_brake),
]


# ═══════════════════════════════════════════════════════════
#  合规检查入口
# ═══════════════════════════════════════════════════════════

def run_compliance_check(snapshot: dict, positions: list = None,
                         context: dict = None) -> dict:
    """
    执行全部合规规则检查 (当前 10 条)。

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
        summary = f"🟢 全部 {len(results)} 条合规规则审查通过"

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
