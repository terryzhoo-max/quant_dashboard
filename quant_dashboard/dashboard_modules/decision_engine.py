"""
AlphaCore V16.0 · 决策智能中枢 (Decision Intelligence Hub)
==========================================================
核心功能:
  - 信号矛盾检测器 (Conflict Detector)
  - 联合置信度引擎 (Joint Confidence Score / JCS)
  - 情景模拟器 (Scenario Simulator) — 纯数学推演, 零API调用
  - 每日决策快照写入 SQLite

数据来源: 100% 从缓存读取, 不直接调用任何引擎
"""

import copy
import math
import json
from datetime import datetime
from typing import Dict, List, Optional
from services.logger import get_logger

logger = get_logger("ac.decision")


# ═══════════════════════════════════════════════════════════
#  预设情景库 (6 个核心情景)
# ═══════════════════════════════════════════════════════════

SCENARIOS = {
    "vix_spike_40": {
        "name": "VIX 暴涨至 40",
        "desc": "全球恐慌指数飙升至极端水平，触发风控降级",
        "icon": "🌪️",
        "severity": "extreme",
        "deltas": {"vix_val": 40},
    },
    "erp_extreme_bull": {
        "name": "ERP 突破 7%",
        "desc": "股票相对债券极度低估，历史级别买入机会",
        "icon": "💎",
        "severity": "high",
        "deltas": {"erp_val": 7.2, "erp_score": 95},
    },
    "aiae_overheat_v": {
        "name": "AIAE 进入 Ⅴ 级",
        "desc": "市场配置热度达到极端过热，全策略大幅降权",
        "icon": "🔥",
        "severity": "extreme",
        "deltas": {"aiae_regime": 5, "aiae_v1": 35.0},
    },
    "rate_cut_50bp": {
        "name": "降息 50bps",
        "desc": "央行紧急降息，流动性大幅宽松",
        "icon": "📉",
        "severity": "high",
        "deltas": {"vix_val": 15},  # 降息通常伴随 VIX 回落
    },
    "liquidity_crisis": {
        "name": "流动性熔断",
        "desc": "个股跌停占比 >10%，触发流动性熔断机制",
        "icon": "🚨",
        "severity": "extreme",
        "deltas": {"vix_val": 45, "is_circuit_breaker": True},
    },
    "golden_cross": {
        "name": "黄金买点",
        "desc": "多引擎同步看多：AIAE冷 + ERP极高 + VIX低",
        "icon": "🏆",
        "severity": "positive",
        "deltas": {"aiae_regime": 1, "erp_val": 6.8, "erp_score": 88, "vix_val": 14},
    },
}


# ═══════════════════════════════════════════════════════════
#  信号矛盾检测器
# ═══════════════════════════════════════════════════════════

# 矛盾规则定义: (引擎A条件, 引擎B条件, 严重度, 描述, 建议)
_CONFLICT_RULES = [
    {
        "id": "aiae_vs_erp_bull",
        "a_check": lambda s: s.get("aiae_regime", 3) >= 4,
        "b_check": lambda s: s.get("erp_score", 50) > 65,
        "severity": "medium",
        "desc": "AIAE偏热(减仓) × ERP看多(加仓)",
        "action": "以AIAE为锚，ERP仅作估值参考，不追加仓位",
    },
    {
        "id": "aiae_vs_erp_bear",
        "a_check": lambda s: s.get("aiae_regime", 3) <= 2,
        "b_check": lambda s: s.get("erp_score", 50) < 35,
        "severity": "medium",
        "desc": "AIAE偏冷(加仓) × ERP看空(减仓)",
        "action": "AIAE主导方向，但控制单次加仓幅度，分批建仓",
    },
    {
        "id": "vix_vs_aiae_cold",
        "a_check": lambda s: s.get("vix_val", 20) >= 30,
        "b_check": lambda s: s.get("aiae_regime", 3) <= 2,
        "severity": "high",
        "desc": "VIX恐慌(撤退) × AIAE冷配区(建仓)",
        "action": "等待VIX回落至25以下再执行AIAE建仓信号",
    },
    {
        "id": "vix_vs_erp_bull",
        "a_check": lambda s: s.get("vix_val", 20) >= 35,
        "b_check": lambda s: s.get("erp_score", 50) > 70,
        "severity": "high",
        "desc": "VIX极端恐慌 × ERP极度低估",
        "action": "经典左侧信号，可小仓位试探但需严格止损",
    },
    {
        "id": "mr_crash_vs_erp",
        "a_check": lambda s: s.get("mr_regime", "RANGE") == "CRASH",
        "b_check": lambda s: s.get("erp_score", 50) > 65,
        "severity": "medium",
        "desc": "MR技术面崩盘 × ERP估值便宜",
        "action": "技术面优先，等待MR转RANGE后再考虑ERP加仓信号",
    },
]


