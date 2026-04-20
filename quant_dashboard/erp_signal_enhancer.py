"""
ERP Signal Enhancement Module — O10 (Adaptive Weights) + O11 (Multi-Timeframe Confirmation)

共享模块：四引擎统一调用，避免重复代码
"""


def adaptive_weights(base_weights: dict, vol_key: str, vol_regime: str) -> dict:
    """
    O10: 权重自适应 — 恐慌时自动提升波动率维度权重

    策略:
    - extreme_panic/high_fear: 波动率权重 ×2, ERP绝对值权重 ×0.6
    - elevated: 波动率权重 ×1.3, ERP绝对值权重 ×0.85
    - 其他: 原始权重不变

    所有权重调整后归一化至总和=1.0
    """
    w = dict(base_weights)  # 浅拷贝

    if vol_regime in ("extreme_panic", "high_fear"):
        # 恐慌环境: 波动率最重要, ERP绝对值被当前极端估值扭曲
        w[vol_key] = w[vol_key] * 2.0
        w["erp_abs"] = w["erp_abs"] * 0.6
    elif vol_regime in ("elevated", "elevated_high", "high"):
        # 紧张环境: 适度提升波动率
        w[vol_key] = w[vol_key] * 1.3
        w["erp_abs"] = w["erp_abs"] * 0.85

    # 归一化
    total = sum(w.values())
    if total > 0:
        w = {k: round(v / total, 4) for k, v in w.items()}

    return w


def multi_timeframe_confirmation(erp_series, current_score: float) -> dict:
    """
    O11: 多时间框架确认

    用不同窗口的ERP均值判断信号一致性:
    - 日线 (近5天均值)
    - 周线 (近20天均值)
    - 月线 (近63天均值)

    分别映射为看多(ERP > 中位数)/看空/中性, 然后计算一致性

    返回:
        {
            "daily_bias": "bullish" / "bearish" / "neutral",
            "weekly_bias": ...,
            "monthly_bias": ...,
            "agreement": 3/3, 2/3, 1/3
            "confirmed": True/False (>=2/3 一致),
            "label": "三线共振看多" / "信号分歧" / etc.
            "confidence_mod": +3 / 0 / -3  (对composite的微调)
        }
    """
    if len(erp_series) < 63:
        return {
            "daily_bias": "neutral", "weekly_bias": "neutral", "monthly_bias": "neutral",
            "agreement": "N/A", "confirmed": True, "label": "数据不足，默认确认",
            "confidence_mod": 0,
        }

    # 计算各窗口的ERP均值
    erp_daily = float(erp_series.tail(5).mean())
    erp_weekly = float(erp_series.tail(20).mean())
    erp_monthly = float(erp_series.tail(63).mean())
    erp_median = float(erp_series.tail(252).median()) if len(erp_series) >= 252 else float(erp_series.median())

    def _classify(val, median):
        """ERP高于中位数=低估=看多, 低于=看空"""
        if val > median * 1.05:
            return "bullish"
        elif val < median * 0.95:
            return "bearish"
        return "neutral"

    daily_b = _classify(erp_daily, erp_median)
    weekly_b = _classify(erp_weekly, erp_median)
    monthly_b = _classify(erp_monthly, erp_median)

    biases = [daily_b, weekly_b, monthly_b]
    bull_count = biases.count("bullish")
    bear_count = biases.count("bearish")

    if bull_count >= 2:
        agreement = f"{bull_count}/3"
        confirmed = True
        label = "📗 多时间框架看多" if bull_count == 3 else "📗 周月看多(日线分歧)"
        confidence_mod = 3 if bull_count == 3 else 1
    elif bear_count >= 2:
        agreement = f"{bear_count}/3"
        confirmed = True
        label = "📕 多时间框架看空" if bear_count == 3 else "📕 周月看空(日线分歧)"
        confidence_mod = -3 if bear_count == 3 else -1
    else:
        agreement = "1/3"
        confirmed = False
        label = "📙 多时间框架信号分歧"
        confidence_mod = 0

    return {
        "daily_bias": daily_b,
        "weekly_bias": weekly_b,
        "monthly_bias": monthly_b,
        "erp_daily_avg": round(erp_daily, 2),
        "erp_weekly_avg": round(erp_weekly, 2),
        "erp_monthly_avg": round(erp_monthly, 2),
        "erp_median_1y": round(erp_median, 2),
        "agreement": agreement,
        "confirmed": confirmed,
        "label": label,
        "confidence_mod": confidence_mod,
    }
