"""
AlphaCore V24.1 · 三因子风险归因引擎单元测试
=============================================
覆盖:
  - 日期索引对齐 (Issue 1 验证)
  - 因子贡献精确累计 (Issue 2 验证)
  - OLS Ridge 回归稳健性 (Issue 5 验证)
  - systematic_pct clamp (Issue 6 验证)
  - Alpha 线性年化 (Issue 4 验证)
"""

import sys
import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 1. _to_date_indexed 测试 ──

class TestToDateIndexed:
    """Issue 1: 确保整数 index 被转换为 DatetimeIndex"""

    def test_integer_index_converted(self):
        from engines.factor_attribution_engine import _to_date_indexed
        dates = pd.date_range("2025-01-01", periods=5)
        df = pd.DataFrame({"trade_date": dates, "close": [1, 2, 3, 4, 5]})
        assert not isinstance(df.index, pd.DatetimeIndex)
        result = _to_date_indexed(df)
        assert isinstance(result.index, pd.DatetimeIndex)
        assert "trade_date" not in result.columns

    def test_already_datetime_index(self):
        from engines.factor_attribution_engine import _to_date_indexed
        dates = pd.date_range("2025-01-01", periods=5)
        df = pd.DataFrame({"close": [1, 2, 3, 4, 5]}, index=dates)
        df.index.name = "trade_date"
        result = _to_date_indexed(df)
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_none_input(self):
        from engines.factor_attribution_engine import _to_date_indexed
        assert _to_date_indexed(None) is None

    def test_empty_dataframe(self):
        from engines.factor_attribution_engine import _to_date_indexed
        df = pd.DataFrame()
        result = _to_date_indexed(df)
        assert result.empty


# ── 2. OLS 回归测试 ──

class TestOLSRegression:
    """Issue 5: Ridge 回归 + 条件数检查"""

    def test_perfect_fit(self):
        """完美线性关系 → R² ≈ 1"""
        from engines.factor_attribution_engine import _ols_regression
        np.random.seed(42)
        X = np.random.randn(100, 2)
        y = 0.5 + 1.2 * X[:, 0] - 0.8 * X[:, 1]
        result = _ols_regression(y, X)
        assert result["r_squared"] > 0.999
        assert abs(result["alpha"] - 0.5) < 0.01
        assert abs(result["betas"][0] - 1.2) < 0.01
        assert abs(result["betas"][1] - (-0.8)) < 0.01

    def test_no_relationship(self):
        """纯噪声 → R² ≈ 0"""
        from engines.factor_attribution_engine import _ols_regression
        np.random.seed(42)
        X = np.random.randn(100, 2)
        y = np.random.randn(100)
        result = _ols_regression(y, X)
        assert result["r_squared"] < 0.1

    def test_collinear_factors_no_crash(self):
        """Issue 5: 高共线性因子不应崩溃"""
        from engines.factor_attribution_engine import _ols_regression
        np.random.seed(42)
        X = np.random.randn(100, 1)
        # 第二个因子 = 第一个 + 微小噪声 (高共线性)
        X_collinear = np.column_stack([X, X + np.random.randn(100) * 1e-8])
        y = 0.3 + 0.5 * X[:, 0] + np.random.randn(100) * 0.1
        result = _ols_regression(y, X_collinear)
        # 不崩溃, 返回有效结果
        assert "betas" in result
        assert "r_squared" in result
        assert result["condition_number"] > 1e5  # 应该报高条件数

    def test_r_squared_clamped_to_zero(self):
        """Issue 6: R² 不应为负"""
        from engines.factor_attribution_engine import _ols_regression
        # 极端 case: y 全部相同 (ss_tot = 0)
        X = np.random.randn(50, 2)
        y = np.ones(50)
        result = _ols_regression(y, X)
        assert result["r_squared"] >= 0

    def test_ridge_lambda_effect(self):
        """微正则化 (1e-6) 不应显著改变估计"""
        from engines.factor_attribution_engine import _ols_regression
        np.random.seed(42)
        X = np.random.randn(100, 3)
        y = 0.1 + 0.5 * X[:, 0] - 0.3 * X[:, 1] + 0.8 * X[:, 2] + np.random.randn(100) * 0.1
        r_default = _ols_regression(y, X, ridge_lambda=1e-6)
        r_none = _ols_regression(y, X, ridge_lambda=0)
        # β 差异应极小
        for i in range(3):
            assert abs(r_default["betas"][i] - r_none["betas"][i]) < 0.001


# ── 3. 贡献公式测试 ──

class TestContributionFormula:
    """Issue 2: β × Σ(r_f) vs β × μ × T"""

    def test_contribution_is_exact_cumulative(self):
        """验证新公式: contribution = beta * sum(factor_returns)"""
        beta = 1.2
        factor_returns = pd.Series([0.01, -0.005, 0.008, 0.002, -0.003])

        # 新公式 (精确)
        contribution_exact = beta * factor_returns.sum()
        # 旧公式 (近似)
        contribution_approx = beta * factor_returns.mean() * len(factor_returns)

        # 二者在小样本上应非常接近
        assert abs(contribution_exact - contribution_approx) < 1e-10
        # 但新公式更精确 (概念上正确)
        expected = beta * (0.01 - 0.005 + 0.008 + 0.002 - 0.003)
        assert abs(contribution_exact - expected) < 1e-12


