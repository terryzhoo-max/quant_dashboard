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
    aiae_r = snapshot.get("aiae_regime", 3)
    erp_s = snapshot.get("erp_score", 50)
    vix_v = snapshot.get("vix_val", 20)
    mr_r = snapshot.get("mr_regime", "RANGE")

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
    conflicts = compute_conflict_matrix(snapshot)
    # 过滤掉 info 级别 (如 all_neutral) 不计入惩罚
    penalty_conflicts = [c for c in conflicts["conflicts"] if c["severity"] != "info"]
    has_severe = any(c["severity"] == "high" for c in penalty_conflicts)
    penalty_count = len(penalty_conflicts)

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
        "agreement_pct": round(base_agreement / 60.0 * 100, 1),
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
        if _real_count == 0 and not hub_factors:
            logger.warning("快照警告: hub_factors 为空, 可能缓存未预热")
        else:
            logger.debug("快照组装: erp=%.1f vix_s=%.1f comp=%.1f pos=%s",
                         snapshot.get("erp_score", 0), snapshot.get("vix_score", 0),
                         snapshot.get("hub_composite", 0), snapshot.get("suggested_position"))

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

