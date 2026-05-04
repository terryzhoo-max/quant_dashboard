"""
AlphaCore V21.2 · 投资组合引擎测试
====================================
覆盖:
  - 交易执行: 买入/卖出/仓位上限/余额校验
  - 估值计算: 仓位权重/盈亏
  - 行业推断: ETF/港股名称 → 行业
  - 净值曲线: 边界条件
  - 组合重置
  - safe_round 防御
"""

import pytest
import sys, os
import json
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_engine import PortfolioEngine, safe_round


@pytest.fixture
def engine(tmp_path):
    """创建临时目录中的干净 portfolio 引擎"""
    store = str(tmp_path / "test_portfolio.json")
    history = str(tmp_path / "test_history.json")
    e = PortfolioEngine(store_path=store, history_path=history)
    e.holdings = {"cash": 1000000.0, "positions": {}}
    e._save_portfolio()
    return e


# ═══════════════════════════════════════════════════════
#  safe_round 防御
# ═══════════════════════════════════════════════════════

class TestSafeRound:
    """safe_round 鲁棒性"""

    def test_normal_float(self):
        assert safe_round(3.14159, 2) == 3.14

    def test_string_float(self):
        assert safe_round("42.567", 1) == 42.6

    def test_none_returns_zero(self):
        assert safe_round(None, 2) == 0.0

    def test_garbage_returns_zero(self):
        assert safe_round("abc", 2) == 0.0

    def test_int_input(self):
        assert safe_round(42, 2) == 42.0


# ═══════════════════════════════════════════════════════
#  交易执行
# ═══════════════════════════════════════════════════════

class TestTradeExecution:
    """买入/卖出逻辑"""

    def test_buy_success(self, engine):
        """正常买入"""
        ok, msg = engine.add_position("000001.SZ", 1000, 10.0, "平安银行")
        assert ok is True
        assert engine.holdings["cash"] == 990000.0
        assert "000001.SZ" in engine.holdings["positions"]
        assert engine.holdings["positions"]["000001.SZ"]["amount"] == 1000

    def test_buy_insufficient_cash(self, engine):
        """余额不足"""
        ok, msg = engine.add_position("000001.SZ", 1000000, 100.0, "天价股")
        assert ok is False
        assert "余额不足" in msg

    def test_sell_success(self, engine):
        """正常卖出"""
        engine.add_position("000001.SZ", 1000, 10.0, "平安银行")
        ok, msg = engine.reduce_position("000001.SZ", 500, 12.0)
        assert ok is True
        assert engine.holdings["positions"]["000001.SZ"]["amount"] == 500
        assert engine.holdings["cash"] == 996000.0  # 990000 + 500*12

    def test_sell_clears_position(self, engine):
        """全部卖出应清除持仓"""
        engine.add_position("000001.SZ", 1000, 10.0, "平安银行")
        engine.reduce_position("000001.SZ", 1000, 12.0)
        assert "000001.SZ" not in engine.holdings["positions"]

    def test_sell_nonexistent(self, engine):
        """卖出不存在的持仓"""
        ok, msg = engine.reduce_position("999999.SZ", 100, 10.0)
        assert ok is False
        assert "未持有" in msg

    def test_sell_exceeds_holding(self, engine):
        """卖出超过持仓数量"""
        engine.add_position("000001.SZ", 100, 10.0, "平安银行")
        ok, msg = engine.reduce_position("000001.SZ", 200, 12.0)
        assert ok is False
        assert "持仓不足" in msg

    def test_buy_twice_averages_cost(self, engine):
        """两次买入应平均成本"""
        engine.add_position("000001.SZ", 1000, 10.0, "平安银行")
        engine.add_position("000001.SZ", 1000, 12.0, "平安银行")
        pos = engine.holdings["positions"]["000001.SZ"]
        assert pos["amount"] == 2000
        assert abs(pos["cost"] - 11.0) < 0.01  # 加权平均


# ═══════════════════════════════════════════════════════
#  仓位上限校验
# ═══════════════════════════════════════════════════════

class TestPositionLimit:
    """单票 20% 仓位上限"""

    def test_within_limit(self, engine):
        """不超限的买入应成功"""
        # 买 100万总资产的 15% (150k)
        ok, _ = engine.add_position("000001.SZ", 1500, 100.0, "测试")
        assert ok is True

    def test_exceeds_limit(self, engine):
        """超限的买入应拒绝"""
        # 买 100万总资产的 30% (300k)
        # projected_weight = 300k / (1000k + 300k) = 23.1% > 20%
        ok, msg = engine.add_position("000001.SZ", 3000, 100.0, "测试")
        assert ok is False
        assert "上限" in msg