def compute_conflict_matrix(snapshot: dict) -> dict:
    """
    扫描所有矛盾规则，返回:
    {
        "conflicts": [{id, severity, desc, action}],
        "conflict_count": int,
        "has_severe": bool,
        "matrix_summary": str
    }
    """
    conflicts = []
    for rule in _CONFLICT_RULES:
        try:
            if rule["a_check"](snapshot) and rule["b_check"](snapshot):
                conflicts.append({
                    "id": rule["id"],
                    "severity": rule["severity"],
                    "desc": rule["desc"],
                    "action": rule["action"],
                })
        except Exception:
            continue

    has_severe = any(c["severity"] == "high" for c in conflicts)
    count = len(conflicts)

    if count == 0:
        summary = "🟢 所有引擎方向一致，无矛盾信号"
    elif has_severe:
        summary = f"🔴 检测到 {count} 个矛盾 (含严重矛盾)，建议保持防御"
    else:
        summary = f"🟡 检测到 {count} 个中度矛盾，适度降低仓位"

    return {
        "conflicts": conflicts,
        "conflict_count": count,
        "has_severe": has_severe,
        "matrix_summary": summary,
    }


# ═══════════════════════════════════════════════════════════
#  联合置信度引擎 (JCS)
# ═══════════════════════════════════════════════════════════

# 引擎权重
_JCS_WEIGHTS = {
    "aiae": 0.35,
    "erp": 0.25,
    "vix": 0.15,
    "mr": 0.15,
    "degraded": 0.10,  # 数据完整度惩罚项
}


def _signal_direction(snapshot: dict) -> dict:
    """将各引擎状态映射为方向: +1(看多), 0(中性), -1(看空)"""
    aiae_r = snapshot.get("aiae_regime", 3)
    erp_s = snapshot.get("erp_score", 50)
    vix_v = snapshot.get("vix_val", 20)
    mr_r = snapshot.get("mr_regime", "RANGE")

    return {
        "aiae": 1 if aiae_r <= 2 else (-1 if aiae_r >= 4 else 0),
        "erp": 1 if erp_s > 60 else (-1 if erp_s < 40 else 0),
        "vix": 1 if vix_v < 18 else (-1 if vix_v > 28 else 0),
        "mr": 1 if mr_r == "BULL" else (-1 if mr_r in ("BEAR", "CRASH") else 0),
    }


def compute_jcs(snapshot: dict) -> dict:
    """
    联合置信度引擎:
    JCS = Direction_Agreement × Data_Freshness × Engine_Health

    返回:
    {
        "score": 0-100,
        "level": "high" / "medium" / "low",
        "label": str,
        "directions": {engine: direction},
        "agreement_pct": float,
        "freshness_factor": float,
        "health_factor": float,
    }
    """
    directions = _signal_direction(snapshot)

    # 1. Direction Agreement (方向一致性)
    # 计算加权方向得分的绝对值 (0-1, 越高越一致)
    weighted_sum = (
        directions["aiae"] * _JCS_WEIGHTS["aiae"] +
        directions["erp"] * _JCS_WEIGHTS["erp"] +
        directions["vix"] * _JCS_WEIGHTS["vix"] +
        directions["mr"] * _JCS_WEIGHTS["mr"]
    )
    # 归一化到 0-1 (最大值 = 所有方向相同 × 权重和)
    max_weight = sum(v for k, v in _JCS_WEIGHTS.items() if k != "degraded")
    agreement = abs(weighted_sum) / max_weight if max_weight > 0 else 0

    # 2. Data Freshness (数据新鲜度)
    # 简化版: 检查各引擎是否有有效数据
    stale_count = 0
    if snapshot.get("aiae_regime") is None:
        stale_count += 1
    if snapshot.get("erp_score") is None:
        stale_count += 1
    if snapshot.get("vix_val") is None:
        stale_count += 1
    freshness = 1.0 - (stale_count / 4.0) * 0.3

    # 3. Engine Health (引擎健康度)
    degraded = snapshot.get("degraded_modules", [])
    if isinstance(degraded, str):
        degraded = [d.strip() for d in degraded.split(",") if d.strip()]
    health = max(0.4, 1.0 - len(degraded) * 0.12)

    # 合成 JCS (0-100)
    raw_jcs = agreement * freshness * health * 100
    jcs = round(min(100, max(0, raw_jcs)), 1)

    # 矛盾惩罚
    conflicts = compute_conflict_matrix(snapshot)
    if conflicts["has_severe"]:
        jcs = round(jcs * 0.6, 1)
    elif conflicts["conflict_count"] > 0:
        jcs = round(jcs * 0.8, 1)

    # 分级
    if jcs >= 70:
        level, label = "high", "🟢 高置信 — 多引擎方向一致"
    elif jcs >= 40:
        level, label = "medium", "🟡 中置信 — 存在分歧或部分降级"
    else:
        level, label = "low", "🔴 低置信 — 严重矛盾或数据缺失，建议观望"

    return {
        "score": jcs,
        "level": level,
        "label": label,
        "directions": directions,
        "agreement_pct": round(agreement * 100, 1),
        "freshness_factor": round(freshness, 2),
        "health_factor": round(health, 2),
        "conflict_count": conflicts["conflict_count"],
    }


