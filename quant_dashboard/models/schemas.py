"""AlphaCore 请求/响应 Pydantic 模型 — 从 main.py 提取"""
from pydantic import BaseModel
from typing import List, Optional


# ── 回测 ──
class BacktestRequest(BaseModel):
    strategy: str  # 'mr', 'div', 'mom', 'erp'
    ts_code: str
    start_date: str
    end_date: str
    initial_cash: float = 1000000.0
    params: dict = {}
    order_pct: float = 0.01
    adj: str = 'qfq'
    benchmark_code: str = '000300.SH'

class BatchBacktestRequest(BaseModel):
    items: List[BacktestRequest]

# ── 交易 ──
class TradeRequest(BaseModel):
    ts_code: str
    amount: int
    price: float
    name: str = ""
    action: str  # "buy" or "sell"

# ── 因子分析 ──
class FactorAnalysisRequest(BaseModel):
    factor_name: str = "roe"
    stock_pool: str = "top30"
    start_date: str = "20200101"
    end_date: str = "20231231"

# ── AIAE 手动更新 ──
class FundPositionUpdate(BaseModel):
    value: float       # 偏股型基金仓位 (60-100%)
    date: str          # 对应季报截止日 (如 "2026-03-31")

# ── 港股手动更新 ──
class HKSouthboundUpdate(BaseModel):
    weekly_net_buy_billion_rmb: float
    monthly_net_buy_billion_rmb: float = None
    cumulative_12m_billion_rmb: float = None

class HKAHPremiumUpdate(BaseModel):
    index_value: float

# ── 日股手动更新 ──
class JPMarginUpdate(BaseModel):
    margin_buying_trillion_jpy: float

class JPForeignUpdate(BaseModel):
    net_buy_billion_jpy: float
    cumulative_12m_billion_jpy: float = None