# ═══════════════════════════════════════════════════════
#  行业推断
# ═══════════════════════════════════════════════════════

class TestIndustryInference:
    """ETF/港股行业推断"""

    def test_semiconductor_etf(self):
        assert PortfolioEngine._infer_industry("159995.SZ", "芯片ETF") == "半导体"

    def test_gold_etf(self):
        assert PortfolioEngine._infer_industry("518880.SH", "黄金ETF") == "贵金属"

    def test_military_etf(self):
        assert PortfolioEngine._infer_industry("512660.SH", "军工ETF") == "国防军工"

    def test_hs_tech(self):
        assert PortfolioEngine._infer_industry("513130.SH", "恒生科技ETF") == "港股-科技"

    def test_dividend_hk(self):
        assert PortfolioEngine._infer_industry("513820.SH", "恒生红利ETF") == "港股-红利"

    def test_csi500(self):
        assert PortfolioEngine._infer_industry("510500.SH", "500ETF") == "宽基-中证500"

    def test_hk_stock(self):
        assert PortfolioEngine._infer_industry("00700.HK", "腾讯控股") == "港股"

    def test_unknown_etf(self):
        result = PortfolioEngine._infer_industry("000000.SZ", "某ETF")
        assert result == "主题ETF"


# ═══════════════════════════════════════════════════════
#  估值计算
# ═══════════════════════════════════════════════════════

class TestValuation:
    """组合估值"""

    def test_empty_portfolio(self, engine):
        val = engine.get_valuation()
        assert val["position_count"] == 0
        assert val["cash"] == 1000000.0

    def test_cash_weight_full(self, engine):
        """无持仓 → 100% 现金"""
        val = engine.get_valuation()
        assert val["cash_weight"] == 100.0

    def test_has_positions(self, engine):
        engine.add_position("000001.SZ", 1000, 10.0, "测试")
        val = engine.get_valuation()
        assert val["position_count"] == 1
        assert val["cash"] == 990000.0


# ═══════════════════════════════════════════════════════
#  组合重置
# ═══════════════════════════════════════════════════════

class TestReset:
    """组合清零"""

    def test_reset_clears_positions(self, engine):
        engine.add_position("000001.SZ", 1000, 10.0, "测试")
        result = engine.reset_portfolio()
        assert result["success"] is True
        assert result["cleared_positions"] == 1
        assert len(engine.holdings["positions"]) == 0
        assert engine.holdings["cash"] == 0.0

    def test_reset_empty_portfolio(self, engine):
        result = engine.reset_portfolio()
        assert result["success"] is True
        assert result["cleared_positions"] == 0


# ═══════════════════════════════════════════════════════
#  交易历史记录
# ═══════════════════════════════════════════════════════

class TestTradeHistory:
    """交易记录持久化"""

    def test_buy_creates_record(self, engine):
        engine.add_position("000001.SZ", 100, 10.0, "测试")
        assert len(engine.trade_history) >= 1
        last = engine.trade_history[-1]
        assert last["action"] == "buy"
        assert last["success"] is True

    def test_failed_sell_creates_record(self, engine):
        engine.reduce_position("NONEXIST.SZ", 100, 10.0)
        assert len(engine.trade_history) >= 1
        last = engine.trade_history[-1]
        assert last["action"] == "sell"
        assert last["success"] is False

    def test_history_persisted_to_file(self, engine):
        engine.add_position("000001.SZ", 100, 10.0, "测试")
        with open(engine.history_path, "r") as f:
            data = json.load(f)
        assert len(data) >= 1

    def test_history_capped_at_200(self, engine):
        """交易记录超过 200 条应裁剪"""
        for i in range(210):
            engine.trade_history.append({"idx": i})
        engine._save_history()
        # 触发裁剪 (通过 _record_trade)
        engine._record_trade("test", "X", "X", 0, 0, True, "trim test")
        assert len(engine.trade_history) <= 201


# ═══════════════════════════════════════════════════════
#  净值曲线边界
# ═══════════════════════════════════════════════════════

class TestNavHistory:
    """净值曲线边界条件"""

    def test_empty_portfolio(self, engine):
        result = engine.get_nav_history()
        assert result["status"] == "empty"
        assert result["dates"] == []
