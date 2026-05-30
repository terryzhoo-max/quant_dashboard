"""AlphaCore 请求/响应 Pydantic 模型 — 从 main.py 提取"""
from pydantic import BaseModel, Field
from typing import List, Literal, Optional


# ── 回测 ──
class BacktestRequest(BaseModel):
    strategy: Literal["mr", "div", "mom", "erp"]
    ts_code: str = Field(..., min_length=3, max_length=20)
    start_date: str = Field(..., pattern=r"^\d{8}$")
    end_date: str = Field(..., pattern=r"^\d{8}$")
    initial_cash: float = Field(1000000.0, ge=10000, le=100000000)
    params: dict = {}
    order_pct: float = Field(0.01, ge=0.001, le=1.0)
    adj: Literal["qfq", "hfq", ""] = "qfq"
    benchmark_code: str = Field("000300.SH", min_length=3, max_length=20)

class BatchBacktestRequest(BaseModel):
    items: List[BacktestRequest] = Field(..., min_length=1, max_length=10)

# ── 交易 ──
class TradeRequest(BaseModel):
    ts_code: str = Field(..., min_length=3, max_length=20)
    amount: int = Field(..., gt=0, le=10000000)
    price: float = Field(..., gt=0, le=100000)
    name: str = Field("", max_length=50)
    action: Literal["buy", "sell"]

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
