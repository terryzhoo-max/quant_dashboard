"""
AlphaCore · 回测策略库 V2.0
===========================
与策略中心生产引擎完全对齐:
  - 均值回归 V4.2 (mean_reversion_engine.py)
  - 红利趋势 V4.0 (dividend_trend_engine.py)
  - 动量轮动 V3.0 (momentum_rotation_engine.py)

每个策略函数的默认参数来自策略中心 RANGE 态最优参数。
止损逻辑内嵌于信号序列中（不修改引擎核心）。
"""

import pandas as pd
import numpy as np


# ─── 公用指标计算 ──────────────────────────────────────────────────────────────

def _rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder 平滑 RSI — 与策略中心 mean_reversion_engine.py 完全一致"""
    delta = close.diff(1)
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 0.001)
    return 100 - (100 / (1 + rs))


def _rsi_sma(close: pd.Series, period: int = 9) -> pd.Series:
    """SMA 平滑 RSI — 与红利趋势引擎一致"""
    delta = close.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, 0.001)
    return 100 - (100 / (1 + rs))


def _bias(close: pd.Series, period: int) -> pd.Series:
    """BIAS 乖离率 = (close - MA) / MA × 100"""
    ma = close.rolling(period).mean()
    return (close - ma) / ma * 100


def _bollinger(close: pd.Series, period: int = 20, std_dev: int = 2):
    """布林带"""
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    return upper, lower, ma


def _apply_stop_loss(df: pd.DataFrame, raw_signals: pd.Series,
                     stop_loss_pct: float, price_col: str = 'close') -> pd.Series:
    """
    在原始信号序列中嵌入止损逻辑。
    止损需要循环（因为止损价依赖进场成本），无法纯向量化。
    
    raw_signals: 1=买入, -1=卖出, 0=无操作
    stop_loss_pct: 止损幅度 (正数, 如 0.07 = 7%)
    
    返回: 修改后的信号序列（止损卖出标记为 -1）
    """
    signals = raw_signals.copy()
    close = df[price_col].values
    n = len(signals)
    
    in_position = False
    entry_price = 0.0
    
    for i in range(n):
        sig = signals.iloc[i]
        
        if not in_position:
            if sig == 1:
                in_position = True
                entry_price = close[i]
        else:
            # 检查止损
            if entry_price > 0:
                drawdown = (close[i] / entry_price) - 1
                if drawdown <= -stop_loss_pct:
                    signals.iloc[i] = -1  # 强制止损卖出
                    in_position = False
                    entry_price = 0.0
                    continue
            
            if sig == -1:
                in_position = False
                entry_price = 0.0
            elif sig == 1:
                pass  # 已持仓，忽略重复买入信号
    
    return signals


# ═══════════════════════════════════════════════════════════════════════════════
#  均值回归策略 V4.2 (与 mean_reversion_engine.py 完全对齐)
# ═══════════════════════════════════════════════════════════════════════════════

def mean_reversion_strategy_vectorized(
    df: pd.DataFrame,
    N_trend: int = 90,           # 趋势均线周期 (RANGE态最优)
    rsi_period: int = 14,        # RSI 周期 (策略中心统一 Wilder RSI-14)
    rsi_buy: int = 35,           # RSI 买入阈值 (RANGE态)
    rsi_sell: int = 70,          # RSI 卖出阈值 (RANGE态)
    bias_buy: float = -2.0,      # BIAS 乖离率买入阈值 (RANGE态)
    stop_loss: float = 7.0,      # 止损幅度 % (正数, RANGE态 = 7%)
) -> pd.Series:
    """
    均值回归 V4.2 回测版 — 与策略中心生产引擎逻辑完全一致
    
    核心逻辑 (对齐 mean_reversion_engine.py):
      1. 趋势过滤: close > MA(N_trend)
      2. 买入条件: RSI(14) ≤ rsi_buy  OR  BIAS ≤ bias_buy
      3. 卖出条件: RSI(14) ≥ rsi_sell
      4. 止损: 持仓浮亏超过 stop_loss% 强制平仓
    
    默认参数来源: mr_per_regime_params.json RANGE态
    三态预设: BEAR(40,14,45,65,-3.0,5) / RANGE(90,14,35,70,-2.0,7) / BULL(120,14,45,75,-1.5,6)
    """
    close = df['close']
    
    # 1. 指标计算 (完全对齐策略中心)
    rsi = _rsi_wilder(close, period=rsi_period)
    ma_trend = close.rolling(N_trend).mean()
    bias = _bias(close, N_trend)
    
    # 2. 信号生成 (对齐 generate_signal() 逻辑)
    trend_ok = close > ma_trend
    buy_sig = trend_ok & ((rsi <= rsi_buy) | (bias <= bias_buy))
    sell_sig = rsi >= rsi_sell
    
    signals = pd.Series(0, index=df.index)
    signals[buy_sig] = 1
    signals[sell_sig] = -1
    
    # 3. 内嵌止损
    if stop_loss > 0:
        signals = _apply_stop_loss(df, signals, stop_loss / 100.0)
    
    return signals


# ═══════════════════════════════════════════════════════════════════════════════
#  红利趋势策略 V4.0 (与 dividend_trend_engine.py 完全对齐)
# ═══════════════════════════════════════════════════════════════════════════════

def dividend_trend_strategy_vectorized(
    df: pd.DataFrame,
    ma_trend: int = 60,          # 趋势均线 (RANGE态: 60日)
    rsi_period: int = 9,         # RSI(9) — 红利专用
    rsi_buy: int = 35,           # RSI 买入 (RANGE态)
    rsi_sell: int = 75,          # RSI 卖出 (RANGE态)
    bias_buy: float = -2.0,      # BIAS 买入 (RANGE态)
    ma_defend: int = 30,         # 防守均线 (RANGE态)
    stop_loss: float = 6.0,      # 止损 % (红利ETF较宽松)
) -> pd.Series:
    """
    红利趋势增强 V4.0 回测版 — 与策略中心生产引擎逻辑完全一致
    
    核心逻辑 (对齐 dividend_trend_engine.py generate_signal()):
      Layer 1: 趋势过滤 close > MA(ma_trend)
      Layer 2: 买入触发 RSI ≤ rsi_buy OR BIAS ≤ bias_buy OR close ≤ Boll下轨
      Layer 3: 卖出触发 close < MA(ma_defend) OR RSI ≥ rsi_sell
      Layer 4: 止损
    
    默认参数来源: dividend_trend_engine.py REGIME_PARAMS["RANGE"]
    四态预设: BULL(60,9,40,80,-1.5,20,6) / RANGE(60,9,35,75,-2.0,30,6) / BEAR(90,9,30,70,-3.0,40,5)
    """
    close = df['close']
    
    # 1. 指标计算 (对齐 calculate_indicators())
    rsi = _rsi_sma(close, period=rsi_period)
    ma_t = close.rolling(ma_trend).mean()
    ma_d = close.rolling(ma_defend).mean()
    bias = _bias(close, ma_defend)
    boll_upper, boll_lower, _ = _bollinger(close, period=20)
    
    # 2. 信号生成 (对齐 generate_signal() 三层逻辑)
    # Layer 1: 趋势过滤
    trend_ok = close > ma_t
    
    # Layer 2: 买入触发
    buy_trigger = (rsi <= rsi_buy) | (bias <= bias_buy) | (close <= boll_lower)
    buy_sig = trend_ok & buy_trigger
    
    # Layer 3: 卖出触发
    sell_trigger = (close < ma_d) | (rsi >= rsi_sell)
    
    signals = pd.Series(0, index=df.index)
    signals[buy_sig] = 1
    signals[sell_trigger] = -1
    
    # 3. 内嵌止损
    if stop_loss > 0:
        signals = _apply_stop_loss(df, signals, stop_loss / 100.0)
    
    return signals


# ═══════════════════════════════════════════════════════════════════════════════
#  动量轮动策略 V3.0 (与 momentum_rotation_engine.py 核心逻辑对齐)
# ═══════════════════════════════════════════════════════════════════════════════

def momentum_rotation_strategy_vectorized(
    df: pd.DataFrame,
    lookback_s: int = 20,             # 短期动量窗口 (20日)
    lookback_m: int = 60,             # 中期动量窗口 (60日)
    momentum_threshold: float = 2.0,  # 入场阈值 % (RANGE态)
    stop_loss: float = 7.0,           # 止损 % (RANGE态)
) -> pd.Series:
    """
    动量轮动 V3.0 回测版 — 与策略中心生产引擎核心逻辑对齐
    
    核心逻辑 (对齐 momentum_rotation_engine.py):
      1. 短期动量: pct_change(lookback_s) > threshold%
      2. 中期确认: pct_change(lookback_m) > 0 (方向一致)
      3. 趋势斜率: 20日线性回归斜率 > 0 (上升趋势)
      4. 卖出: 短期动量 < 0 (趋势反转)
      5. 止损
    
    注意: 单标的模式。跨标的轮动需在回测终端用 PK 模式实现。
    
    默认参数来源: momentum_rotation_engine.py REGIME_PARAMS["RANGE"]
    三态预设: BULL(20,60,0,8) / RANGE(20,60,2,7) / BEAR(20,60,5,5)
    """
    close = df['close']
    
    # 1. 动量指标 (对齐 calculate_indicators())
    mom_s = close.pct_change(lookback_s) * 100  # 短期动量 %
    mom_m = close.pct_change(lookback_m) * 100  # 中期动量 %
    
    # 趋势斜率 (20日对数回归, 对齐生产引擎)
    slope = pd.Series(0.0, index=df.index)
    if len(close) >= 20:
        for i in range(20, len(close)):
            y = np.log(close.iloc[i-20:i].values.astype(float))
            x = np.arange(20, dtype=float)
            xm = x - x.mean()
            ym = y - y.mean()
            denom = (xm ** 2).sum()
            if denom > 0:
                slope.iloc[i] = float((xm * ym).sum() / denom) * 252
    
    # 2. 信号生成 (对齐 generate_signals() 多层过滤)
    buy_sig = (
        (mom_s > momentum_threshold) &   # 短期动量超阈值
        (mom_m > 0) &                     # 中期方向确认
        (slope > 0)                       # 趋势斜率为正
    )
    
    sell_sig = mom_s < 0  # 短期动量转负 = 趋势反转
    
    signals = pd.Series(0, index=df.index)
    signals[buy_sig] = 1
    signals[sell_sig] = -1
    
    # 3. 内嵌止损
    if stop_loss > 0:
        signals = _apply_stop_loss(df, signals, stop_loss / 100.0)
    
    return signals
