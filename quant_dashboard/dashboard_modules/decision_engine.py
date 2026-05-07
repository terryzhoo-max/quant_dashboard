"""
AlphaCore V17.1 · 决策智能中枢 (Decision Intelligence Hub)
==========================================================
核心功能:
  - 信号矛盾检测器 (Conflict Detector)
  - 联合置信度引擎 (Joint Confidence Score / JCS) — V17.0 加法模型
  - 情景模拟器 (Scenario Simulator) — 纯数学推演, 零API调用
  - 执行建议生成器 (Action Plan Generator)
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
    # ── V17.0 新增规则 ──
    {
        "id": "mr_bull_vs_aiae_hot",
        "a_check": lambda s: s.get("mr_regime", "RANGE") == "BULL",
        "b_check": lambda s: s.get("aiae_regime", 3) >= 4,
        "severity": "high",
        "desc": "MR技术面看多 × AIAE配置过热(Ⅳ/Ⅴ)",
        "action": "技术面可能是最后一涨，AIAE为锚，严控追高仓位",
    },
    {
        "id": "all_neutral",
        "a_check": lambda s: all(d == 0 for d in _signal_direction(s).values()),
        "b_check": lambda s: True,
        "severity": "info",
        "desc": "所有引擎处于中性，无明确方向信号",
        "action": "维持现有仓位，等待信号出现再行动",
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

    # V19.3: 排除 info 级别 (如 all_neutral) — 不计入矛盾计数和前端 warn 状态
    actionable = [c for c in conflicts if c["severity"] != "info"]
    has_severe = any(c["severity"] == "high" for c in actionable)
    count = len(actionable)

    if count == 0:
        summary = "🟢 零矛盾信号，各引擎间无方向冲突"
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
#  联合置信度引擎 (JCS) — V17.0 加法模型
# ═══════════════════════════════════════════════════════════

# 引擎权重 (用于方向一致性加权)
_JCS_WEIGHTS = {
    "aiae": 0.35,   # V19.1: 主锚降权 (0.45→0.35), 月频滞后指标不应过半
    "erp": 0.25,    # 估值锚不变
    "vix": 0.20,    # V19.1: 提权 (0.15→0.20), 唯一实时情绪指标
    "mr": 0.20,     # V19.1: 提权 (0.15→0.20), 唯一价格结构指标
}


def _signal_direction(snapshot: dict) -> dict:
    """将各引擎状态映射为方向: +1(看多), 0(中性), -1(看空)"""
    aiae_r = snapshot.get("aiae_regime") or 3        # None → 中性
    erp_s = snapshot.get("erp_score") or 50          # None → 中性
    vix_v = snapshot.get("vix_val") or 20            # None → 中性
    mr_r = snapshot.get("mr_regime") or "RANGE"      # None → 中性

    return {
        "aiae": 1 if aiae_r <= 2 else (-1 if aiae_r >= 4 else 0),
        "erp": 1 if erp_s > 55 else (-1 if erp_s < 35 else 0),  # V19.1: 拓宽 (60/40→55/35, A股ERP分布校准)
        "vix": 1 if vix_v < 16 else (-1 if vix_v > 25 else 0),  # P1: 收窄阈值 (A股实证校准)
        "mr": 1 if mr_r == "BULL" else (-1 if mr_r in ("BEAR", "CRASH") else 0),
    }


def compute_jcs(snapshot: dict) -> dict:
    """
    V17.0 联合置信度引擎 (加法模型, 替代旧版乘法连乘):

    JCS = base_agreement (60%) + data_health (20%) + consensus_bonus (20%)

    旧版问题: agreement × freshness × health 三乘数连乘导致分值被压缩到 30-50 区间,
              "中置信" 成为常态, 丧失信号区分价值.

    返回:
    {
        "score": 0-100,
        "level": "high" / "medium" / "low",
        "label": str,
        "directions": {engine: direction},
        "agreement_pct": float,
        "data_health": float,
        "consensus_bonus": float,
        "conflict_count": int,
    }
    """
    directions = _signal_direction(snapshot)
    dir_vals = list(directions.values())  # [+1, 0, -1, ...]

    # ── 1. Base Agreement (占 60 分) ──
    # 有明确方向的引擎数量 (非中性)
    active_count = sum(1 for d in dir_vals if d != 0)
    # 所有有方向引擎的方向是否一致 (全+1 或全-1)
    active_dirs = [d for d in dir_vals if d != 0]
    if active_count == 0:
        # 全部中性 → 无信号, 基础分 30 (不应高也不应低)
        base_agreement = 30.0
    elif all(d == active_dirs[0] for d in active_dirs):
        # 所有有方向的引擎一致
        # 4引擎全一致=60, 3一致1中性=52, 2一致2中性=42
        base_agreement = 30.0 + active_count * 7.5
    else:
        # 存在方向对冲: 按加权方向计算衰减
        weighted_sum = sum(
            directions[k] * _JCS_WEIGHTS[k] for k in _JCS_WEIGHTS
        )
        max_weight = sum(_JCS_WEIGHTS.values())
        agreement_ratio = abs(weighted_sum) / max_weight if max_weight > 0 else 0
        # 对冲越严重分越低: 完全对冲→10, 弱对冲→25
        base_agreement = 10.0 + agreement_ratio * 20.0

    # V19.1: 中性距离加分 — 中性引擎的读数仍含信息量
    # VIX=16 (安全) vs VIX=24 (临界) 不应得分相同
    distance_bonus = 0.0
    if directions["vix"] == 0:
        vix_v = snapshot.get("vix_val", 20)
        # VIX 离恐慌线 (25) 越远越安全, 最多+2.5
        distance_bonus += max(0, (25 - vix_v) / 25) * 2.5
    if directions["erp"] == 0:
        erp_s = snapshot.get("erp_score", 50)
        # ERP 偏离中位 50 越远, 方向性越明确, 最多+2.5
        distance_bonus += abs(erp_s - 50) / 50 * 2.5
    base_agreement += min(distance_bonus, 5.0)  # 总距离分上限 5

    # ── 2. Data Health (占 20 分) ──
    stale_count = 0
    if snapshot.get("aiae_regime") is None:
        stale_count += 1
    if snapshot.get("erp_score") is None:
        stale_count += 1
    if snapshot.get("vix_val") is None:
        stale_count += 1
    if snapshot.get("mr_regime") is None:
        stale_count += 1

    degraded = snapshot.get("degraded_modules", [])
    if isinstance(degraded, str):
        degraded = [d.strip() for d in degraded.split(",") if d.strip()]
    degraded_count = len(degraded)

    # 每个缺失引擎扣 4 分, 每个降级模块扣 2 分
    data_health = max(0.0, 20.0 - stale_count * 4.0 - degraded_count * 2.0)

    # ── 3. Consensus Bonus (占 20 分) ──
    # 全方向一致且无中性 → +20; 有中性但无矛盾 → +10; 其他 → 0
    if active_count == 4 and all(d == active_dirs[0] for d in active_dirs):
        consensus_bonus = 20.0
    elif active_count >= 2 and all(d == active_dirs[0] for d in active_dirs):
        consensus_bonus = 10.0
    else:
        consensus_bonus = 0.0

    # ── 合成 JCS ──
    raw_jcs = base_agreement + data_health + consensus_bonus

    # ── 矛盾惩罚 (减法, 不再用乘法) ──
    # V22.0 O1: 直接复用 compute_conflict_matrix 已计算好的
    #          conflict_count/has_severe, 避免重复过滤
    conflicts = compute_conflict_matrix(snapshot)
    penalty_count = conflicts["conflict_count"]
    has_severe = conflicts["has_severe"]

    if has_severe:
        raw_jcs -= 25.0  # 严重矛盾扣 25 分
    elif penalty_count > 0:
        raw_jcs -= penalty_count * 10.0  # 每个中度矛盾扣 10 分

    jcs = round(min(100, max(0, raw_jcs)), 1)

    # ── 分级 ──
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
        "agreement_pct": min(100.0, round(base_agreement / 60.0 * 100, 1)),
        "data_health": round(data_health, 1),
        "consensus_bonus": round(consensus_bonus, 1),
        "conflict_count": conflicts["conflict_count"],
    }


# ═══════════════════════════════════════════════════════════
#  情景模拟器 (纯数学, 零 API 调用)
# ═══════════════════════════════════════════════════════════

# AIAE Regime → Cap 映射 (从 aiae_params.POSITION_MATRIX 动态读取, 取 erp_2_4 行)
try:
    from aiae_params import POSITION_MATRIX as _PM
    _REGIME_CAP_MAP = {i+1: _PM["erp_2_4"][i] for i in range(5)}
except ImportError:
    _REGIME_CAP_MAP = {1: 85, 2: 70, 3: 50, 4: 25, 5: 5}  # fallback
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

    # V17.0: ERP 值变化时联动重算 erp_score (Sigmoid 映射)
    if "erp_val" in deltas:
        erp_v = after["erp_val"]
        # 复用 ERP 绝对值→分位的近似映射: ERP 3%→20分, 4.5%→50分, 6%→80分
        _erp_x = max(-20, min(20, 2.5 * (erp_v - 4.5)))
        after["erp_score"] = round(100.0 / (1.0 + math.exp(-_erp_x)), 1)

    if deltas.get("is_circuit_breaker"):
        after["suggested_position"] = 0
        after["is_circuit_breaker"] = True
        # V17.0: 流动性熔断联动
        after["liquidity_score"] = 0
        after["macro_temp_score"] = max(0, after.get("macro_temp_score", 50) - 30)

    # P2: MR Regime 联动 — VIX 极端 / AIAE 过热时自动降级 MR 技术面
    if after.get("vix_val", 0) >= 35:
        after["mr_regime"] = "CRASH" if after["vix_val"] >= 45 else "BEAR"
    if after.get("aiae_regime", 3) >= 5 and after.get("mr_regime") == "BULL":
        after["mr_regime"] = "RANGE"  # 过热牛市末端降级
    # V20.0: ERP 极端低估 → MR 联动 (ERP>6.5% 意味着恐慌抛售, 技术面应降级)
    if after.get("erp_val", 4.5) >= 6.5 and after.get("mr_regime") == "BULL":
        after["mr_regime"] = "RANGE"  # 估值极端通常伴随技术面修正

    # 重算 hub composite
    after["hub_composite"] = _recalc_hub_composite(after)
    before["hub_composite"] = _recalc_hub_composite(before)

    # 重算 JCS
    jcs_before = compute_jcs(before)
    jcs_after = compute_jcs(after)

    # V19.3: 重算矛盾状态 (供影响摘要使用)
    conflicts_before = compute_conflict_matrix(before)
    conflicts_after = compute_conflict_matrix(after)

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
    # V19.3: 矛盾状态变化
    cc_b, cc_a = conflicts_before["conflict_count"], conflicts_after["conflict_count"]
    if cc_a != cc_b:
        impact_items.append(f"矛盾 {cc_b} → {cc_a} {'⚠️ 新增矛盾' if cc_a > cc_b else '✅ 矛盾消解'}")

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

def _parse_erp_value(raw) -> float:
    """安全解析 ERP 值: '4.5%' → 4.5, 4.5 → 4.5, None → 4.5"""
    if raw is None:
        return 4.5
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).replace('%', '').strip())
    except (ValueError, TypeError):
        return 4.5


def _build_snapshot_from_cache() -> dict:
    """
    V17.1: 从缓存组装当前系统快照 (不调引擎, 纯读取)
    
    缓存结构 (由 assemble_response.py 写入):
      data.macro_cards.vix.value          → vix_val (float)
      data.macro_cards.erp.value          → erp_val (字符串 '4.5%', 需解析)
      data.macro_cards.market_temp.hub_factors.{key}.score  → 各因子得分
      data.macro_cards.market_temp.hub_composite             → 综合得分
      data.macro_cards.regime_banner.aiae_cap                → 建议仓位
      data.macro_cards.market_temp.degraded_modules          → 降级模块
    """
    from services.cache_service import cache_manager

    snapshot = {}

    # Dashboard 数据 (V17.1: 修正读取路径, 从 macro_cards.market_temp 读取)
    dashboard = cache_manager.get_json("dashboard_data")
    if dashboard and dashboard.get("data"):
        d = dashboard["data"]
        macro = d.get("macro_cards", {})
        market_temp = macro.get("market_temp", {})
        regime_banner = macro.get("regime_banner", {})

        # VIX — 从 macro_cards.vix.value 读取 (float)
        snapshot["vix_val"] = macro.get("vix", {}).get("value")

        # ERP — value 是字符串 "4.5%", 需解析为浮点数
        snapshot["erp_val"] = _parse_erp_value(macro.get("erp", {}).get("value"))

        # Hub 因子得分 — 从 market_temp.hub_factors 读取
        hub_factors = market_temp.get("hub_factors", {})
        snapshot["erp_score"] = hub_factors.get("erp_value", {}).get("score", 50)
        snapshot["vix_score"] = hub_factors.get("vix_fear", {}).get("score", 50)
        snapshot["liquidity_score"] = hub_factors.get("capital_flow", {}).get("score", 50)
        snapshot["macro_temp_score"] = hub_factors.get("macro_temp", {}).get("score", 50)

        # Hub composite + position
        snapshot["hub_composite"] = market_temp.get("hub_composite", 50)
        snapshot["suggested_position"] = regime_banner.get("aiae_cap", 55)

        # 降级模块
        snapshot["degraded_modules"] = market_temp.get("degraded_modules", [])

        # V17.1: 快照完整性日志
        _real_count = sum(1 for k in ["erp_score", "vix_score", "hub_composite"]
                         if snapshot.get(k) != 50)
        _is_cold = _real_count == 0 and not hub_factors
        if _is_cold:
            logger.warning("快照警告: hub_factors 为空, 可能缓存未预热")
        else:
            logger.debug("快照组装: erp=%.1f vix_s=%.1f comp=%.1f pos=%s",
                         snapshot.get("erp_score", 0), snapshot.get("vix_score", 0),
                         snapshot.get("hub_composite", 0), snapshot.get("suggested_position"))

        # V20.0: 数据质量透传 — 前端据此决定是否显示冷启动提示
        snapshot["_data_quality"] = {
            "real_sources": _real_count,
            "total_expected": 4,
            "is_cold_start": _is_cold,
        }

    # AIAE 上下文 (V17.5: 扩展完整字段供仪表卡片使用)
    aiae_ctx = cache_manager.get_json("aiae_ctx")
    if aiae_ctx:
        snapshot["aiae_regime"] = aiae_ctx.get("regime", 3)
        snapshot["aiae_v1"] = aiae_ctx.get("aiae_v1", 22)
        snapshot["aiae_regime_cn"] = aiae_ctx.get("regime_cn", "中性均衡")
        snapshot["aiae_cap"] = aiae_ctx.get("cap", 55)
        snapshot["aiae_slope"] = aiae_ctx.get("slope", 0)
        snapshot["aiae_slope_dir"] = aiae_ctx.get("slope_direction", "flat")
        snapshot["margin_heat"] = aiae_ctx.get("margin_heat", 2.0)
        snapshot["fund_position"] = aiae_ctx.get("fund_position", 80)

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


# ═══════════════════════════════════════════════════════════
#  V17.0 C1: 执行建议生成器
# ═══════════════════════════════════════════════════════════

def generate_action_plan(snapshot: dict, jcs: dict, conflicts: dict) -> dict:
    """
    根据 JCS + 矛盾状态 + 快照数据 → 生成可执行的操作建议。

    返回:
    {
        "action_label": str,       # 核心行动标签
        "action_icon": str,        # 图标
        "confidence": str,         # high/medium/low
        "reasoning": str,          # 一句话推理逻辑
        "top_signals": [str],      # 最强信号摘要 (最多3个)
        "next_check": str,         # 下次检查条件
        "position_target": float,  # 目标仓位
        "risk_note": str,          # 风控提示
    }
    """
    jcs_score = jcs.get("score", 50)
    jcs_level = jcs.get("level", "medium")
    directions = jcs.get("directions", {})
    has_severe = conflicts.get("has_severe", False)
    conflict_count = conflicts.get("conflict_count", 0)
    raw_pos = snapshot.get("suggested_position", 55)
    aiae_regime = snapshot.get("aiae_regime", 3)
    mr_regime = snapshot.get("mr_regime", "RANGE")
    erp_score = snapshot.get("erp_score", 50)
    vix_val = snapshot.get("vix_val", 20)

    # V19.1: 平滑 Sigmoid 曲线代替硬分档
    # JCS=0→0.55, JCS=45→0.80, JCS=70→0.95, JCS=100→1.0
    jcs_multiplier = 0.5 + 0.5 / (1 + math.exp(-0.08 * (jcs_score - 45)))
    pos = round(raw_pos * jcs_multiplier)

    top_signals = []
    risk_note = ""

    # ── 高置信场景 ──
    if jcs_level == "high" and not has_severe:
        # 判断方向
        bullish = sum(1 for d in directions.values() if d == 1)
        bearish = sum(1 for d in directions.values() if d == -1)

        if bullish >= 3:
            action_label = "积极加仓"
            action_icon = "🚀"
            reasoning = f"JCS {jcs_score}分，{bullish}/4引擎看多，方向明确"
            if mr_regime == "BULL":
                top_signals.append("MR技术面处于牛市区间")
            if erp_score > 60:
                top_signals.append(f"ERP估值偏低({erp_score:.0f}分)")
            if aiae_regime <= 2:
                top_signals.append(f"AIAE处于冷配区(R{aiae_regime})")
            next_check = "AIAE升至R4或VIX突破28时减仓"
            risk_note = f"仓位上限 {pos}%，注意单票不超过20%"
        elif bearish >= 3:
            action_label = "防御减仓"
            action_icon = "🛡️"
            reasoning = f"JCS {jcs_score}分但方向偏空，{bearish}/4引擎看空"
            if aiae_regime >= 4:
                top_signals.append(f"AIAE过热(R{aiae_regime})")
            if erp_score < 40:
                top_signals.append("ERP估值偏高")
            if vix_val > 28:
                top_signals.append(f"VIX恐慌({vix_val:.1f})")
            next_check = "VIX回落至25以下 或 AIAE降至R3"
            risk_note = "严格止损，不抄底"
        else:
            action_label = "持仓优化"
            action_icon = "⚖️"
            reasoning = f"JCS {jcs_score}分，信号方向一致但力度温和"
            top_signals.append("多引擎无对冲，可小幅调仓")
            next_check = "明日收盘后复查"
            risk_note = "维持现有仓位结构"

        return {
            "action_label": action_label, "action_icon": action_icon,
            "confidence": "high", "reasoning": reasoning,
            "top_signals": top_signals[:3], "next_check": next_check,
            "position_target": pos, "risk_note": risk_note,
        }

    # ── 矛盾场景 ──
    if has_severe or conflict_count >= 2:
        action_label = "暂停操作"
        action_icon = "⏸️"
        reasoning = f"检测到{conflict_count}个矛盾(含{'严重矛盾' if has_severe else '中度矛盾'})，JCS={jcs_score}"
        for c in conflicts.get("conflicts", [])[:2]:
            top_signals.append(c["desc"])
        next_check = conflicts.get("conflicts", [{}])[0].get("action", "等待矛盾消解")
        risk_note = "不新建仓位，已有持仓设严格止损"

        return {
            "action_label": action_label, "action_icon": action_icon,
            "confidence": "low", "reasoning": reasoning,
            "top_signals": top_signals[:3], "next_check": next_check,
            "position_target": min(pos, 30), "risk_note": risk_note,
        }

    # ── 中置信 / 默认场景 ──
    action_label = "持仓观望"
    action_icon = "👁️"
    reasoning = f"JCS {jcs_score}分，信号不够强烈，等待明确方向"
    neutral_count = sum(1 for d in directions.values() if d == 0)
    if neutral_count >= 3:
        top_signals.append(f"{neutral_count}/4引擎中性，市场缺乏方向")
    if conflict_count == 1:
        top_signals.append("存在轻度矛盾，不宜大幅调仓")
    top_signals.append(f"当前仓位目标: {pos}%")
    next_check = "明日收盘后复查 或 VIX出现异动"
    risk_note = "维持现有仓位，不追涨杀跌"

    return {
        "action_label": action_label, "action_icon": action_icon,
        "confidence": "medium", "reasoning": reasoning,
        "top_signals": top_signals[:3], "next_check": next_check,
        "position_target": pos, "risk_note": risk_note,
    }


# ═════════════════════════════════════════════════════════
#  V17.3 主动警示系统 (Alert Generator)
# ═════════════════════════════════════════════════════════

def generate_alerts(snapshot: dict) -> list:
    """
    扫描快照，生成市场警报列表。
    只在极端或异常条件下触发，正常市场不产生警报。
    
    返回: [{type, severity, icon, title, detail, rule}]
    severity: critical / warning / caution
    """
    alerts = []
    vix = snapshot.get("vix_val") or 20
    aiae_regime = snapshot.get("aiae_regime") or 3
    directions = _signal_direction(snapshot)
    degraded = snapshot.get("degraded_modules", [])
    if isinstance(degraded, str):
        degraded = [d.strip() for d in degraded.split(",") if d.strip()]

    # 1. VIX 极端恐慌
    if vix >= 35:
        alerts.append({
            "type": "vix_extreme",
            "severity": "critical",
            "icon": "🚨",
            "title": f"VIX 极端恐慌 ({vix:.1f})",
            "detail": "全球恐慌指数超过 35，触发全策略风控降权",
            "rule": "规则: VIX ≥ 35 → 仓位上限 30%，禁止新建仓",
        })

    # 2. 流动性熔断
    if snapshot.get("is_circuit_breaker"):
        alerts.append({
            "type": "circuit_breaker",
            "severity": "critical",
            "icon": "🛑",
            "title": "流动性熔断触发",
            "detail": "个股跌停占比超限，市场流动性极度恶化",
            "rule": "规则: 熔断触发 → 仓位归零，等待流动性恢复",
        })

    # 3. 多引擎共振看空 (≥3 个引擎 -1)
    bear_count = sum(1 for d in directions.values() if d == -1)
    if bear_count >= 3:
        bear_names = [k.upper() for k, v in directions.items() if v == -1]
        alerts.append({
            "type": "multi_bear",
            "severity": "warning",
            "icon": "⚠️",
            "title": f"{bear_count} 引擎共振看空",
            "detail": f"{', '.join(bear_names)} 同时发出看空信号",
            "rule": "规则: ≥3 引擎看空 → 降至防御仓位，严格止损",
        })

    # 4. 数据降级警告
    if len(degraded) >= 2:
        alerts.append({
            "type": "data_degraded",
            "severity": "caution",
            "icon": "⚡",
            "title": f"{len(degraded)} 个模块数据降级",
            "detail": f"{', '.join(degraded)} 数据过期，JCS 置信度可能偏离",
            "rule": "规则: ≥2 模块降级 → 不依据 JCS 执行，等待数据恢复",
        })

    # 5. AIAE 极度过热
    if aiae_regime >= 5:
        alerts.append({
            "type": "aiae_overheat",
            "severity": "warning",
            "icon": "🔥",
            "title": "市场极度过热 (Ⅴ级)",
            "detail": "AIAE 配置热度达到极端，历史回撤概率最高",
            "rule": "规则: AIAE R5 → 仓位上限 15%，禁止追涨",
        })

    return alerts


# ═══════════════════════════════════════════════════════════
#  V19.0: 全球市场温度聚合 (纯缓存读取, 零 API 调用)
# ═══════════════════════════════════════════════════════════

# 各市场 AIAE 五档定义 (从各引擎同步, 用于 action 文案)
_GLOBAL_REGIMES = {
    "cn": {
        1: {"cn": "极度恐慌", "emoji": "🟢", "color": "#10b981", "action": "满配进攻", "range": "<12.5%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": "12.5-17%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": "17-23%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": "23-30%", "pos": "25-40%"},
        5: {"cn": "极度过热", "emoji": "🔴", "color": "#ef4444", "action": "清仓防守", "range": ">30%", "pos": "0-15%"},
    },
    "us": {
        1: {"cn": "极度恐慌", "emoji": "🟢", "color": "#10b981", "action": "满配进攻", "range": "<15%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": "15-20%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": "20-27%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": "27-34%", "pos": "25-40%"},
        5: {"cn": "极度过热", "emoji": "🔴", "color": "#ef4444", "action": "清仓防守", "range": ">34%", "pos": "0-15%"},
    },
    "hk": {
        1: {"cn": "极度恐慌", "emoji": "🟢", "color": "#10b981", "action": "满配进攻", "range": "<8%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": "8-12%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": "12-18%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": "18-25%", "pos": "25-40%"},
        5: {"cn": "极度过热", "emoji": "🔴", "color": "#ef4444", "action": "清仓防守", "range": ">25%", "pos": "0-15%"},
    },
    "jp": {
        1: {"cn": "极度悲观", "emoji": "🟢", "color": "#10b981", "action": "全力买入", "range": "<10%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": "10-14%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": "14-20%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": "20-28%", "pos": "25-40%"},
        5: {"cn": "泡沫警报", "emoji": "🔴", "color": "#ef4444", "action": "全面撤退", "range": ">28%", "pos": "0-15%"},
    },
}

# Cap lookup (erp_4_6 行中位值, 用于全球温度聚合)
try:
    from aiae_params import POSITION_MATRIX as _PM2
    _REGIME_CAP_LOOKUP = {i+1: _PM2["erp_4_6"][i] for i in range(5)}
except ImportError:
    _REGIME_CAP_LOOKUP = {1: 90, 2: 80, 3: 60, 4: 35, 5: 10}

# 各市场 AIAE gauge 色带阈值 (用于 ECharts)
_GLOBAL_GAUGE_BANDS = {
    "cn": [12.5, 17, 23, 30, 40],
    "us": [15, 20, 27, 34, 45],
    "hk": [8, 12, 18, 25, 35],
    "jp": [10, 14, 20, 28, 40],
}


def _build_global_temperature() -> dict:
    """
    V19.0: 从缓存聚合四大市场温度数据 (A股/美股/港股/日股)
    数据源:
      - A股: aiae_ctx 缓存 (由 warmup_pipeline 写入)
      - 海外: aiae_global_report_data 缓存 (由 /api/v1/aiae_global/report 写入)
    零 API 调用, 纯缓存读取。
    """
    from services.cache_service import cache_manager

    markets = []
    market_names = {"cn": "A股", "us": "美股", "hk": "港股", "jp": "日股"}
    market_flags = {"cn": "🇨🇳", "us": "🇺🇸", "hk": "🇭🇰", "jp": "🇯🇵"}

    # ── A 股: 从 aiae_ctx 读取 ──
    aiae_ctx = cache_manager.get_json("aiae_ctx")
    if aiae_ctx:
        regime = aiae_ctx.get("regime", 3)
        ri = _GLOBAL_REGIMES["cn"].get(regime, _GLOBAL_REGIMES["cn"][3])
        markets.append({
            "key": "cn", "name": market_names["cn"], "flag": market_flags["cn"],
            "aiae_v1": aiae_ctx.get("aiae_v1", 22.0),
            "regime": regime, "regime_cn": ri["cn"], "regime_color": ri["color"],
            "emoji": ri["emoji"], "cap": aiae_ctx.get("cap", _REGIME_CAP_LOOKUP.get(regime, 57)),
            "action": ri["action"], "range": ri["range"], "pos": ri["pos"],
            "gauge_bands": _GLOBAL_GAUGE_BANDS["cn"],
            "status": "ready",
        })
    else:
        markets.append({"key": "cn", "name": market_names["cn"], "flag": market_flags["cn"], "status": "loading"})

    # ── 海外 (US/HK/JP): 从 aiae_global_report_data 读取 ──
    global_data = cache_manager.get_json("aiae_global_report_data")
    for mkt_key in ["us", "hk", "jp"]:
        if global_data and global_data.get("status") == "success":
            report = global_data.get(mkt_key, {})
            current = report.get("current", {})
            # P5: 多路径 fallback — 兼容不同海外引擎的 JSON 结构
            aiae_v1 = (
                current.get("aiae_v1")
                or report.get("aiae_v1")
                or report.get("summary", {}).get("aiae_v1")
            )
            regime = current.get("regime", 3)
            ri = _GLOBAL_REGIMES[mkt_key].get(regime, _GLOBAL_REGIMES[mkt_key][3])

            # 从 position 字段获取仓位, 回退到 regime 默认
            position_data = report.get("position", {})
            cap = position_data.get("matrix_position", _REGIME_CAP_LOOKUP.get(regime, 57))

            markets.append({
                "key": mkt_key, "name": market_names[mkt_key], "flag": market_flags[mkt_key],
                "aiae_v1": aiae_v1 if aiae_v1 is not None else 22.0,
                "regime": regime, "regime_cn": ri["cn"], "regime_color": ri["color"],
                "emoji": ri["emoji"], "cap": cap,
                "action": ri["action"], "range": ri["range"], "pos": ri["pos"],
                "gauge_bands": _GLOBAL_GAUGE_BANDS[mkt_key],
                "status": "ready" if aiae_v1 is not None else "fallback",
            })
        else:
            markets.append({"key": mkt_key, "name": market_names[mkt_key], "flag": market_flags[mkt_key], "status": "loading"})

    # ── 全球对比 (直接复用已有的 global_comparison) ──
    comparison = {}
    if global_data and global_data.get("global_comparison"):
        comparison = global_data["global_comparison"]

    return {
        "markets": markets,
        "comparison": comparison,
    }


def get_hub_data() -> dict:
    """决策中枢全量数据 (供 API 返回)"""
    snapshot = _build_snapshot_from_cache()

    conflicts = compute_conflict_matrix(snapshot)
    jcs = compute_jcs(snapshot)
    action_plan = generate_action_plan(snapshot, jcs, conflicts)

    # V19.0: 全球市场温度
    global_temp = _build_global_temperature()

    # V21.2: 数据新鲜度元数据 — 前端据此显示各引擎最后更新时间
    from services.cache_service import cache_manager
    _now_ts = datetime.now().timestamp()
    _freshness = {}

    # ── 各引擎缓存状态 + 数据日期提取 ──
    _engine_defs = [
        ("dashboard", "dashboard_data", "Dashboard"),
        ("aiae", "aiae_ctx", "AIAE"),
        ("strategy", "strategy_results", "策略引擎"),
        ("global", "aiae_global_report_data", "全球对比"),
    ]
    _dates_seen = []
    for _fk, _ck, _label in _engine_defs:
        _cached = cache_manager.get_json(_ck)
        if _cached:
            # 提取数据日期 (各引擎存储位置不同)
            _dd = None
            if _fk == "dashboard":
                # dashboard_data 不含 trade_date, 但内嵌 ERP 信号有日期
                _erp_snap = (_cached.get("data", {}).get("macro_cards", {})
                             .get("erp", {}))
                # 从 erp_pct 值存在推断数据有效, 日期从 strategy 补
            elif _fk == "aiae":
                _dd = _cached.get("trade_date") or _cached.get("date")
            elif _fk == "strategy":
                # strategy_results.erp_timing.current_snapshot.trade_date
                _erp_t = _cached.get("erp_timing", {})
                if isinstance(_erp_t, dict):
                    _dd = (_erp_t.get("data", _erp_t).get("current_snapshot", {})
                           .get("trade_date"))
                if not _dd:
                    _mr = _cached.get("mr", {})
                    if isinstance(_mr, dict):
                        _dd = (_mr.get("data", {}).get("market_overview", {})
                               .get("trade_date"))
            elif _fk == "global":
                _dd = (_cached.get("generated_at", "")[:10]
                       if isinstance(_cached.get("generated_at"), str) else None)

            _freshness[_fk] = {"label": _label, "status": "ok", "age_min": 0, "data_date": _dd}
            if _dd:
                _dates_seen.append(_dd)
        else:
            _freshness[_fk] = {"label": _label, "status": "stale", "age_min": -1, "data_date": None}

    # 权威日期源: ERP Timing 引擎的 current_snapshot.trade_date (数据交易日)
    if not _dates_seen:
        try:
            from erp_timing_engine import get_erp_engine
            _erp_sig = get_erp_engine().compute_signal()
            _erp_td = _erp_sig.get("current_snapshot", {}).get("trade_date")
            if _erp_td:
                _erp_td = str(_erp_td)[:10]
                _dates_seen.append(_erp_td)
                if "strategy" in _freshness:
                    _freshness["strategy"]["data_date"] = _erp_td
        except Exception:
            pass

    # ── 跨引擎日期一致性检查 ──
    _unique_dates = list(set(_dates_seen))
    _date_consistent = len(_unique_dates) <= 1
    _primary_date = _unique_dates[0] if _unique_dates else None

    # 用 last_update 时间戳计算各引擎数据年龄
    _last_upd = cache_manager.get_json("last_update")
    if _last_upd and isinstance(_last_upd, (int, float)):
        _age = max(0, int((_now_ts - _last_upd) / 60))  # V22.0 O3: 防时钟偏差产生负值
        for _fk2 in _freshness:
            if _freshness[_fk2]["status"] == "ok":
                _freshness[_fk2]["age_min"] = _age

    # V22.0: 信号半衰期 — 各引擎数据年龄映射为可靠性系数 (放射性衰变模型)
    # 半衰期定义: 经过此天数后, 信号可靠性降至 50%
    _DECAY_HALF_LIVES = {
        "aiae": 15,   # 月频数据, 缓慢衰减
        "erp": 3,     # 日频, 中等衰减 (ERP 信号本身是慢变量)
        "vix": 1,     # 实时数据, 快速衰减
        "mr": 2,      # 日频, 中等衰减
    }
    _DECAY_FRESHNESS_MAP = {
        "aiae": "aiae",
        "erp": "strategy",
        "vix": "dashboard",
        "mr": "strategy",
    }
    _signal_decay = {}
    for _eng_key, _hl_days in _DECAY_HALF_LIVES.items():
        _fk = _DECAY_FRESHNESS_MAP.get(_eng_key, _eng_key)
        _f = _freshness.get(_fk, {})
        _age_min = _f.get("age_min", -1)
        if _age_min >= 0:
            _age_days = _age_min / (60 * 24)
            _reliability = round(0.5 ** (_age_days / _hl_days), 3)
            _signal_decay[_eng_key] = {
                "age_min": _age_min,
                "half_life_hours": _hl_days * 24,
                "reliability": _reliability,
                "label": {"aiae": "AIAE", "erp": "ERP", "vix": "VIX", "mr": "MR"}.get(_eng_key, _eng_key),
            }
        else:
            _signal_decay[_eng_key] = {
                "age_min": -1,
                "half_life_hours": _hl_days * 24,
                "reliability": 0.0,
                "label": {"aiae": "AIAE", "erp": "ERP", "vix": "VIX", "mr": "MR"}.get(_eng_key, _eng_key),
            }

    # V22.0: 合规检查 (在 return 前计算, 内联到 dict)
    _compliance = {"status": "unknown", "summary": "合规检查不可用", "checks": []}
    try:
        from engines.compliance_engine import run_compliance_check
        _pos_target = action_plan.get("position_target", 55)
        _pos_current = snapshot.get("suggested_position", 55)
        _direction = "increase" if _pos_target > _pos_current + 3 \
            else ("decrease" if _pos_target < _pos_current - 3 else "hold")
        _ctx = {"direction": _direction, "jcs_level": jcs.get("level"), "jcs_score": jcs.get("score")}
        _compliance = run_compliance_check(snapshot, context=_ctx)
    except Exception as e:
        logger.debug("合规检查异常: %s", e)

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "snapshot": snapshot,
        "conflicts": conflicts,
        "jcs": jcs,
        "action_plan": action_plan,
        "alerts": generate_alerts(snapshot),
        "scenarios": {k: {"name": v["name"], "desc": v["desc"], "icon": v["icon"], "severity": v["severity"]}
                      for k, v in SCENARIOS.items()},
        "global_temperature": global_temp,
        "data_freshness": _freshness,
        "signal_decay": _signal_decay,
        "data_date": _primary_date,
        "date_consistent": _date_consistent,
        "compliance": _compliance,
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


# ═══════════════════════════════════════════════════════════
#  Phase 2: 准确率回填 (T+5 真实市场收益) — V17.0 修正
# ═══════════════════════════════════════════════════════════

def _get_index_close(trade_date: str, index_code: str = "000300.SH") -> Optional[float]:
    """
    从 Tushare 获取指定日期的指数收盘价。
    支持交易日回溯: 若当日非交易日则查前一交易日。
    返回 None 表示无法获取。
    """
    try:
        import tushare as ts
        pro = ts.pro_api()
        # trade_date 格式: YYYY-MM-DD → YYYYMMDD
        dt_str = trade_date.replace("-", "")
        dt = datetime.strptime(dt_str, "%Y%m%d")
        from datetime import timedelta
        for offset in range(5):  # 最多回溯5天
            try:
                try_date = (dt - timedelta(days=offset)).strftime("%Y%m%d")
                df = pro.index_daily(ts_code=index_code, trade_date=try_date)
                if df is not None and not df.empty:
                    return float(df.iloc[0]["close"])
            except Exception:
                continue
    except Exception as e:
        logger.warning("获取指数收盘价失败 (%s, %s): %s", trade_date, index_code, e)
    return None


def backfill_signal_accuracy():
    """
    V17.0: 使用沪深300真实收盘价计算 T+5 收益率, 替代旧版 ERP 代理.
    
    逻辑:
      1. 查找 5-30 天前 market_return_5d 为空的决策记录
      2. 对每条记录, 获取 T 日和 T+5 日的沪深300收盘价
      3. 计算真实 5 日收益率 = (close_T5 - close_T) / close_T
      4. 回填到 decision_log
    """
    from services import db as ac_db
    from datetime import timedelta

    today = datetime.now()
    conn = ac_db._get_conn()
    rows = conn.execute(
        "SELECT date FROM decision_log WHERE market_return_5d IS NULL "
        "AND date <= ? ORDER BY date DESC LIMIT 15",
        ((today - timedelta(days=5)).strftime("%Y-%m-%d"),)
    ).fetchall()

    if not rows:
        return

    filled_count = 0
    for row in rows:
        log_date = row[0]  # YYYY-MM-DD
        try:
            # 获取 T 日收盘价
            close_t = _get_index_close(log_date)
            if close_t is None:
                logger.debug("准确率回填跳过 %s: T日收盘价不可用", log_date)
                continue

            # 获取 T+5 交易日收盘价
            dt = datetime.strptime(log_date, "%Y-%m-%d")
            # T+5 交易日 ≈ T+7 自然日 (跳过周末)
            t5_date = (dt + timedelta(days=7)).strftime("%Y-%m-%d")
            close_t5 = _get_index_close(t5_date)
            if close_t5 is None:
                logger.debug("准确率回填跳过 %s: T+5日收盘价不可用", log_date)
                continue

            market_return = round((close_t5 - close_t) / close_t, 4)
            ac_db.backfill_accuracy(log_date, market_return)
            filled_count += 1
            logger.info("准确率回填: %s -> return_5d=%.4f (%.2f->%.2f)",
                        log_date, market_return, close_t, close_t5)
        except Exception as e:
            logger.warning("准确率回填异常 %s: %s", log_date, e)
            continue

    if filled_count > 0:
        logger.info("准确率回填完成: %d/%d 条", filled_count, len(rows))


# ═══════════════════════════════════════════════════════════
#  V22.0: 仓位调整路径生成器 (Position Path Planner)
#  弥合"决策 → 执行"断层: 从目标仓位% → 具体标的的分步操作
# ═══════════════════════════════════════════════════════════

# 仓位调整优先级规则
_POSITION_RULES = {
    "max_single_stock": 20,      # 单票仓位上限 (%)
    "max_single_sector": 40,     # 单板块仓位上限 (%)
    "min_holdings": 5,           # 最少持仓数
    "profit_take_threshold": 20,  # 浮盈超过此值 → 优先止盈
    "loss_cut_threshold": -8,    # 浮亏超过此值 → 优先止损
    "step_count": 3,             # 分 3 批执行
    "step_intervals": [0, 2, 5], # T / T+2 / T+5
}


def generate_position_path(snapshot: dict = None, jcs_data: dict = None) -> dict:
    """
    根据当前持仓 + 决策中枢输出, 生成 3 步仓位调整路径。

    输入 (可选, 不传则从缓存构建):
      snapshot: 当前快照
      jcs_data: JCS 结果

    返回:
    {
        "current_cap": float,       # 当前总仓位%
        "target_cap": float,        # 目标仓位%
        "gap": float,               # 调整幅度
        "direction": "increase"/"decrease"/"hold",
        "steps": [                  # 3 步执行计划
            {
                "day": "T" / "T+2" / "T+5",
                "actions": [
                    {
                        "code": "159995.SZ",
                        "name": "芯片ETF华夏",
                        "action": "reduce"/"increase"/"hold",
                        "current_weight": 28.5,
                        "target_weight": 20.0,
                        "delta": -8.5,
                        "reason": "超配20%上限 · 浮盈+96.9%建议止盈"
                    }, ...
                ],
                "step_cap": float,   # 该步骤后总仓位
            }
        ],
        "warnings": [str],          # 风险提示
        "data_source": "portfolio"/"signal",  # 数据来源
    }
    """
    # 构建快照和 JCS (如果未传入)
    if snapshot is None:
        snapshot = _build_snapshot_from_cache()
    if jcs_data is None:
        jcs_data = compute_jcs(snapshot)

    jcs_level = jcs_data.get("level", "medium")
    jcs_score = jcs_data.get("score", 50)
    aiae_regime = snapshot.get("aiae_regime", 3)
    vix_val = snapshot.get("vix_val", 20)
    suggested_pos = snapshot.get("suggested_position", 55)

    # ── 读取实际持仓 ──
    positions = []
    data_source = "signal"
    total_asset = 0
    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        val = pe.get_valuation()
        positions = val.get("positions", [])
        total_asset = val.get("total_asset", 0)
        if positions:
            data_source = "portfolio"
    except Exception as e:
        logger.debug("仓位路径: 持仓读取失败, 回退策略信号: %s", e)

    # ── 无持仓时的纯建议模式 ──
    if not positions:
        return {
            "current_cap": 0,
            "target_cap": suggested_pos,
            "gap": suggested_pos,
            "direction": "increase" if suggested_pos > 30 else "hold",
            "steps": [{
                "day": "T",
                "actions": [{
                    "code": "--", "name": "无实际持仓数据",
                    "action": "increase", "current_weight": 0,
                    "target_weight": suggested_pos, "delta": suggested_pos,
                    "reason": f"JCS={jcs_score:.0f} · AIAE R{aiae_regime} · 目标{suggested_pos}%"
                }],
                "step_cap": suggested_pos,
            }],
            "warnings": ["当前无持仓数据，无法生成精确路径。请导入持仓文件。"],
            "data_source": "signal",
        }

    # ── 有持仓: 计算当前风险暴露 ──
    current_cap = round(100 - val.get("cash_weight", 100), 1) if total_asset > 0 else 0
    target_cap = suggested_pos
    gap = round(target_cap - current_cap, 1)

    if abs(gap) < 3:
        direction = "hold"
    elif gap > 0:
        direction = "increase"
    else:
        direction = "decrease"

    # ── 对持仓打分排序 (决定调整优先级) ──
    MAX_SINGLE = _POSITION_RULES["max_single_stock"]
    PROFIT_TAKE = _POSITION_RULES["profit_take_threshold"]
    LOSS_CUT = _POSITION_RULES["loss_cut_threshold"]

    scored = []
    for p in positions:
        w = p.get("weight", 0)
        pnl_pct = p.get("pnl_pct", 0)
        # 优先级分数: 超配扣分 + 大盈大亏扣分 → 高优先调整
        score = 0
        reasons = []

        # 超配 (超过单票上限)
        if w > MAX_SINGLE:
            score += (w - MAX_SINGLE) * 2
            reasons.append(f"超配>{MAX_SINGLE}%上限")
        # 接近上限
        elif w > MAX_SINGLE * 0.75:
            score += (w - MAX_SINGLE * 0.75)
            reasons.append(f"接近{MAX_SINGLE}%上限")

        # 大幅浮盈 → 止盈候选
        if pnl_pct > PROFIT_TAKE:
            score += pnl_pct * 0.5
            reasons.append(f"浮盈+{pnl_pct:.0f}%建议止盈")
        # 大幅浮亏 → 止损候选 (仅在 JCS 低或 VIX 高时)
        elif pnl_pct < LOSS_CUT:
            if jcs_level == "low" or vix_val > 25:
                score += abs(pnl_pct) * 0.8
                reasons.append(f"浮亏{pnl_pct:.0f}% · JCS低/VIX高建议止损")
            else:
                reasons.append(f"浮亏{pnl_pct:.0f}% · 信号尚可暂持")

        scored.append({
            "code": p.get("ts_code", "--"),
            "name": p.get("name", "Unknown"),
            "industry": p.get("industry", "其他"),
            "weight": w,
            "pnl_pct": pnl_pct,
            "market_value": p.get("market_value", 0),
            "priority_score": round(score, 1),
            "reasons": reasons,
        })

    # 按优先级降序 (高分先调)
    scored.sort(key=lambda x: x["priority_score"], reverse=True)

    # ── 生成 3 步路径 (V23.0: 递进式调仓, 权重状态跟踪) ──
    STEPS = _POSITION_RULES["step_intervals"]
    total_gap = gap
    steps = []
    warnings = []

    # 紧急风控 (VIX > 30 或 JCS < 40 时前置警告)
    emergency_mode = False
    if vix_val > 30:
        warnings.append(f"⚠️ VIX={vix_val:.1f}>30: 首步优先减仓防御")
        emergency_mode = True
    if jcs_level == "low":
        warnings.append(f"⚠️ JCS={jcs_score:.0f}<40: 仅执行减仓操作，禁止新开仓位")
        emergency_mode = True
    if aiae_regime >= 4:
        warnings.append(f"⚠️ AIAE R{aiae_regime}: 过热区间，全路径禁止加仓")

    # V23.0: 渐进式 gap 分配 (替代平均分配)
    if emergency_mode:
        step_ratios = [0.60, 0.25, 0.15]   # 紧急: 首步加重
    else:
        step_ratios = [0.40, 0.35, 0.25]   # 常规: 均衡递进

    # V23.0: 可变权重状态跟踪 (关键修复 — 步骤间权重递进)
    live_weights = {s["code"]: s["weight"] for s in scored}
    MIN_REDUCE = 0.3    # 最小操作阈值 (%), 低于此值不产生操作
    MIN_WEIGHT = 0.5    # 权重下限 (%), 低于此值跳过减仓

    cumulative_delta = 0.0  # 追踪三步总执行量

    for step_i, day_offset in enumerate(STEPS):
        step_gap = round(total_gap * step_ratios[step_i], 1)
        # 最后一步吸收余数 (确保精确到达目标)
        if step_i == len(STEPS) - 1:
            step_gap = round(total_gap - cumulative_delta, 1)

        step_actions = []
        remaining = step_gap

        # ── 减仓路径: 从高优先级持仓开始减 ──
        if remaining < -MIN_REDUCE:
            for s in scored:
                if remaining >= -0.1:
                    break
                lw = live_weights.get(s["code"], 0)
                if lw <= MIN_WEIGHT:
                    continue

                # 单次最多减半 (防止一步清仓导致冲击成本飙升)
                max_reduce = min(abs(remaining), lw * 0.5, 15)
                reduce_amt = round(min(max_reduce, lw - MIN_WEIGHT), 1)
                if reduce_amt < MIN_REDUCE:
                    continue

                new_weight = round(lw - reduce_amt, 1)
                step_actions.append({
                    "code": s["code"], "name": s["name"],
                    "action": "reduce",
                    "current_weight": round(lw, 2),
                    "target_weight": new_weight,
                    "delta": round(-reduce_amt, 1),
                    "reason": " · ".join(s["reasons"][:2]) or "仓位调整",
                })
                remaining += reduce_amt
                # V23.0: 关键 — 更新活权重, 下一步从新权重开始
                live_weights[s["code"]] = new_weight

        # ── 加仓路径 (禁止条件检查) ──
        elif remaining > MIN_REDUCE:
            if jcs_level == "low" or aiae_regime >= 4:
                warnings.append(f"Step {step_i+1}: JCS低/AIAE过热，跳过加仓 (需增加{remaining:.1f}%)")
            else:
                # 从低权重持仓开始加 (分散化)
                low_weight_items = sorted(scored, key=lambda x: live_weights.get(x["code"], 0))
                for s in low_weight_items:
                    if remaining <= 0.1:
                        break
                    lw = live_weights.get(s["code"], 0)
                    if lw >= MAX_SINGLE * 0.8:
                        continue
                    add_amt = round(min(remaining, MAX_SINGLE - lw, 10), 1)
                    if add_amt < MIN_REDUCE:
                        continue
                    new_weight = round(lw + add_amt, 1)
                    step_actions.append({
                        "code": s["code"], "name": s["name"],
                        "action": "increase",
                        "current_weight": round(lw, 2),
                        "target_weight": new_weight,
                        "delta": round(add_amt, 1),
                        "reason": f"低配分散 · 权重{lw:.1f}%→{new_weight:.1f}%",
                    })
                    remaining -= add_amt
                    live_weights[s["code"]] = new_weight

        # ── 累计 delta 追踪 ──
        step_delta = sum(a["delta"] for a in step_actions)
        cumulative_delta += step_delta

        # ── step_cap 计算 (基于累计 delta) ──
        step_cap = round(current_cap + cumulative_delta, 1)

        # ── 动态步骤注释 (基于实际操作内容) ──
        if step_i == 0:
            if emergency_mode:
                note = "紧急防御优先"
            elif any(a.get("delta", 0) < -3 for a in step_actions):
                note = "首批减持"
            elif step_actions:
                note = "初步调仓"
            else:
                note = "观察等待"
        elif step_i == 1:
            note = "主力调仓"
        else:
            note = "精细校准"

        day_label = f"T+{day_offset}" if day_offset > 0 else "T"
        steps.append({
            "day": day_label,
            "interval_days": day_offset,
            "actions": step_actions,
            "step_cap": step_cap,
            "note": note,
        })

    # ── V23.0: 最终校验 — 累计 delta 必须接近 total_gap ──
    delta_error = abs(cumulative_delta - total_gap)
    if delta_error > 1.0 and steps:
        warnings.append(f"⚠️ 路径缺口: 目标{total_gap:.1f}% 实际{cumulative_delta:.1f}% 差异{delta_error:.1f}%")

    return {
        "current_cap": current_cap,
        "target_cap": target_cap,
        "gap": gap,
        "direction": direction,
        "steps": steps,
        "warnings": warnings,
        "data_source": data_source,
    }


# ═══════════════════════════════════════════════════════════
#  V22.0: 跨市场风险传染矩阵 (Contagion Matrix)
#  计算四大市场 120 日收益率相关性, 零新 API 调用
# ═══════════════════════════════════════════════════════════

# 四大市场索引: parquet 文件 → 标签
_CONTAGION_INDICES = [
    {"key": "cn", "ts_code": "510300.SH", "label": "A股", "flag": "🇨🇳",
     "file": "data_lake/daily_prices/510300.SH.parquet"},
    {"key": "us", "ts_code": "513500.SH", "label": "美股", "flag": "🇺🇸",
     "file": "data_lake/daily_prices/513500.SH.parquet"},
    {"key": "hk", "ts_code": "HSI", "label": "港股", "flag": "🇭🇰",
     "file": "data_lake/erp_hk_hsi_history.parquet", "col": "close"},
    {"key": "jp", "ts_code": "N225", "label": "日股", "flag": "🇯🇵",
     "file": "data_lake/erp_jp_nikkei.parquet", "col": "close"},
    # 数据源确认:
    #   CN: 沪深300ETF (Tushare → daily_prices/510300.SH.parquet)
    #   US: 标普500ETF (Tushare → daily_prices/513500.SH.parquet)
    #   HK: 恒生指数 (erp_hk_engine._fetch_hsi_history → erp_hk_hsi_history.parquet, col=close)
    #   JP: 日经225  (erp_jp_engine._fetch_nikkei_history → erp_jp_nikkei.parquet, col=close)
    # 均为引擎原生缓存, 零新增 API 调用.
]


def compute_contagion_matrix(window_days: int = 120) -> dict:
    """
    计算四大市场日收益率 Pearson 相关性矩阵。

    数据源: data_lake/daily_prices/ 中的 parquet 文件 (零 API 调用)
    方法:
      1. 读取四个 ETF 的日线收盘价
      2. 计算日收益率 (close.pct_change)
      3. 对齐交易日 (取四市场交集)
      4. 计算 {window_days} 日滚动 Pearson 矩阵
      5. 返回矩阵 + 传染力解读

    返回:
    {
        "markets": [{key, label, flag}],
        "correlation_matrix": [[1.0, 0.35, 0.62, 0.28], ...],
        "window_days": 120,
        "common_days": 245,
        "contagion_risk": "medium"/"high"/"low",
        "contagion_note": str,
        "high_pairs": [{a, b, corr, level}],
    }
    """
    import os
    import numpy as np
    import pandas as pd

    # ── 1. 读取 ETF/指数日线 ──
    returns = {}
    for idx in _CONTAGION_INDICES:
        fpath = idx["file"]
        if not os.path.exists(fpath):
            continue
        try:
            df = pd.read_parquet(fpath)
            if df.empty:
                continue

            # 确定价格列名 (默认 "close", 可覆盖为 "index_value" 等)
            price_col = idx.get("col", "close")
            if price_col not in df.columns:
                continue

            # 确保有日期列
            if "trade_date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df.set_index("trade_date")
            elif df.index.name != "trade_date" and not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            # 日收益率
            r = df[price_col].pct_change().dropna()
            # 过滤异常值 (>50% 单日波动)
            r = r[(r > -0.5) & (r < 0.5)]
            if len(r) >= 30:
                returns[idx["key"]] = r
        except Exception as e:
            logger.debug("传染矩阵: 读取 %s 失败: %s", fpath, e)

    if len(returns) < 2:
        return {
            "status": "insufficient_data",
            "markets": [],
            "correlation_matrix": [],
            "window_days": window_days,
            "common_days": 0,
            "contagion_risk": "unknown",
            "contagion_note": "数据不足，需至少两个市场的日线数据",
            "high_pairs": [],
        }

    # ── 2. 对齐日期 ──
    ret_df = pd.DataFrame(returns)
    ret_df = ret_df.dropna()  # 仅保留所有市场都有数据的交易日
    common_days = len(ret_df)
    if common_days < window_days:
        # 数据不够窗口大小, 用全部数据
        effective_window = common_days
    else:
        effective_window = window_days

    # 取最近 effective_window 天
    ret_tail = ret_df.tail(effective_window)

    # ── 3. 计算 Pearson 相关性 ──
    corr_matrix_raw = ret_tail.corr().values
    market_keys = list(ret_df.columns)
    market_count = len(market_keys)

    # 构建输出矩阵 (按原始 _CONTAGION_INDICES 顺序)
    ordered_keys = [idx["key"] for idx in _CONTAGION_INDICES if idx["key"] in market_keys]
    corr_map = {}
    for i, ki in enumerate(market_keys):
        for j, kj in enumerate(market_keys):
            corr_map[(ki, kj)] = round(float(corr_matrix_raw[i][j]), 3)

    matrix = []
    for ki in ordered_keys:
        row = []
        for kj in ordered_keys:
            row.append(corr_map.get((ki, kj), 0.0))
        matrix.append(row)

    # ── 4. 高相关对检测 (|ρ| > 0.5) ──
    high_pairs = []
    for i, ki in enumerate(ordered_keys):
        for j, kj in enumerate(ordered_keys):
            if i >= j:
                continue
            corr = corr_map.get((ki, kj), 0)
            if abs(corr) > 0.5:
                level = "extreme" if abs(corr) > 0.8 else ("high" if abs(corr) > 0.65 else "moderate")
                label_i = next((idx["label"] for idx in _CONTAGION_INDICES if idx["key"] == ki), ki)
                label_j = next((idx["label"] for idx in _CONTAGION_INDICES if idx["key"] == kj), kj)
                high_pairs.append({
                    "a": label_i, "b": label_j,
                    "corr": corr,
                    "level": level,
                    "direction": "同涨同跌" if corr > 0 else "对冲",
                })

    # ── 5. 传染风险评估 ──
    avg_corr = np.mean([abs(corr) for (ki, kj), corr in corr_map.items() if ki != kj]) if len(corr_map) > 1 else 0
    if avg_corr > 0.7:
        contagion_risk = "high"
        contagion_note = f"🔴 市场高度联动 (平均 |ρ|={avg_corr:.2f})，单一风险事件可能引发跨市场共振。建议降低单一市场集中度。"
    elif avg_corr > 0.4:
        contagion_risk = "medium"
        contagion_note = f"🟡 市场温和联动 (平均 |ρ|={avg_corr:.2f})，存在区域性分散价值。选择低相关市场可有效降低组合波动。"
    else:
        contagion_risk = "low"
        contagion_note = f"🟢 市场相对独立 (平均 |ρ|={avg_corr:.2f})，全球分散化效果显著。当前是跨市场配置的理想窗口。"

    # ── 6. 市场信息 ──
    markets_info = []
    for idx in _CONTAGION_INDICES:
        if idx["key"] in ordered_keys:
            markets_info.append({
                "key": idx["key"],
                "label": idx["label"],
                "flag": idx["flag"],
                "ts_code": idx["ts_code"],
            })

    return {
        "markets": markets_info,
        "correlation_matrix": matrix,
        "window_days": effective_window,
        "common_days": common_days,
        "contagion_risk": contagion_risk,
        "contagion_note": contagion_note,
        "high_pairs": high_pairs,
    }


# ═══════════════════════════════════════════════════════════
#  V22.0: 有向冲击传播模拟器 (Directed Shock Simulator)
#  基于 BFS 级联传播，替代旧版单点静态情景推演。
# ═══════════════════════════════════════════════════════════

# ── 冲击传播图: 节点 + 有向边 (系数基于宏观金融先验 + 历史回归) ──

_SHOCK_NODES = {
    "rate":      {"label": "利率",     "icon": "📈", "unit": "bps",
                  "snapshot_key": None, "desc": "10年期国债收益率"},
    "erp":       {"label": "ERP",      "icon": "📊", "unit": "%",
                  "snapshot_key": "erp_val", "desc": "股权风险溢价"},
    "vix":       {"label": "VIX",      "icon": "🌪️", "unit": "",
                  "snapshot_key": "vix_val", "desc": "波动率恐慌指数"},
    "aiae":      {"label": "AIAE",     "icon": "🌡️", "unit": "%",
                  "snapshot_key": "aiae_v1", "desc": "全市场配置热度"},
    "mr":        {"label": "MR",       "icon": "📉", "unit": "",
                  "snapshot_key": None, "desc": "均值回归技术面"},
    "cny":       {"label": "人民币",    "icon": "💱", "unit": "%",
                  "snapshot_key": None, "desc": "USD/CNY 汇率"},
    "liquidity": {"label": "流动性",    "icon": "💧", "unit": "",
                  "snapshot_key": "liquidity_score", "desc": "市场流动性"},
    "sentiment": {"label": "情绪",      "icon": "😨", "unit": "",
                  "snapshot_key": None, "desc": "市场情绪综合"},
}

# 有向边: (source, target, coefficient)
# coefficient: source 每变化 1 单位标准差 → target 变化 coefficient 单位标准差
# 正号 = 同向, 负号 = 反向
_SHOCK_EDGES = [
    # rate 利率冲击 → 传导
    ("rate", "erp",        0.70),   # 加息 → ERP 升 (估值压缩)
    ("rate", "vix",        0.50),   # 加息 → 不确定性 → VIX 升
    ("rate", "cny",        0.60),   # 加息 → USD 强 → CNY 弱
    ("rate", "liquidity", -0.40),   # 加息 → 流动性紧
    # VIX 恐慌冲击 → 传导
    ("vix", "erp",        0.35),   # 恐慌 → 股权风险溢价升
    ("vix", "mr",        -0.80),   # 恐慌 → 技术面崩溃
    ("vix", "liquidity", -0.50),   # 恐慌 → 流动性枯竭
    ("vix", "sentiment", -0.90),   # 恐慌 → 情绪冰点
    # ERP 估值冲击 → 传导
    ("erp", "aiae",      -0.50),   # ERP 升 (低估) → AIAE 配置上升空间
    ("erp", "sentiment", -0.40),   # 低估 → 逆向看多
    # AIAE 热度冲击 → 传导
    ("aiae", "mr",       -0.30),   # 过热 → 技术面降温
    ("aiae", "sentiment", 0.60),   # 过热 → 亢奋情绪
    # CNY 汇率冲击 → 传导
    ("cny", "erp",        0.30),   # 人民币贬 → 资本外流 → ERP 升
    ("cny", "liquidity", -0.25),   # 人民币贬 → 流动性偏紧
    # 流动性冲击 → 传导
    ("liquidity", "vix",       -0.40),  # 流动性紧 → VIX 升
    ("liquidity", "mr",        -0.30),  # 流动性紧 → 技术面偏空
    ("liquidity", "sentiment",  0.35),  # 流动性宽 → 情绪好
    # 情绪冲击 → 传导 (反馈环)
    ("sentiment", "vix",       -0.60),  # 情绪差 → VIX 升
    ("sentiment", "mr",         0.40),  # 情绪好 → 技术面改善
]

# 预设冲击源
_SHOCK_SOURCES = {
    "rate_hike_50": {
        "name": "美联储加息 50bp", "icon": "🏦", "severity": "high",
        "source_node": "rate", "magnitude": 1.5,
        "desc": "联邦基金利率上调 50 个基点，全球流动性收紧",
    },
    "rate_cut_50": {
        "name": "紧急降息 50bp", "icon": "📉", "severity": "high",
        "source_node": "rate", "magnitude": -1.5,
        "desc": "央行紧急降息，释放流动性宽松信号",
    },
    "vix_explosion": {
        "name": "VIX 恐慌爆发", "icon": "🌪️", "severity": "extreme",
        "source_node": "vix", "magnitude": 2.0,
        "desc": "VIX 单日飙升 >50%，全球风险资产抛售",
    },
    "cny_crash": {
        "name": "人民币急贬", "icon": "💱", "severity": "high",
        "source_node": "cny", "magnitude": 1.5,
        "desc": "USD/CNY 突破关键阻力，资本外流压力骤增",
    },
    "liquidity_freeze": {
        "name": "流动性冻结", "icon": "🧊", "severity": "extreme",
        "source_node": "liquidity", "magnitude": -2.0,
        "desc": "回购利率飙升，市场流动性急剧萎缩",
    },
    "earnings_shock": {
        "name": "盈利预期崩塌", "icon": "💥", "severity": "high",
        "source_node": "erp", "magnitude": 1.5,
        "desc": "龙头企业盈利预警，ERP 大幅跳升",
    },
    "sentiment_euphoria": {
        "name": "情绪亢奋过热", "icon": "🔥", "severity": "high",
        "source_node": "sentiment", "magnitude": 1.5,
        "desc": "散户跑步入场，融资余额飙升，情绪极度亢奋",
    },
}

# 冲击 → snapshot 映射
# 将节点的标准化冲击值 (单位: 标准差) 转换为 snapshot 的实际 delta
_SNAPSHOT_DELTA_MAP = {
    "erp_val":     lambda v: v * 0.8,          # 1σ shock → ERP 变动 0.8%
    "erp_score":   lambda v: v * 15,           # 1σ shock → ERP score 变动 15 分
    "vix_val":     lambda v: v * 8,             # 1σ shock → VIX 变动 8 点
    "vix_score":   lambda v: v * (-12),         # VIX 升 → score 降
    "aiae_v1":     lambda v: v * (-3),          # 冲击 → AIAE 反向
    "aiae_regime": lambda aiae_v1: (
        1 if aiae_v1 < 12.5 else (2 if aiae_v1 < 17 else
        3 if aiae_v1 < 23 else (4 if aiae_v1 < 30 else 5))
    ),
    "mr_regime":   lambda shock: (
        "CRASH" if shock < -1.2 else ("BEAR" if shock < -0.5 else
        ("BULL" if shock > 0.8 else "RANGE"))
    ),
    "liquidity_score": lambda v: v * 15,
    "macro_temp_score": lambda v: v * (-10),
}


def _build_adjacency():
    """构建邻接表: {node: [(target, coefficient), ...]}"""
    adj = {}
    for src, tgt, coef in _SHOCK_EDGES:
        adj.setdefault(src, []).append((tgt, coef))
        adj.setdefault(tgt, [])
    return adj


def propagate_shock(source_node: str, magnitude: float, steps: int = 3,
                    decay: float = 0.65) -> dict:
    """
    BFS 级联传播: 冲击从源节点沿有向边逐层衰减传播。

    参数:
      source_node: 冲击起始节点
      magnitude: 初始冲击强度 (单位: 标准差)
      steps: 传播步数 (默认 3 跳)
      decay: 每步衰减系数 (默认 0.65, 即每跳保留 65%)

    返回:
    {
        "source": str,
        "magnitude": float,
        "propagation_path": [{step, node, incoming_from, shock_value, net_impact}],
        "node_impacts": {node: final_net_impact},
        "summary": str,
    }
    """
    adj = _build_adjacency()
    if source_node not in adj:
        return {"error": f"未知节点: {source_node}"}

    # 每个节点的累计冲击值
    impacts = {node: 0.0 for node in _SHOCK_NODES}
    impacts[source_node] = magnitude

    # 记录传播路径
    propagation_path = [{
        "step": 0,
        "node": source_node,
        "incoming_from": "初始冲击",
        "shock_value": round(magnitude, 2),
        "net_impact": round(magnitude, 2),
    }]

    # BFS: 按层传播
    visited = {source_node}
    current_layer = [(source_node, magnitude)]

    for step in range(1, steps + 1):
        next_layer = []
        step_path = []

        for node, incoming_shock in current_layer:
            for target, coef in adj.get(node, []):
                transmitted = incoming_shock * coef * (decay ** (step - 1))
                if abs(transmitted) < 0.03:
                    continue  # 低于阈值, 忽略
                impacts[target] += transmitted
                if target not in visited:
                    visited.add(target)
                    next_layer.append((target, transmitted))
                step_path.append({
                    "step": step,
                    "node": target,
                    "incoming_from": node,
                    "shock_value": round(transmitted, 2),
                    "net_impact": round(impacts[target], 2),
                })

        # 按冲击绝对值排序
        step_path.sort(key=lambda x: abs(x["shock_value"]), reverse=True)
        propagation_path.extend(step_path)
        current_layer = next_layer

        if not next_layer:
            break

    # 生成摘要
    top_affected = sorted(
        [(n, v) for n, v in impacts.items() if n != source_node and abs(v) > 0.05],
        key=lambda x: abs(x[1]), reverse=True
    )[:5]
    summary_parts = []
    for node, val in top_affected:
        direction = "↑" if val > 0 else "↓"
        label = _SHOCK_NODES.get(node, {}).get("label", node)
        summary_parts.append(f"{label}{direction}{abs(val):.1f}σ")
    summary = " → ".join(summary_parts) if summary_parts else "冲击未显著传导"

    return {
        "source": source_node,
        "source_label": _SHOCK_NODES.get(source_node, {}).get("label", source_node),
        "magnitude": magnitude,
        "decay": decay,
        "steps": steps,
        "propagation_path": propagation_path,
        "node_impacts": {k: round(v, 3) for k, v in impacts.items()},
        "summary": summary,
    }


def apply_shock_to_snapshot(snapshot: dict, node_impacts: dict) -> dict:
    """
    将节点冲击值映射为 snapshot 的实际变量变更。

    返回: 修改后的 snapshot 深拷贝。
    """
    import copy
    after = copy.deepcopy(snapshot)

    # ── 核心变量直接映射 ──
    for node, shock in node_impacts.items():
        nd = _SHOCK_NODES.get(node, {})
        sk = nd.get("snapshot_key")
        if sk and sk in after and after[sk] is not None:
            mapper = _SNAPSHOT_DELTA_MAP.get(sk)
            if mapper:
                after[sk] = round(after[sk] + mapper(shock), 2)

    # ── 衍生变量联动 ──
    # ERP score 联锁
    if "erp_val" in after and after["erp_val"] is not None:
        _x = max(-20, min(20, 2.5 * (after["erp_val"] - 4.5)))
        after["erp_score"] = round(100.0 / (1.0 + math.exp(-_x)), 1)

    # VIX score 联锁
    if "vix_val" in after and after["vix_val"] is not None:
        after["vix_score"] = _recalc_vix_score(after["vix_val"])

    # AIAE regime 联锁
    if "aiae_v1" in after and after["aiae_v1"] is not None:
        aiae_v = after["aiae_v1"]
        mapper = _SNAPSHOT_DELTA_MAP["aiae_regime"]
        after["aiae_regime"] = mapper(aiae_v)
        after["aiae_regime_cn"] = _REGIME_CN_MAP.get(after["aiae_regime"], "中性均衡")
        after["suggested_position"] = _REGIME_CAP_MAP.get(after["aiae_regime"], 55)

    # MR regime 联锁 — 综合技术面冲击
    mr_shock = node_impacts.get("mr", 0) + node_impacts.get("vix", 0) * (-0.6)
    after["mr_regime"] = _SNAPSHOT_DELTA_MAP["mr_regime"](mr_shock)

    # 综合分联锁
    after["hub_composite"] = _recalc_hub_composite(after)

    return after


def run_shock_simulation(source: str, magnitude: float = None,
                         steps: int = 3) -> dict:
    """
    一站式冲击模拟: 传播 → 应用 → 对比。

    输入:
      source: 冲击源 ID (如 "rate_hike_50") 或原始节点名 (如 "rate")
      magnitude: 可选覆盖预设强度
      steps: 传播步数

    返回:
    {
        "shock_source": {...},
        "propagation": {...},
        "before": {...},
        "after": {...},
        "jcs_before": {...},
        "jcs_after": {...},
        "impact_summary": [...],
    }
    """
    # 解析冲击源
    if source in _SHOCK_SOURCES:
        src_def = _SHOCK_SOURCES[source]
        source_node = src_def["source_node"]
        mag = magnitude if magnitude is not None else src_def["magnitude"]
        shock_info = {
            "id": source, "name": src_def["name"], "icon": src_def["icon"],
            "severity": src_def["severity"], "desc": src_def["desc"],
        }
    else:
        source_node = source
        mag = magnitude if magnitude is not None else 1.0
        shock_info = {
            "id": source, "name": f"冲击: {source}", "icon": "⚡",
            "severity": "medium", "desc": "",
        }

    # 传播
    propagation = propagate_shock(source_node, mag, steps)

    if "error" in propagation:
        return {"status": "error", "error": propagation["error"]}

    # 构建当前快照并应用冲击
    snapshot = _build_snapshot_from_cache()
    after = apply_shock_to_snapshot(snapshot, propagation["node_impacts"])

    # 计算前后 JCS
    jcs_before = compute_jcs(snapshot)
    jcs_after = compute_jcs(after)

    # 影响摘要
    impact_items = []
    pos_before = snapshot.get("suggested_position", 55)
    pos_after = after.get("suggested_position", 55)
    if abs(pos_after - pos_before) > 1:
        direction = "↑" if pos_after > pos_before else "↓"
        impact_items.append(f"仓位 {pos_before}% → {pos_after}% ({direction}{abs(pos_after - pos_before):.0f}%)")
    jcs_delta = jcs_after["score"] - jcs_before["score"]
    if abs(jcs_delta) > 0.5:
        direction = "↑" if jcs_delta > 0 else "↓"
        impact_items.append(f"JCS {jcs_before['score']:.0f} → {jcs_after['score']:.0f} ({direction}{abs(jcs_delta):.0f})")
    if after.get("mr_regime") != snapshot.get("mr_regime"):
        impact_items.append(f"MR {snapshot.get('mr_regime')} → {after.get('mr_regime')}")

    return {
        "status": "success",
        "shock_source": shock_info,
        "propagation": propagation,
        "before": {
            "aiae_regime": snapshot.get("aiae_regime"),
            "aiae_v1": snapshot.get("aiae_v1"),
            "erp_score": snapshot.get("erp_score"),
            "erp_val": snapshot.get("erp_val"),
            "vix_val": snapshot.get("vix_val"),
            "mr_regime": snapshot.get("mr_regime"),
            "suggested_position": pos_before,
        },
        "after": {
            "aiae_regime": after.get("aiae_regime"),
            "aiae_v1": after.get("aiae_v1"),
            "erp_score": after.get("erp_score"),
            "erp_val": after.get("erp_val"),
            "vix_val": after.get("vix_val"),
            "mr_regime": after.get("mr_regime"),
            "suggested_position": pos_after,
        },
        "jcs_before": {"score": jcs_before["score"], "level": jcs_before["level"], "label": jcs_before["label"]},
        "jcs_after": {"score": jcs_after["score"], "level": jcs_after["level"], "label": jcs_after["label"]},
        "impact_summary": impact_items,
    }


# ═══════════════════════════════════════════════════════════
#  V22.0: 动态事件驱动信号引擎 (Event Monitor)
#  对比当前快照与上一次快照, 检测 VI X/AIAE/MR/JCS 突变事件,
#  自动运行冲击传播并记录事件日志。
# ═══════════════════════════════════════════════════════════

import os as _os
import json as _json
from datetime import datetime as _dt

_EVENT_LOG_PATH = "data_lake/market_events.json"
_SNAPSHOT_PATH = "data_lake/event_last_snapshot.json"
_MAX_EVENTS = 50


def _load_last_snapshot() -> dict:
    """加载上一次保存的快照"""
    if _os.path.exists(_SNAPSHOT_PATH):
        try:
            with open(_SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
                return _json.load(f)
        except Exception:
            pass
    return {}


def _save_last_snapshot(snapshot: dict):
    """保存当前快照供下次对比"""
    try:
        payload = {
            "timestamp": _dt.now().isoformat(),
            "aiae_regime": snapshot.get("aiae_regime"),
            "aiae_v1": snapshot.get("aiae_v1"),
            "erp_score": snapshot.get("erp_score"),
            "erp_val": snapshot.get("erp_val"),
            "vix_val": snapshot.get("vix_val"),
            "mr_regime": snapshot.get("mr_regime"),
        }
        _os.makedirs(_os.path.dirname(_SNAPSHOT_PATH), exist_ok=True)
        with open(_SNAPSHOT_PATH, 'w', encoding='utf-8') as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("保存事件快照失败: %s", e)


def _load_event_log() -> list:
    """加载事件日志"""
    if _os.path.exists(_EVENT_LOG_PATH):
        try:
            with open(_EVENT_LOG_PATH, 'r', encoding='utf-8') as f:
                return _json.load(f)
        except Exception:
            pass
    return []


def _save_event_log(events: list):
    """保存事件日志 (保留最近 MAX_EVENTS 条)"""
    try:
        _os.makedirs(_os.path.dirname(_EVENT_LOG_PATH), exist_ok=True)
        trimmed = events[-_MAX_EVENTS:]
        with open(_EVENT_LOG_PATH, 'w', encoding='utf-8') as f:
            _json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("保存事件日志失败: %s", e)


def detect_market_events(current_snapshot: dict) -> list:
    """
    对比当前快照与上次快照, 检测市场突变事件。

    检测规则:
      1. VIX 跳变: |Δ| > 5 或 |Δ%| > 25%
      2. AIAE regime 变化
      3. MR regime 变化
      4. ERP 极端: 突破 6.5% 或跌破 3%
      5. JCS 跨级: high↔medium↔low
    """
    prev = _load_last_snapshot()
    if not prev:
        _save_last_snapshot(current_snapshot)
        return []

    events = []
    now_ts = _dt.now().isoformat()
    curr_vix = current_snapshot.get("vix_val") or 20
    prev_vix = prev.get("vix_val") or 20
    curr_aiae_r = current_snapshot.get("aiae_regime") or 3
    prev_aiae_r = prev.get("aiae_regime") or 3
    curr_mr = current_snapshot.get("mr_regime") or "RANGE"
    prev_mr = prev.get("mr_regime") or "RANGE"
    curr_erp = current_snapshot.get("erp_val") or 4.5
    prev_erp = prev.get("erp_val") or 4.5

    # ── 1. VIX 跳变 ──
    vix_delta = curr_vix - prev_vix
    vix_delta_pct = (curr_vix - prev_vix) / max(prev_vix, 1) * 100
    if abs(vix_delta) > 5 or abs(vix_delta_pct) > 25:
        severity = "extreme" if abs(vix_delta) > 10 else ("high" if abs(vix_delta) > 7 else "medium")
        direction = "飙升" if vix_delta > 0 else "骤降"
        events.append({
            "type": "vix_spike",
            "severity": severity,
            "icon": "🌪️",
            "title": f"VIX {direction}",
            "detail": f"VIX {prev_vix:.1f} → {curr_vix:.1f} (Δ{vix_delta:+.1f}, {vix_delta_pct:+.0f}%)",
            "detected_at": now_ts,
            "auto_scenario": "vix_explosion" if vix_delta > 0 else None,
        })

    # ── 2. AIAE regime 变化 ──
    if curr_aiae_r != prev_aiae_r:
        direction = "升温" if curr_aiae_r > prev_aiae_r else "降温"
        severity = "high" if abs(curr_aiae_r - prev_aiae_r) >= 2 else "medium"
        events.append({
            "type": "aiae_regime_change",
            "severity": severity,
            "icon": "🌡️",
            "title": f"AIAE Regime {direction}",
            "detail": f"R{prev_aiae_r}({_REGIME_CN_MAP.get(prev_aiae_r, '?')}) → R{curr_aiae_r}({_REGIME_CN_MAP.get(curr_aiae_r, '?')})",
            "detected_at": now_ts,
            "auto_scenario": "aiae_overheat_v" if curr_aiae_r >= 4 else None,
        })

    # ── 3. MR regime 变化 ──
    if curr_mr != prev_mr:
        severity = "high" if curr_mr in ("BEAR", "CRASH") else "medium"
        events.append({
            "type": "mr_regime_change",
            "severity": severity,
            "icon": "📉",
            "title": f"MR 技术面切换",
            "detail": f"{prev_mr} → {curr_mr}",
            "detected_at": now_ts,
            "auto_scenario": None,
        })

    # ── 4. ERP 极端 ──
    if (curr_erp > 6.5 and prev_erp <= 6.5) or (curr_erp < 3.0 and prev_erp >= 3.0):
        direction = "极度低估" if curr_erp > 6.5 else "极度高估"
        events.append({
            "type": "erp_extreme",
            "severity": "high",
            "icon": "📊",
            "title": f"ERP {direction}",
            "detail": f"ERP {prev_erp:.2f}% → {curr_erp:.2f}%",
            "detected_at": now_ts,
            "auto_scenario": "erp_extreme_bull" if curr_erp > 6.5 else None,
        })

    # ── 保存快照 ──
    _save_last_snapshot(current_snapshot)

    if not events:
        return []

    # ── 对每个事件自动运行冲击传播 ──
    for evt in events:
        scenario_id = evt.get("auto_scenario")
        if scenario_id:
            try:
                shock_result = run_shock_simulation(scenario_id)
                if shock_result.get("status") == "success":
                    evt["shock_result"] = {
                        "jcs_before": shock_result["jcs_before"]["score"],
                        "jcs_after": shock_result["jcs_after"]["score"],
                        "impact": shock_result.get("impact_summary", []),
                    }
            except Exception as e:
                logger.debug("事件自动冲击传播失败 (%s): %s", evt["type"], e)

    # ── 持久化 ──
    existing = _load_event_log()
    existing.extend(events)
    _save_event_log(existing)

    return events


def get_recent_events(limit: int = 10) -> list:
    """获取最近的市场事件 (供 API)"""
    events = _load_event_log()
    return events[-limit:][::-1]  # 最新的在前


def get_hub_data_with_events() -> dict:
    """
    get_hub_data 的增强版: 额外检测市场事件并附加事件列表。
    供 API 直接调用以原子化获取决策中枢 + 事件。
    """
    result = get_hub_data()

    try:
        snapshot = result.get("snapshot", {})
        if snapshot:
            events = detect_market_events(snapshot)
            result["market_events"] = get_recent_events(10)
            result["new_events_count"] = len(events)
    except Exception as e:
        logger.debug("事件检测异常: %s", e)
        result["market_events"] = []
        result["new_events_count"] = 0

    return result


# ═══════════════════════════════════════════════════════════
#  V22.0: 交易执行成本估算 (Execution Cost Estimator)
#  基于 Almgren-Chriss 简化模型 + 日线数据, 零新 API 调用。
# ═══════════════════════════════════════════════════════════

def _estimate_volatility(code: str) -> float:
    """从 parquet 日线估算年化波动率"""
    import os as _os2
    try:
        import pandas as pd
        fpath = f"data_lake/daily_prices/{code}.parquet"
        if not _os2.path.exists(fpath):
            return 0.25  # 默认年化 25%
        df = pd.read_parquet(fpath)
        if "close" not in df.columns or len(df) < 20:
            return 0.25
        returns = df["close"].pct_change().dropna().tail(60)
        daily_vol = float(returns.std())
        annual_vol = daily_vol * (252 ** 0.5)
        return round(min(annual_vol, 0.80), 3)  # 上限 80%
    except Exception:
        return 0.25


def _estimate_daily_volume(code: str, price: float) -> float:
    """从 parquet 日线估算日均成交额 (万元)"""
    import os as _os2
    try:
        import pandas as pd
        fpath = f"data_lake/daily_prices/{code}.parquet"
        if not _os2.path.exists(fpath):
            return price * 10000  # 保守估算
        df = pd.read_parquet(fpath)
        if "vol" in df.columns:
            avg_vol = float(df["vol"].tail(60).mean())
            if avg_vol > 0:
                return round(avg_vol * price / 10000, 1)  # 万元
        if "amount" in df.columns:
            avg_amt = float(df["amount"].tail(60).mean())
            if avg_amt > 0:
                return round(avg_amt / 10000, 1)  # 万元
        return price * 5000  # fallback
    except Exception:
        return price * 5000


def estimate_execution_cost(code: str, order_value: float,
                            current_price: float = None) -> dict:
    """
    Almgren-Chriss 简化冲击成本模型。

    参数:
      code: 标的代码
      order_value: 订单金额 (元)
      current_price: 当前价格 (从持仓获取)

    返回:
    {
        "impact_cost_pct": float,    # 冲击成本 (%)
        "impact_cost_value": float,  # 冲击成本 (元)
        "annual_vol": float,         # 年化波动率
        "daily_volume_wan": float,   # 日均成交额 (万元)
        "liquidity_grade": str,      # 流动性评级
        "recommended_window": str,   # 建议执行窗口
    }
    """
    vol = _estimate_volatility(code)
    dv = _estimate_daily_volume(code, current_price or 10.0)
    dv_value = dv * 10000  # 万元 → 元

    if dv_value <= 0 or order_value <= 0:
        return {
            "impact_cost_pct": 0.05,
            "impact_cost_value": round(order_value * 0.0005, 2),
            "annual_vol": vol,
            "daily_volume_wan": dv,
            "liquidity_grade": "unknown",
            "recommended_window": "T+0 (当日)",
        }

    # 参与率 = 订单金额 / 日均成交额
    participation = order_value / dv_value

    # Almgren-Chriss 简化: impact ≈ σ * sqrt(Q / V) * 1.5
    # σ = daily_vol = annual_vol / sqrt(252)
    daily_vol = vol / (252 ** 0.5)
    impact_pct = daily_vol * (participation ** 0.5) * 1.5 * 100

    # 流动性评级
    if participation < 0.01:
        liquidity_grade = "🟢 极高流动性"
        recommended_window = "T+0 (当日)"
    elif participation < 0.05:
        liquidity_grade = "🟡 正常流动性"
        recommended_window = "T+0 (当日)"
    elif participation < 0.20:
        liquidity_grade = "🟠 一般流动性"
        recommended_window = "T+0~T+1 分批"
    else:
        liquidity_grade = "🔴 低流动性"
        recommended_window = "T+0~T+2 分批"

    return {
        "impact_cost_pct": round(min(impact_pct, 5.0), 3),
        "impact_cost_value": round(order_value * min(impact_pct, 5.0) / 100, 2),
        "annual_vol": vol,
        "daily_volume_wan": dv,
        "participation_pct": round(participation * 100, 2),
        "liquidity_grade": liquidity_grade,
        "recommended_window": recommended_window,
    }


def estimate_position_path_costs(path_result: dict) -> dict:
    """
    为仓位调整路径的每个操作追加执行成本估算。

    在 generate_position_path 返回后调用，原地增强 steps 中的 actions。
    """
    for step in path_result.get("steps", []):
        for action in step.get("actions", []):
            code = action.get("code", "")
            if not code or code == "--":
                action["execution_cost"] = None
                continue
            # 估算金额 = |delta| * total_asset (粗略, 基于权重变动)
            delta_pct = abs(action.get("delta", 0))
            # 从持仓数据获取市值 (如果 action 有 market_value)
            mv = action.get("market_value", 0)
            order_value = mv * (delta_pct / 100) if mv > 0 else 50000
            try:
                cost = estimate_execution_cost(code, order_value)
                action["execution_cost"] = cost
            except Exception:
                action["execution_cost"] = None
    return path_result