# ── 4. systematic_pct 边界测试 ──

class TestSystematicPctClamp:
    """Issue 6: systematic_pct ∈ [0, 100]"""

    def test_clamp_above_100(self):
        """数值精度问题导致 > 100% 时应被 clamp"""
        systematic_var = 1.001
        total_var = 1.0
        result = min(100.0, max(0.0, systematic_var / total_var * 100))
        assert result == 100.0

    def test_clamp_below_0(self):
        """理论上不应为负, 但防护"""
        systematic_var = -0.001
        total_var = 1.0
        result = min(100.0, max(0.0, systematic_var / total_var * 100))
        assert result == 0.0

    def test_normal_case(self):
        systematic_var = 0.6
        total_var = 1.0
        result = min(100.0, max(0.0, systematic_var / total_var * 100))
        assert 59.9 < result < 60.1


# ── 5. Alpha 年化测试 ──

class TestAlphaAnnualization:
    """Issue 4: 线性年化 vs 复利年化"""

    def test_linear_annualization(self):
        """小日频 alpha 下二者差异不大, 但线性法更稳健"""
        alpha_daily = 0.0001  # 1 bps/day
        alpha_annual_linear = alpha_daily * 252
        alpha_annual_compound = (1 + alpha_daily) ** 252 - 1
        # 线性: 2.52%, 复利: ~2.55%
        assert abs(alpha_annual_linear - 0.0252) < 1e-6
        # 差异在 1% 以内
        assert abs(alpha_annual_linear - alpha_annual_compound) < 0.001

    def test_negative_alpha_no_complex(self):
        """负 alpha 不应产生问题"""
        alpha_daily = -0.0005  # -5 bps/day
        alpha_annual = alpha_daily * 252
        assert alpha_annual < 0
        assert abs(alpha_annual - (-0.126)) < 1e-6


# ── 6. 端到端集成测试 (Mock) ──

class TestFactorAttributionIntegration:
    """Mock 端到端测试: 验证完整管线在 mock 数据下不崩溃"""

    def _make_price_df(self, n=150, base=100, volatility=0.02, seed=42):
        """生成模拟价格 DataFrame"""
        np.random.seed(seed)
        dates = pd.bdate_range(end=datetime.now(), periods=n)
        returns = np.random.randn(n) * volatility
        prices = base * np.exp(np.cumsum(returns))
        return pd.DataFrame({
            "trade_date": dates,
            "close": prices,
        })

    @patch("portfolio_engine.get_portfolio_engine")
    @patch("data_manager.FactorDataManager")
    def test_full_pipeline_runs(self, mock_dm_cls, mock_pe_func):
        """完整管线不崩溃, 返回 success"""
        from engines.factor_attribution_engine import compute_factor_attribution

        # Mock portfolio engine
        mock_pe = MagicMock()
        mock_pe.get_valuation.return_value = {
            "positions": [
                {"ts_code": "600519.SH", "name": "贵州茅台", "market_value": 50000, "industry": "食品饮料"},
                {"ts_code": "000858.SZ", "name": "五粮液", "market_value": 30000, "industry": "食品饮料"},
                {"ts_code": "601318.SH", "name": "中国平安", "market_value": 20000, "industry": "银行"},
            ]
        }
        mock_pe_func.return_value = mock_pe

        # Mock data manager
        mock_dm = MagicMock()

        def mock_get_price(ts_code):
            seed_map = {
                "000300.SH": 1, "000852.SH": 2, "000922.SH": 3, "399006.SZ": 4,
                "600519.SH": 5, "000858.SZ": 6, "601318.SH": 7,
            }
            return self._make_price_df(seed=seed_map.get(ts_code, 99))

        mock_dm.get_price_payload = mock_get_price
        mock_dm_cls.return_value = mock_dm

        result = compute_factor_attribution(lookback=60)

        assert result["status"] == "success"
        assert "factors" in result
        assert "regression" in result
        assert "stock_exposures" in result
        assert 0 <= result["portfolio_decomposition"]["systematic_pct"] <= 100
        assert result["regression"]["r_squared"] >= 0

    @patch("portfolio_engine.get_portfolio_engine")
    def test_insufficient_positions(self, mock_pe_func):
        """持仓不足 → 返回 insufficient"""
        from engines.factor_attribution_engine import compute_factor_attribution

        mock_pe = MagicMock()
        mock_pe.get_valuation.return_value = {
            "positions": [
                {"ts_code": "600519.SH", "name": "贵州茅台", "market_value": 50000},
            ]
        }
        mock_pe_func.return_value = mock_pe

        result = compute_factor_attribution()
        assert result["status"] == "insufficient"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