# ═══════════════════════════════════════════════════════════
#  情景模拟器 (纯数学, 零 API 调用)
# ═══════════════════════════════════════════════════════════

# AIAE Regime → Cap 映射 (复用 aiae_engine.py 的 REGIMES)
_REGIME_CAP_MAP = {1: 90, 2: 70, 3: 55, 4: 35, 5: 15}
_REGIME_CN_MAP = {1: "极度恐慌", 2: "低配置区", 3: "中性均衡", 4: "偏热区域", 5: "极度过热"}


def _recalc_vix_score(vix_val: float) -> float:
    """复用 market_temp.py 的 VIX Sigmoid 公式"""
    _x = max(-20, min(20, -0.15 * (vix_val - 20.0)))
    return round(100.0 / (1.0 + math.exp(-_x)), 1)


def _recalc_hub_composite(snapshot: dict) -> float:
    """复用 market_temp.py 的六因子加权 composite 公式"""
    aiae_regime = snapshot.get("aiae_regime", 3)
    erp_score = snapshot.get("erp_score", 50)
    vix_score = snapshot.get("vix_score", 50)
    liquidity = snapshot.get("liquidity_score", 50)
    macro_temp = snapshot.get("macro_temp_score", 50)

    hub_aiae = round(max(10, 100 - (aiae_regime - 1) * 22.5), 1)
    composite = round(
        hub_aiae * 0.40 +
        erp_score * 0.25 +
        vix_score * 0.15 +
        liquidity * 0.10 +
        macro_temp * 0.10, 1
    )
    return composite


def simulate_scenario(scenario_id: str, current_snapshot: dict) -> dict:
    """
    纯数学情景推演:
    1. 深拷贝当前快照
    2. 应用情景 delta
    3. 重算受影响的衍生指标
    4. 返回 before/after 对比
    """
    if scenario_id not in SCENARIOS:
        return {"error": f"未知情景: {scenario_id}"}

    scenario = SCENARIOS[scenario_id]
    deltas = scenario["deltas"]

    before = copy.deepcopy(current_snapshot)
    after = copy.deepcopy(current_snapshot)

    # 应用 delta
    for key, val in deltas.items():
        after[key] = val

    # 重算受影响的衍生指标
    if "vix_val" in deltas:
        after["vix_score"] = _recalc_vix_score(after["vix_val"])

    if "aiae_regime" in deltas:
        new_regime = deltas["aiae_regime"]
        after["suggested_position"] = _REGIME_CAP_MAP.get(new_regime, 55)
        after["aiae_regime_cn"] = _REGIME_CN_MAP.get(new_regime, "中性均衡")

    if deltas.get("is_circuit_breaker"):
        after["suggested_position"] = 0
        after["is_circuit_breaker"] = True

    # 重算 hub composite
    after["hub_composite"] = _recalc_hub_composite(after)
    before["hub_composite"] = _recalc_hub_composite(before)

    # 重算 JCS
    jcs_before = compute_jcs(before)
    jcs_after = compute_jcs(after)

    # 影响摘要
    pos_before = before.get("suggested_position", 55)
    pos_after = after.get("suggested_position", pos_before)
    pos_delta = pos_after - pos_before

    impact_items = []
    if pos_delta != 0:
        direction = "↓" if pos_delta < 0 else "↑"
        impact_items.append(f"仓位 {pos_before}% → {pos_after}% ({direction}{abs(pos_delta)}%)")
    if jcs_after["score"] != jcs_before["score"]:
        impact_items.append(f"JCS {jcs_before['score']} → {jcs_after['score']}")
    if after.get("hub_composite", 0) != before.get("hub_composite", 0):
        impact_items.append(f"Composite {before.get('hub_composite', 0)} → {after.get('hub_composite', 0)}")

    return {
        "scenario": {
            "id": scenario_id,
            "name": scenario["name"],
            "desc": scenario["desc"],
            "icon": scenario["icon"],
            "severity": scenario["severity"],
        },
        "before": {
            "aiae_regime": before.get("aiae_regime"),
            "erp_score": before.get("erp_score"),
            "erp_val": before.get("erp_val"),
            "vix_val": before.get("vix_val"),
            "vix_score": before.get("vix_score"),
            "suggested_position": pos_before,
            "hub_composite": before.get("hub_composite"),
            "jcs": jcs_before["score"],
            "jcs_level": jcs_before["level"],
        },
        "after": {
            "aiae_regime": after.get("aiae_regime"),
            "erp_score": after.get("erp_score"),
            "erp_val": after.get("erp_val"),
            "vix_val": after.get("vix_val"),
            "vix_score": after.get("vix_score"),
            "suggested_position": pos_after,
            "hub_composite": after.get("hub_composite"),
            "jcs": jcs_after["score"],
            "jcs_level": jcs_after["level"],
        },
        "impact": impact_items,
        "position_delta": pos_delta,
    }


