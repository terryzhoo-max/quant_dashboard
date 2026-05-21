"""
AlphaCore · 风险关联矩阵 (Risk Matrix)
========================================
从 decision_engine.py 拆分: 策略重叠分析 + 板块集中度 + 尾部风险仪表

O1 Refactor: 独立子模块
"""

from services.logger import get_logger
from dashboard_modules.decision.snapshot import _build_snapshot_from_cache
from dashboard_modules.decision.conflicts import compute_conflict_matrix

logger = get_logger("ac.decision.risk_matrix")


def compute_risk_matrix() -> dict:
    """
    风险关联矩阵:
    1. 策略标的重叠分析 (Jaccard Index)
    2. 板块集中度
    3. 尾部风险仪表
    """
    from services.cache_service import cache_manager

    strategy_results = cache_manager.get_json("strategy_results") or {}

    # 提取各策略买入标的集合
    strategy_codes = {}
    strategy_sectors = {}
    for sname in ["mr", "div", "mom"]:
        sdata = strategy_results.get(sname, {})
        if isinstance(sdata, dict):
            signals = sdata.get("data", {}).get("buy_signals", [])
            codes = set()
            sectors = {}
            for s in signals:
                code = s.get("ts_code") or s.get("code", "")
                if code:
                    codes.add(code)
                sector = s.get("group") or s.get("sector", "other")
                sectors[sector] = sectors.get(sector, 0) + 1
            strategy_codes[sname] = codes
            strategy_sectors[sname] = sectors

    # 1. Jaccard 重叠矩阵
    strat_names = list(strategy_codes.keys())
    overlap_matrix = []
    for i, a in enumerate(strat_names):
        row = []
        for j, b in enumerate(strat_names):
            sa, sb = strategy_codes.get(a, set()), strategy_codes.get(b, set())
            if i == j:
                row.append({"pair": f"{a}-{b}", "jaccard": 1.0, "shared": len(sa)})
            elif len(sa | sb) > 0:
                jaccard = round(len(sa & sb) / len(sa | sb), 3)
                row.append({"pair": f"{a}-{b}", "jaccard": jaccard, "shared": len(sa & sb)})
            else:
                row.append({"pair": f"{a}-{b}", "jaccard": 0, "shared": 0})
        overlap_matrix.append(row)

    # 共有标的列表
    all_codes = set()
    for codes in strategy_codes.values():
        all_codes |= codes
    multi_strategy_codes = []
    for code in all_codes:
        in_strats = [s for s, c in strategy_codes.items() if code in c]
        if len(in_strats) >= 2:
            multi_strategy_codes.append({"code": code, "strategies": in_strats, "count": len(in_strats)})
    multi_strategy_codes.sort(key=lambda x: x["count"], reverse=True)

    # 2. 板块集中度 (V19.2: 实际持仓优先, 策略信号回退)
    strat_labels = {"mr": "MR趋势", "div": "红利", "mom": "动量"}
    data_source = "signal"

    # ── 尝试从实际持仓读取 (市值加权 — 真实风险暴露) ──
    portfolio_sectors = {}
    portfolio_count = 0
    try:
        from portfolio_engine import get_portfolio_engine
        _pe = get_portfolio_engine()
        _val = _pe.get_valuation()
        _positions = _val.get("positions", [])
        if _positions:
            for p in _positions:
                industry = p.get("industry", "其他")
                weight = float(p.get("weight", 0))
                portfolio_sectors[industry] = portfolio_sectors.get(industry, 0) + weight
            portfolio_count = len(_positions)
            if portfolio_sectors:
                data_source = "portfolio"
    except Exception as e:
        logger.debug("板块集中度: 持仓读取失败, 回退策略信号: %s", e)

    if data_source == "portfolio":
        # 实际持仓路径 (市值权重)
        total_weight = sum(portfolio_sectors.values()) or 1
        sector_concentration = []
        for sec, w in sorted(portfolio_sectors.items(), key=lambda x: x[1], reverse=True)[:8]:
            pct = round(w / total_weight * 100, 1)
            sector_concentration.append({
                "sector": sec, "count": 0, "pct": pct, "sources": ["实际持仓"],
            })
        top_sector_pct = sector_concentration[0]["pct"] if sector_concentration else 0
        total_signals = portfolio_count
    else:
        # 回退路径: 策略信号 (等权计数)
        all_sectors = {}
        sector_sources = {}
        for sname, sectors in strategy_sectors.items():
            for sec, cnt in sectors.items():
                all_sectors[sec] = all_sectors.get(sec, 0) + cnt
                if sname not in sector_sources.setdefault(sec, []):
                    sector_sources[sec].append(sname)
        total_signals = sum(all_sectors.values()) or 1
        sector_concentration = []
        for sec, cnt in sorted(all_sectors.items(), key=lambda x: x[1], reverse=True)[:8]:
            pct = round(cnt / total_signals * 100, 1)
            sources = [strat_labels.get(s, s) for s in sector_sources.get(sec, [])]
            sector_concentration.append({
                "sector": sec, "count": cnt, "pct": pct, "sources": sources,
            })
        top_sector_pct = sector_concentration[0]["pct"] if sector_concentration else 0

    # HHI: 赫芬达尔指数 (0-10000, >2500 高集中)
    hhi = round(sum(s["pct"] ** 2 for s in sector_concentration))

    # 3. 尾部风险仪表 (综合: 集中度 + VIX + AIAE + 矛盾)
    snapshot = _build_snapshot_from_cache()
    vix = snapshot.get("vix_val", 20) or 20
    conflicts = compute_conflict_matrix(snapshot)

    # 尾部风险公式: 0-100 (V19.1: 参数校准 + 权重重分配)

    # 集中度 — 20%以下健康, 100%满分; 信号池<5时衰减防虚高
    concentration_risk = min(100, max(0, (top_sector_pct - 20) * 1.25))
    if total_signals < 5:
        concentration_risk *= total_signals / 5

    # VIX — 不变 (15→0, 40→100)
    vix_risk = min(100, max(0, (vix - 15) * 4))

    # V19.1: AIAE 连续值映射 (10%→0, 25%→50, 40%→100), 取代粗糙5级离散
    aiae_v1 = snapshot.get("aiae_v1") or 22
    aiae_risk = min(100, max(0, (aiae_v1 - 10) / 30 * 100))

    # 矛盾 — 不变
    conflict_risk = min(100, conflicts["conflict_count"] * 30)

    # V19.1: 权重重分配 — AIAE结构性风险提权, VIX情绪噪声降权
    tail_risk = round(
        concentration_risk * 0.30 +
        vix_risk * 0.20 +          # 30→20: VIX 是短期情绪指标
        aiae_risk * 0.35 +         # 25→35: AIAE 是核心宏观风险锚
        conflict_risk * 0.15, 1
    )

    if tail_risk >= 70:
        tail_level, tail_label = "high", "🔴 尾部风险偏高"
    elif tail_risk >= 40:
        tail_level, tail_label = "medium", "🟡 尾部风险中等"
    else:
        tail_level, tail_label = "low", "🟢 尾部风险可控"

    return {
        "strategy_names": strat_names,
        "overlap_matrix": overlap_matrix,
        "multi_strategy_codes": multi_strategy_codes[:10],
        "sector_concentration": sector_concentration,
        "top_sector_pct": top_sector_pct,
        "hhi": hhi,
        "total_signals": total_signals,
        "data_source": data_source,
        "tail_risk": {
            "score": tail_risk,
            "level": tail_level,
            "label": tail_label,
            "components": {
                "concentration": round(concentration_risk, 1),
                "vix": round(vix_risk, 1),
                "aiae": round(aiae_risk, 1),
                "conflict": round(conflict_risk, 1),
            },
        },
    }
