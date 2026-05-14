"""
AlphaCore · 情景模拟 & 冲击传播引擎
======================================
从 decision_engine.py 拆分 (P2-A)

包含:
  - SCENARIOS 预设情景库 (8 个核心情景)
  - 有向冲击传播 BFS 模拟器 (Shock Propagation)
  - simulate_scenario() 双模式推演

公开 API:
  - SCENARIOS: dict
  - _SHOCK_NODES, _SHOCK_EDGES, _SHOCK_SOURCES, _SNAPSHOT_DELTA_MAP: dict
  - propagate_shock(source, magnitude, steps, decay) → dict
  - apply_shock_to_snapshot(snapshot, node_impacts) → dict
  - run_shock_simulation(source, magnitude, steps) → dict
  - simulate_scenario(scenario_id, current_snapshot) → dict
"""

import copy
import math

from dashboard_modules.decision.conflicts import compute_conflict_matrix
from dashboard_modules.decision.jcs import (
    _REGIME_CAP_MAP, _REGIME_CN_MAP,
    _recalc_vix_score, _recalc_hub_composite,
    compute_jcs,
)
from dashboard_modules.decision.snapshot import _build_snapshot_from_cache


# ═══════════════════════════════════════════════════════════
#  预设情景库 (8 个核心情景)
#  V23.0: shock_bridge 桥接冲击传播引擎
# ═══════════════════════════════════════════════════════════

SCENARIOS = {
    "vix_spike_40": {
        "name": "VIX 暴涨至 40",
        "desc": "全球恐慌指数飙升至极端水平，触发风控降级",
        "icon": "🌪️",
        "severity": "extreme",
        "shock_bridge": {"source": "vix", "magnitude": 2.5},
        "deltas": {},
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
        "desc": "央行紧急降息，流动性大幅宽松，全链路联动",
        "icon": "📉",
        "severity": "high",
        "shock_bridge": {"source": "rate", "magnitude": -1.5},
        "deltas": {},
    },
    "liquidity_crisis": {
        "name": "流动性熔断",
        "desc": "回购利率飙升，市场流动性急剧萎缩，触发熔断",
        "icon": "🚨",
        "severity": "extreme",
        "shock_bridge": {"source": "liquidity", "magnitude": -2.5},
        "deltas": {"is_circuit_breaker": True},
    },
    "golden_cross": {
        "name": "黄金买点",
        "desc": "多引擎同步看多：AIAE冷 + ERP极高 + VIX低",
        "icon": "🏆",
        "severity": "positive",
        "deltas": {"aiae_regime": 1, "erp_val": 6.8, "erp_score": 88, "vix_val": 14},
    },
    "stagflation": {
        "name": "滞胀风暴",
        "desc": "CPI超预期 + 加息预期 + 经济放缓，三重压力共振",
        "icon": "🌊",
        "severity": "extreme",
        "shock_bridge": {"source": "rate", "magnitude": 2.0},
        "deltas": {"aiae_regime": 4},
    },
    "tech_rotation": {
        "name": "科技→价值轮动",
        "desc": "高估值板块资金流出，防御型资产获青睐",
        "icon": "🔄",
        "severity": "high",
        "shock_bridge": {"source": "sentiment", "magnitude": -1.2},
        "deltas": {},
    },
}


# ═══════════════════════════════════════════════════════════
#  冲击传播图: 节点 + 有向边
# ═══════════════════════════════════════════════════════════

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

_SHOCK_EDGES = [
    ("rate", "erp",        0.70),
    ("rate", "vix",        0.50),
    ("rate", "cny",        0.60),
    ("rate", "liquidity", -0.40),
    ("vix", "erp",        0.35),
    ("vix", "mr",        -0.80),
    ("vix", "liquidity", -0.50),
    ("vix", "sentiment", -0.90),
    ("erp", "aiae",      -0.50),
    ("erp", "sentiment", -0.40),
    ("aiae", "mr",       -0.30),
    ("aiae", "sentiment", 0.60),
    ("cny", "erp",        0.30),
    ("cny", "liquidity", -0.25),
    ("liquidity", "vix",       -0.40),
    ("liquidity", "mr",        -0.30),
    ("liquidity", "sentiment",  0.35),
    ("sentiment", "vix",       -0.60),
    ("sentiment", "mr",         0.40),
]

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

