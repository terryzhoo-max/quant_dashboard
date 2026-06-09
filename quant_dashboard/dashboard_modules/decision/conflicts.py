"""
AlphaCore · 信号矛盾检测器 + 方向解析
=======================================
从 decision_engine.py 拆分 (P2-A)

公开 API:
  - _signal_direction(snapshot) → {engine: direction}
  - compute_conflict_matrix(snapshot) → {conflicts, count, severity}
"""


def _signal_direction(snapshot: dict) -> dict:
    """将各引擎状态映射为方向: +1(看多), 0(中性), -1(看空)
    
    V25.3: 扩展至 6 维 (原4 + gold + bond)
    gold/bond 使用 composite signal 分值映射:
      signal > 25 → +1, signal < -25 → -1, else → 0
    """
    aiae_r = snapshot.get("aiae_regime") or 3        # None → 中性
    erp_s = snapshot.get("erp_score") or 50          # None → 中性
    vix_v = snapshot.get("vix_val") or 20            # None → 中性
    mr_r = snapshot.get("mr_regime") or "RANGE"      # None → 中性

    # 新增: 多资产信号
    gold_sig = snapshot.get("gold_signal")           # [-100, 100] or None
    bond_sig = snapshot.get("bond_signal")           # [-100, 100] or None

    return {
        "aiae": 1 if aiae_r <= 2 else (-1 if aiae_r >= 4 else 0),
        "erp": 1 if erp_s > 55 else (-1 if erp_s < 35 else 0),  # V19.1: 拓宽 (60/40→55/35, A股ERP分布校准)
        "vix": 1 if vix_v < 16 else (-1 if vix_v > 25 else 0),  # P1: 收窄阈值 (A股实证校准)
        "mr": 1 if mr_r == "BULL" else (-1 if mr_r in ("BEAR", "CRASH") else 0),
        # V25.3: 多资产维度 (None → 0 中性, 不影响旧逻辑)
        "gold": (1 if gold_sig > 25 else (-1 if gold_sig < -25 else 0)) if gold_sig is not None else 0,
        "bond": (1 if bond_sig > 25 else (-1 if bond_sig < -25 else 0)) if bond_sig is not None else 0,
    }


def _signal_conviction(snapshot: dict) -> dict:
    """各引擎 → [-1.0, +1.0] 连续信念度 (V26 Signal Conviction Model)

    与 _signal_direction() 的三值化 {-1,0,+1} 不同，连续信念度保留信号强度:
      ±1.0: 极度看多/看空 (引擎读数触及极端区)
      ±0.5: 中度看多/看空
       0.0: 中性 (引擎无方向信号)

    映射原则:
      AIAE:  R1→+1.0 ... R3→0 ... R5→-1.0 (线性, 步长0.5)
      ERP:   score→线性, 中心50, 半宽25 (0→-1, 50→0, 100→+1)
      VIX:   反向线性, 中心20, 半宽10 (10→+1, 20→0, 30→-1)
      MR:    离散 {BULL:+0.8, RANGE:0, BEAR:-0.7, CRASH:-1.0}
      Gold/Bond: 连续信号/50, clamp ±1
    """
    aiae_r = snapshot.get("aiae_regime") if snapshot.get("aiae_regime") is not None else 3
    erp_s  = snapshot.get("erp_score") if snapshot.get("erp_score") is not None else 50
    vix_v  = snapshot.get("vix_val") if snapshot.get("vix_val") is not None else 20
    mr_r   = snapshot.get("mr_regime") or "RANGE"
    gold_sig = snapshot.get("gold_signal")
    bond_sig = snapshot.get("bond_signal")

    # AIAE: R1(极冷)=+1, R2=+0.5, R3(中性)=0, R4=-0.5, R5(极热)=-1
    aiae_conv = max(-1.0, min(1.0, (3 - aiae_r) / 2.0))

    # ERP: score 50=中性, >75=强看多, <25=强看空
    erp_conv = max(-1.0, min(1.0, (erp_s - 50) / 25.0))

    # VIX: 20=中性, <10=强看多(无恐慌), >30=强看空(恐慌)
    vix_conv = max(-1.0, min(1.0, (20 - vix_v) / 10.0))

    # MR: 离散→信念度 (BULL 不给满+1, 技术面信号可靠度略低于基本面)
    _mr_map = {"BULL": 0.8, "RANGE": 0.0, "BEAR": -0.7, "CRASH": -1.0}
    mr_conv = _mr_map.get(mr_r, 0.0)

    # Gold/Bond: 连续信号映射 (None → 0 中性, 不干扰核心逻辑)
    gold_conv = max(-1.0, min(1.0, gold_sig / 50.0)) if gold_sig is not None else 0.0
    bond_conv = max(-1.0, min(1.0, bond_sig / 50.0)) if bond_sig is not None else 0.0

    return {
        "aiae": round(aiae_conv, 3),
        "erp":  round(erp_conv, 3),
        "vix":  round(vix_conv, 3),
        "mr":   round(mr_conv, 3),
        "gold": round(gold_conv, 3),
        "bond": round(bond_conv, 3),
    }


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
