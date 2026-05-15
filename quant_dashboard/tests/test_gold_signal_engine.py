"""
AlphaCore P3-B · 黄金信号引擎单元测试
========================================
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from engines.gold_signal_engine import (
    _real_rate_signal,
    _dollar_signal,
    _inflation_signal,
    compute_gold_signal,
    _WEIGHTS,
    _ALLOCATION_MAP,
)


# ═══════════════════════════════════════════════════
#  辅助
# ═══════════════════════════════════════════════════

def _series(values, days=None):
    """生成 Pandas Series 带日期索引"""
    n = len(values)
    dates = pd.date_range(end=datetime.now(), periods=n, freq="B")
    return pd.Series(values, index=dates)


# ═══════════════════════════════════════════════════
#  D1: 实际利率信号
# ═══════════════════════════════════════════════════

class TestRealRateSignal:
    def test_negative_rate_bullish(self):
        """负实际利率 → 看多黄金"""
        data = _series([-1.0] * 30)
        result = _real_rate_signal(data)
        assert result["score"] > 30
        assert "利好" in result["label"]

    def test_high_positive_rate_bearish(self):
        """高正实际利率 → 看空黄金"""
        data = _series([2.0] * 30)
        result = _real_rate_signal(data)
        assert result["score"] < -30
        assert "利空" in result["label"]

    def test_zero_rate_neutral(self):
        """零实际利率 → 中性"""
        data = _series([0.0] * 30)
        result = _real_rate_signal(data)
        assert -30 <= result["score"] <= 30

    def test_insufficient_data(self):
        data = _series([1.0, 1.0])
        result = _real_rate_signal(data)
        assert result["score"] == 0

    def test_none_input(self):
        result = _real_rate_signal(None)
        assert result["score"] == 0


# ═══════════════════════════════════════════════════
#  D2: 美元信号
# ═══════════════════════════════════════════════════

class TestDollarSignal:
    def test_weakening_dollar_bullish(self):
        """美元走弱 → 看多黄金"""
        values = [110] * 25 + [105] * 5  # 下跌趋势
        data = _series(values)
        result = _dollar_signal(data)
        assert result["score"] > 0

    def test_strengthening_dollar_bearish(self):
        """美元走强 → 看空黄金"""
        values = [100] * 25 + [105] * 5  # 上涨趋势
        data = _series(values)
        result = _dollar_signal(data)
        assert result["score"] < 0

    def test_insufficient_data(self):
        data = _series([100] * 10)
        result = _dollar_signal(data)
        assert result["score"] == 0


# ═══════════════════════════════════════════════════
#  D3: 通胀预期信号
# ═══════════════════════════════════════════════════

class TestInflationSignal:
    def test_high_breakeven_bullish(self):
        """高通胀预期 → 看多黄金"""
        dates = pd.date_range(end=datetime.now(), periods=30, freq="B")
        dgs10 = pd.Series([5.0] * 30, index=dates)
        dfii10 = pd.Series([1.5] * 30, index=dates)  # breakeven = 3.5%
        result = _inflation_signal(dgs10, dfii10)
        assert result["score"] > 30

    def test_low_breakeven_bearish(self):
        """低通胀预期 → 看空黄金"""
        dates = pd.date_range(end=datetime.now(), periods=30, freq="B")
        dgs10 = pd.Series([2.0] * 30, index=dates)
        dfii10 = pd.Series([1.5] * 30, index=dates)  # breakeven = 0.5%
        result = _inflation_signal(dgs10, dfii10)
        assert result["score"] < -30

    def test_none_inputs(self):
        result = _inflation_signal(None, None)
        assert result["score"] == 0

    def test_breakeven_calculation(self):
        dates = pd.date_range(end=datetime.now(), periods=30, freq="B")
        dgs10 = pd.Series([4.0] * 30, index=dates)
        dfii10 = pd.Series([1.5] * 30, index=dates)
        result = _inflation_signal(dgs10, dfii10)
        assert abs(result["breakeven"] - 2.5) < 0.01


# ═══════════════════════════════════════════════════
#  综合信号
# ═══════════════════════════════════════════════════

class TestComputeGoldSignal:
    @patch("engines.gold_signal_engine._fetch_fred_series")
    def test_all_bullish(self, mock_fetch):
        """所有子信号看多 → 综合看多"""
        mock_fetch.side_effect = [
            _series([-1.5] * 30),     # DFII10: 负实际利率
            _series([110, 110, 110, 110, 110, 110, 110, 110, 110, 110,
                     110, 110, 110, 110, 110, 110, 110, 110, 110, 110,
                     105, 105, 105, 105, 105, 105, 105, 105, 105, 105]),  # DTWEX: 走弱
            _series([5.0] * 30),      # DGS10: 高名义利率 → 高breakeven
        ]
        result = compute_gold_signal()
        assert result["status"] == "success"
        assert result["gold_signal"] > 25
        assert result["gold_direction"] == "bullish"
        assert result["suggested_allocation"] >= 10

    @patch("engines.gold_signal_engine._fetch_fred_series")
    def test_all_bearish(self, mock_fetch):
        """所有子信号看空 → 综合看空"""
        mock_fetch.side_effect = [
            _series([2.0] * 30),      # DFII10: 高实际利率
            _series([100] * 25 + [110] * 5),  # DTWEX: 走强
            _series([2.5] * 30),      # DGS10: 低名义利率
        ]
        result = compute_gold_signal()
        assert result["status"] == "success"
        assert result["gold_signal"] < -25
        assert result["gold_direction"] == "bearish"
        assert result["suggested_allocation"] <= 5

    @patch("engines.gold_signal_engine._fetch_fred_series")
    def test_error_returns_neutral(self, mock_fetch):
        """FRED 全部失败 → 中性"""
        mock_fetch.return_value = None
        result = compute_gold_signal()
        assert result["gold_direction"] == "neutral"

    def test_weights_sum_to_1(self):
        assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-6

    def test_allocation_map_ordered(self):
        """配置表应从高到低"""
        thresholds = [t for t, _, _ in _ALLOCATION_MAP]
        assert thresholds == sorted(thresholds, reverse=True)