# ═══════════════════════════════════════════════════════════
#  决策中枢主入口 + 每日快照
# ═══════════════════════════════════════════════════════════

def _build_snapshot_from_cache() -> dict:
    """从缓存组装当前系统快照 (不调引擎, 纯读取)"""
    from services.cache_service import cache_manager

    snapshot = {}

    # Dashboard 数据 (含市场温度、VIX、ERP 等)
    dashboard = cache_manager.get_json("dashboard_data")
    if dashboard and dashboard.get("data"):
        d = dashboard["data"]
        macro = d.get("macro_cards", {})
        hub = d.get("hub", {})
        temp = d.get("temperature", {})

        snapshot["vix_val"] = macro.get("vix", {}).get("value")
        snapshot["erp_val"] = macro.get("erp", {}).get("value")
        snapshot["erp_score"] = hub.get("factors", {}).get("erp_value", {}).get("score", 50)
        snapshot["vix_score"] = hub.get("factors", {}).get("vix_fear", {}).get("score", 50)
        snapshot["liquidity_score"] = hub.get("factors", {}).get("capital_flow", {}).get("score", 50)
        snapshot["macro_temp_score"] = hub.get("factors", {}).get("macro_temp", {}).get("score", 50)
        snapshot["hub_composite"] = hub.get("composite_score", 50)
        snapshot["suggested_position"] = hub.get("position", 55)
        snapshot["degraded_modules"] = temp.get("degraded_modules", [])

    # AIAE 上下文
    aiae_ctx = cache_manager.get_json("aiae_ctx")
    if aiae_ctx:
        snapshot["aiae_regime"] = aiae_ctx.get("regime", 3)
        snapshot["aiae_v1"] = aiae_ctx.get("aiae_v1", 22)

    # 策略结果
    strategy_results = cache_manager.get_json("strategy_results") or {}
    mr_data = strategy_results.get("mr", {})
    if isinstance(mr_data, dict):
        mr_ov = mr_data.get("data", {}).get("market_overview", {})
        mr_regime = mr_ov.get("regime", "RANGE") if mr_ov else "RANGE"
    else:
        mr_regime = "RANGE"
    snapshot["mr_regime"] = mr_regime

    return snapshot


def get_hub_data() -> dict:
    """决策中枢全量数据 (供 API 返回)"""
    snapshot = _build_snapshot_from_cache()

    conflicts = compute_conflict_matrix(snapshot)
    jcs = compute_jcs(snapshot)

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "snapshot": snapshot,
        "conflicts": conflicts,
        "jcs": jcs,
        "scenarios": {k: {"name": v["name"], "desc": v["desc"], "icon": v["icon"], "severity": v["severity"]}
                      for k, v in SCENARIOS.items()},
    }