_SNAPSHOT_DELTA_MAP = {
    "erp_val":     lambda v: v * 0.8,
    "erp_score":   lambda v: v * 15,
    "vix_val":     lambda v: v * 8,
    "vix_score":   lambda v: v * (-12),
    "aiae_v1":     lambda v: v * (-3),
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
    """BFS 级联传播: 冲击从源节点沿有向边逐层衰减传播。"""
    adj = _build_adjacency()
    if source_node not in adj:
        return {"error": f"未知节点: {source_node}"}

    impacts = {node: 0.0 for node in _SHOCK_NODES}
    impacts[source_node] = magnitude

    propagation_path = [{
        "step": 0, "node": source_node, "incoming_from": "初始冲击",
        "shock_value": round(magnitude, 2), "net_impact": round(magnitude, 2),
    }]

    visited = {source_node}
    current_layer = [(source_node, magnitude)]

    for step in range(1, steps + 1):
        next_layer = []
        step_path = []

        for node, incoming_shock in current_layer:
            for target, coef in adj.get(node, []):
                transmitted = incoming_shock * coef * (decay ** (step - 1))
                if abs(transmitted) < 0.03:
                    continue
                impacts[target] += transmitted
                if target not in visited:
                    visited.add(target)
                    next_layer.append((target, transmitted))
                step_path.append({
                    "step": step, "node": target, "incoming_from": node,
                    "shock_value": round(transmitted, 2),
                    "net_impact": round(impacts[target], 2),
                })

        step_path.sort(key=lambda x: abs(x["shock_value"]), reverse=True)
        propagation_path.extend(step_path)
        current_layer = next_layer
        if not next_layer:
            break

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
        "magnitude": magnitude, "decay": decay, "steps": steps,
        "propagation_path": propagation_path,
        "node_impacts": {k: round(v, 3) for k, v in impacts.items()},
        "summary": summary,
    }


def apply_shock_to_snapshot(snapshot: dict, node_impacts: dict) -> dict:
    """将节点冲击值映射为 snapshot 的实际变量变更。"""
    after = copy.deepcopy(snapshot)

    for node, shock in node_impacts.items():
        nd = _SHOCK_NODES.get(node, {})
        sk = nd.get("snapshot_key")
        if sk and sk in after and after[sk] is not None:
            mapper = _SNAPSHOT_DELTA_MAP.get(sk)
            if mapper:
                after[sk] = round(after[sk] + mapper(shock), 2)

    if "erp_val" in after and after["erp_val"] is not None:
        _x = max(-20, min(20, 2.5 * (after["erp_val"] - 4.5)))
        after["erp_score"] = round(100.0 / (1.0 + math.exp(-_x)), 1)

    if "vix_val" in after and after["vix_val"] is not None:
        after["vix_score"] = _recalc_vix_score(after["vix_val"])

    if "aiae_v1" in after and after["aiae_v1"] is not None:
        aiae_v = after["aiae_v1"]
        mapper = _SNAPSHOT_DELTA_MAP["aiae_regime"]
        after["aiae_regime"] = mapper(aiae_v)
        after["aiae_regime_cn"] = _REGIME_CN_MAP.get(after["aiae_regime"], "中性均衡")
        after["suggested_position"] = _REGIME_CAP_MAP.get(after["aiae_regime"], 55)

    mr_shock = node_impacts.get("mr", 0) + node_impacts.get("vix", 0) * (-0.6)
    after["mr_regime"] = _SNAPSHOT_DELTA_MAP["mr_regime"](mr_shock)
    after["hub_composite"] = _recalc_hub_composite(after)

    return after


def run_shock_simulation(source: str, magnitude: float = None,
                         steps: int = 3) -> dict:
    """一站式冲击模拟: 传播 → 应用 → 对比。"""
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

    propagation = propagate_shock(source_node, mag, steps)
    if "error" in propagation:
        return {"status": "error", "error": propagation["error"]}

    snapshot = _build_snapshot_from_cache()
    after = apply_shock_to_snapshot(snapshot, propagation["node_impacts"])

    jcs_before = compute_jcs(snapshot)
    jcs_after = compute_jcs(after)

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
            "aiae_regime": snapshot.get("aiae_regime"), "aiae_v1": snapshot.get("aiae_v1"),
            "erp_score": snapshot.get("erp_score"), "erp_val": snapshot.get("erp_val"),
            "vix_val": snapshot.get("vix_val"), "mr_regime": snapshot.get("mr_regime"),
            "suggested_position": pos_before,
        },
        "after": {
            "aiae_regime": after.get("aiae_regime"), "aiae_v1": after.get("aiae_v1"),
            "erp_score": after.get("erp_score"), "erp_val": after.get("erp_val"),
            "vix_val": after.get("vix_val"), "mr_regime": after.get("mr_regime"),
            "suggested_position": pos_after,
        },
        "jcs_before": {"score": jcs_before["score"], "level": jcs_before["level"], "label": jcs_before["label"]},
        "jcs_after": {"score": jcs_after["score"], "level": jcs_after["level"], "label": jcs_after["label"]},
        "impact_summary": impact_items,
    }


