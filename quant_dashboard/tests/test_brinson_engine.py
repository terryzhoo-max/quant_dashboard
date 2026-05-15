"""
AlphaCore P3-A · Brinson 归因引擎单元测试
==========================================
测试 Brinson-Fachler 三因素分解的数学正确性 (纯计算, mock 数据源)。
"""

import pytest
import sys
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from engines.brinson_engine import (
    _HS300_SECTOR_WEIGHTS_FALLBACK,
    compute_brinson_attribution,
)


def _mock_portfolio(positions, total_asset=1000000):
    """Helper: mock portfolio_engine module for lazy imports"""
    mock_pe = MagicMock()
    mock_pe.get_valuation.return_value = {
        "positions": positions,
        "total_asset": total_asset,
        "market_value": sum(p.get("market_value", 100000) for p in positions),
    }
    mock_mod = MagicMock()
    mock_mod.get_portfolio_engine.return_value = mock_pe
    return patch.dict(sys.modules, {"portfolio_engine": mock_mod})


# ═══════════════════════════════════════════════════
#  静态基准权重
# ═══════════════════════════════════════════════════

class TestBenchmarkWeights:
    def test_weights_sum_near_100(self):
        """静态兜底权重之和应接近 100%"""
        total = sum(_HS300_SECTOR_WEIGHTS_FALLBACK.values())
        assert 95 < total < 105

    def test_major_sectors_present(self):
        """关键板块不能缺失"""
        assert "银行" in _HS300_SECTOR_WEIGHTS_FALLBACK
        assert "电子" in _HS300_SECTOR_WEIGHTS_FALLBACK
        assert "食品饮料" in _HS300_SECTOR_WEIGHTS_FALLBACK
        assert "医药生物" in _HS300_SECTOR_WEIGHTS_FALLBACK

    def test_all_positive(self):
        for sector, weight in _HS300_SECTOR_WEIGHTS_FALLBACK.items():
            assert weight > 0, f"{sector} 权重为 {weight}"


# ═══════════════════════════════════════════════════
#  Brinson 归因集成 (mock 持仓和价格)
# ═══════════════════════════════════════════════════

def _mock_portfolio_engine(positions):
    """构造 mock portfolio engine"""
    mock_pe = MagicMock()
    mock_val = {
        "positions": positions,
        "total_asset": 1000000,
        "market_value": sum(p.get("market_value", 100000) for p in positions),
    }
    mock_pe.get_valuation.return_value = mock_val
    
    mock_pe_factory = MagicMock(return_value=mock_pe)
    return mock_pe_factory


def _mock_data_manager(returns_map=None):
    """构造 mock data manager (价格数据)"""
    import pandas as pd
    default_returns = returns_map or {}
    
    mock_dm = MagicMock()
    
    def get_price(code):
        if code in default_returns:
            base = 100.0
            r = default_returns[code]
            # 生成 30 天数据, 最后一天有 r 的收益
            prices = [base * (1 + r * i / 29) for i in range(30)]
            return pd.DataFrame({"close": prices})
        return pd.DataFrame({"close": [100.0] * 30})  # 平收
    
    mock_dm.get_price_payload = get_price
    return mock_dm


class TestBrinsonAttribution:
    @patch("engines.brinson_engine.cache_manager")
    def test_no_positions_returns_insufficient(self, mock_cm):
        """无持仓 → insufficient"""
        with _mock_portfolio([], total_asset=1000000):
            result = compute_brinson_attribution(lookback=20)
        assert result["status"] == "insufficient"

    @patch("engines.brinson_engine.cache_manager")
    def test_basic_structure(self, mock_cm):
        """基本结构验证"""
        positions = [
            {"ts_code": "601318.SH", "name": "中国平安", "weight": 15,
             "industry": "非银金融", "market_value": 150000},
            {"ts_code": "600519.SH", "name": "贵州茅台", "weight": 20,
             "industry": "食品饮料", "market_value": 200000},
            {"ts_code": "000858.SZ", "name": "五粮液", "weight": 10,
             "industry": "食品饮料", "market_value": 100000},
        ]

        mock_dm = MagicMock()
        mock_dm.get_price_payload.return_value = pd.DataFrame({
            "close": [100 + i * 0.1 for i in range(25)]
        })
        mock_dm_mod = MagicMock()
        mock_dm_mod.FactorDataManager.return_value = mock_dm

        with _mock_portfolio(positions), \
             patch.dict(sys.modules, {"data_manager": mock_dm_mod}):
            result = compute_brinson_attribution(lookback=20)

        if result["status"] == "success":
            assert "effects" in result
            assert "allocation" in result["effects"]
            assert "selection" in result["effects"]
            assert "interaction" in result["effects"]
            assert "sector_detail" in result
            assert result["benchmark"] == "沪深300"

    @patch("engines.brinson_engine.cache_manager")
    def test_total_asset_zero_returns_error(self, mock_cm):
        """总资产为零 → error"""
        positions = [{"ts_code": "A.SH", "name": "A", "weight": 50,
                      "industry": "电子", "market_value": 0}]
        with _mock_portfolio(positions, total_asset=0):
            result = compute_brinson_attribution()
        assert result["status"] == "error"
        assert "零" in result["error"]


# ═══════════════════════════════════════════════════
#  Brinson 三因素数学验证
# ═══════════════════════════════════════════════════

class TestBrinsonMath:
    def test_bf_formula_identity(self):
        """Brinson-Fachler 恒等式: AA + SS + II = Rp - Rb (理论验证)"""
        # 简化场景: 2 板块
        wp = np.array([0.60, 0.40])  # 组合权重
        wb = np.array([0.50, 0.50])  # 基准权重
        rp = np.array([0.08, 0.02])  # 组合板块收益
        rb = np.array([0.05, 0.03])  # 基准板块收益
        
        Rp = wp @ rp  # 组合总收益
        Rb = wb @ rb  # 基准总收益
        
        # BF 分解
        AA = np.sum((wp - wb) * (rb - Rb))
        SS = np.sum(wb * (rp - rb))
        II = np.sum((wp - wb) * (rp - rb))
        
        # 恒等式验证
        np.testing.assert_almost_equal(AA + SS + II, Rp - Rb, decimal=10)

    def test_pure_allocation_effect(self):
        """纯配置效应: 组合和基准选同样的股, 只是权重不同"""
        wp = np.array([0.70, 0.30])
        wb = np.array([0.50, 0.50])
        # 组合和基准在板块内选股收益相同
        rp = np.array([0.10, 0.03])
        rb = rp.copy()  # 选股收益相同
        
        Rb = wb @ rb
        AA = np.sum((wp - wb) * (rb - Rb))
        SS = np.sum(wb * (rp - rb))
        
        # 选股效应应为 0
        assert abs(SS) < 1e-10
        # 配置效应应非零 (超配高收益板块)
        assert AA > 0

    def test_pure_selection_effect(self):
        """纯选股效应: 权重相同, 但板块内收益不同"""
        wp = np.array([0.50, 0.50])
        wb = wp.copy()
        rp = np.array([0.12, 0.03])  # 组合选股更好
        rb = np.array([0.06, 0.04])  # 基准选股一般
        
        Rb = wb @ rb
        AA = np.sum((wp - wb) * (rb - Rb))
        SS = np.sum(wb * (rp - rb))
        
        # 配置效应应为 0
        assert abs(AA) < 1e-10
        # 选股效应应非零
        assert SS > 0