def log_daily_decision():
    """每日收盘快照写入 SQLite (由 warmup_pipeline 调用)"""
    from services import db as ac_db

    snapshot = _build_snapshot_from_cache()
    if not snapshot.get("aiae_regime"):
        logger.warning("决策快照跳过: 缓存数据不完整")
        return

    jcs = compute_jcs(snapshot)
    conflicts = compute_conflict_matrix(snapshot)

    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "aiae_regime": snapshot.get("aiae_regime"),
        "aiae_v1": snapshot.get("aiae_v1"),
        "erp_score": snapshot.get("erp_score"),
        "erp_val": snapshot.get("erp_val"),
        "vix_val": snapshot.get("vix_val"),
        "mr_regime": snapshot.get("mr_regime"),
        "hub_composite": snapshot.get("hub_composite"),
        "jcs_score": jcs["score"],
        "jcs_level": jcs["level"],
        "suggested_position": snapshot.get("suggested_position"),
        "conflict_count": conflicts["conflict_count"],
        "degraded_modules": ",".join(snapshot.get("degraded_modules", [])) if isinstance(snapshot.get("degraded_modules"), list) else str(snapshot.get("degraded_modules", "")),
    }

    ac_db.upsert_decision_log(data)
    ac_db.cleanup_old_decisions(365)
    logger.info("决策快照存档: JCS=%.1f (%s) conflicts=%d pos=%s%%",
                jcs["score"], jcs["level"], conflicts["conflict_count"],
                snapshot.get("suggested_position", "?"))


# ═══════════════════════════════════════════════════════════
#  Phase 2: 风险关联矩阵
# ═══════════════════════════════════════════════════════════

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

    # 2. 板块集中度
    all_sectors = {}
    for sectors in strategy_sectors.values():
        for sec, cnt in sectors.items():
            all_sectors[sec] = all_sectors.get(sec, 0) + cnt
    total_signals = sum(all_sectors.values()) or 1
    sector_concentration = []
    for sec, cnt in sorted(all_sectors.items(), key=lambda x: x[1], reverse=True)[:8]:
        sector_concentration.append({
            "sector": sec, "count": cnt,
            "pct": round(cnt / total_signals * 100, 1),
        })
    top_sector_pct = sector_concentration[0]["pct"] if sector_concentration else 0

    # 3. 尾部风险仪表 (综合: 集中度 + VIX + 矛盾)
    snapshot = _build_snapshot_from_cache()
    vix = snapshot.get("vix_val", 20) or 20
    conflicts = compute_conflict_matrix(snapshot)

    # 尾部风险公式: 0-100
    concentration_risk = min(100, top_sector_pct * 1.5)  # 集中度超 60% 满分
    vix_risk = min(100, max(0, (vix - 15) * 4))  # VIX 15→0, 40→100
    conflict_risk = min(100, conflicts["conflict_count"] * 30)  # 每个矛盾 30 分
    tail_risk = round(concentration_risk * 0.4 + vix_risk * 0.4 + conflict_risk * 0.2, 1)

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
        "tail_risk": {
            "score": tail_risk,
            "level": tail_level,
            "label": tail_label,
            "components": {
                "concentration": round(concentration_risk, 1),
                "vix": round(vix_risk, 1),
                "conflict": round(conflict_risk, 1),
            },
        },
    }


# ═══════════════════════════════════════════════════════════
#  Phase 2: 准确率回填 (T+5 市场收益)
# ═══════════════════════════════════════════════════════════

def backfill_signal_accuracy():
    """
    检查 5 天前的决策记录是否已回填市场收益。
    如果未回填，尝试从缓存中获取市场数据计算 T+5 收益。
    """
    from services import db as ac_db
    from services.cache_service import cache_manager
    from datetime import timedelta

    # 查找 5-10 天前未回填的记录
    today = datetime.now()
    conn = ac_db._get_conn()
    rows = conn.execute(
        "SELECT date FROM decision_log WHERE market_return_5d IS NULL "
        "AND date <= ? ORDER BY date DESC LIMIT 10",
        ((today - timedelta(days=5)).strftime("%Y-%m-%d"),)
    ).fetchall()

    if not rows:
        return

    # 尝试从 dashboard 缓存获取当前市场温度作为近似收益指标
    dashboard = cache_manager.get_json("dashboard_data")
    if not dashboard or not dashboard.get("data"):
        return

    # 使用 ERP 变化作为市场方向的代理
    macro = dashboard.get("data", {}).get("macro_cards", {})
    erp_change = macro.get("erp", {}).get("change")
    if erp_change is None:
        return

    # 简化: 用当前 ERP 变化作为 T+5 收益的近似 (方向性判断)
    # 更精确的方法需要接入真实行情API，这里先用代理指标
    for row in rows:
        log_date = row[0]
        # 这里使用一个简化的收益估算
        # 实际生产中应对接 Tushare 指数日线来获取真实收益
        approx_return = round(erp_change * 0.5, 4)  # 简化近似
        ac_db.backfill_accuracy(log_date, approx_return)
        logger.info("准确率回填: %s -> return_5d=%.4f", log_date, approx_return)