def simulate_scenario(scenario_id: str, current_snapshot: dict) -> dict:
    """V23.0 情景推演 (双模式): shock_bridge → BFS, delta → 手动覆盖。"""
    if scenario_id not in SCENARIOS:
        return {"error": f"未知情景: {scenario_id}"}

    scenario = SCENARIOS[scenario_id]

    # ── shock_bridge 模式 ──
    if "shock_bridge" in scenario:
        bridge = scenario["shock_bridge"]
        shock_result = run_shock_simulation(
            bridge["source"], bridge.get("magnitude"), steps=3
        )
        if shock_result.get("status") != "success":
            return {"error": shock_result.get("error", "冲击传播失败")}

        extra_deltas = scenario.get("deltas", {})
        if extra_deltas:
            after_snap = shock_result["after"]
            for k, v in extra_deltas.items():
                after_snap[k] = v
            if extra_deltas.get("is_circuit_breaker"):
                after_snap["suggested_position"] = 0
                after_snap["liquidity_score"] = 0
            if "aiae_regime" in extra_deltas:
                after_snap["suggested_position"] = _REGIME_CAP_MAP.get(
                    extra_deltas["aiae_regime"], 55
                )
            shock_result["jcs_after"] = {
                k: v for k, v in compute_jcs(after_snap).items()
                if k in ("score", "level", "label")
            }

        return {
            "status": "success",
            "scenario": {
                "id": scenario_id, "name": scenario["name"], "desc": scenario["desc"],
                "icon": scenario["icon"], "severity": scenario["severity"],
            },
            "before": shock_result["before"],
            "after": shock_result["after"],
            "impact": shock_result.get("impact_summary", []),
            "position_delta": (
                shock_result["after"].get("suggested_position", 55)
                - shock_result["before"].get("suggested_position", 55)
            ),
            "propagation": shock_result.get("propagation"),
            "jcs_before": shock_result.get("jcs_before"),
            "jcs_after": shock_result.get("jcs_after"),
        }

    # ── 传统 delta 模式 ──
    deltas = scenario["deltas"]
    before = copy.deepcopy(current_snapshot)
    after = copy.deepcopy(current_snapshot)

    for key, val in deltas.items():
        after[key] = val

    if "vix_val" in deltas:
        after["vix_score"] = _recalc_vix_score(after["vix_val"])
    if "aiae_regime" in deltas:
        new_regime = deltas["aiae_regime"]
        after["suggested_position"] = _REGIME_CAP_MAP.get(new_regime, 55)
        after["aiae_regime_cn"] = _REGIME_CN_MAP.get(new_regime, "中性均衡")
    if "erp_val" in deltas:
        erp_v = after["erp_val"]
        _erp_x = max(-20, min(20, 2.5 * (erp_v - 4.5)))
        after["erp_score"] = round(100.0 / (1.0 + math.exp(-_erp_x)), 1)
    if deltas.get("is_circuit_breaker"):
        after["suggested_position"] = 0
        after["is_circuit_breaker"] = True
        after["liquidity_score"] = 0
        after["macro_temp_score"] = max(0, after.get("macro_temp_score", 50) - 30)

    if after.get("vix_val", 0) >= 35:
        after["mr_regime"] = "CRASH" if after["vix_val"] >= 45 else "BEAR"
    if after.get("aiae_regime", 3) >= 5 and after.get("mr_regime") == "BULL":
        after["mr_regime"] = "RANGE"
    if after.get("erp_val", 4.5) >= 6.5 and after.get("mr_regime") == "BULL":
        after["mr_regime"] = "RANGE"

    after["hub_composite"] = _recalc_hub_composite(after)
    before["hub_composite"] = _recalc_hub_composite(before)

    jcs_before = compute_jcs(before)
    jcs_after = compute_jcs(after)
    conflicts_before = compute_conflict_matrix(before)
    conflicts_after = compute_conflict_matrix(after)

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
    cc_b, cc_a = conflicts_before["conflict_count"], conflicts_after["conflict_count"]
    if cc_a != cc_b:
        impact_items.append(f"矛盾 {cc_b} → {cc_a} {'⚠️ 新增矛盾' if cc_a > cc_b else '✅ 矛盾消解'}")

    return {
        "scenario": {
            "id": scenario_id, "name": scenario["name"], "desc": scenario["desc"],
            "icon": scenario["icon"], "severity": scenario["severity"],
        },
        "before": {
            "aiae_regime": before.get("aiae_regime"), "erp_score": before.get("erp_score"),
            "erp_val": before.get("erp_val"), "vix_val": before.get("vix_val"),
            "vix_score": before.get("vix_score"), "suggested_position": pos_before,
            "hub_composite": before.get("hub_composite"),
            "jcs": jcs_before["score"], "jcs_level": jcs_before["level"],
        },
        "after": {
            "aiae_regime": after.get("aiae_regime"), "erp_score": after.get("erp_score"),
            "erp_val": after.get("erp_val"), "vix_val": after.get("vix_val"),
            "vix_score": after.get("vix_score"), "suggested_position": pos_after,
            "hub_composite": after.get("hub_composite"),
            "jcs": jcs_after["score"], "jcs_level": jcs_after["level"],
        },
        "impact": impact_items,
        "position_delta": pos_delta,
    }
