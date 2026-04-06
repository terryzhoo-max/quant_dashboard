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


# ═══════════════════════════════════════════════════════════════════════════════
#  宏观ERP择时策略 V1.0 (与 erp_timing_engine.py V2.0 评分公式对齐)
# ═══════════════════════════════════════════════════════════════════════════════

def _score_d1_erp_abs_vec(erp_series: pd.Series) -> pd.Series:
    """D1: ERP绝对值 → 0-100 (向量化, 对齐 erp_timing_engine._score_d1)"""
    score = pd.Series(0.0, index=erp_series.index)
    score = np.where(erp_series >= 6.0, 100,
            np.where(erp_series >= 5.0, 70 + (erp_series - 5.0) * 30,
            np.where(erp_series >= 4.0, 50 + (erp_series - 4.0) * 20,
            np.where(erp_series >= 3.0, 25 + (erp_series - 3.0) * 25,
            np.where(erp_series >= 2.0, (erp_series - 2.0) * 25, 0)))))
    return pd.Series(np.clip(score, 0, 100), index=erp_series.index)


def _score_d2_erp_pct_vec(erp_series: pd.Series, window: int = 1260) -> pd.Series:
    """D2: ERP历史分位 → 0-100 (滚动窗口, 对齐 erp_timing_engine._score_d2)"""
    def rolling_pct(arr):
        if len(arr) < 20:
            return 50.0
        current = arr[-1]
        return (arr[:-1] < current).mean() * 100

    return erp_series.rolling(window, min_periods=60).apply(rolling_pct, raw=True).fillna(50.0)


def _score_d3_m1_vec(m1_yoy: pd.Series) -> pd.Series:
    """D3: M1同比趋势 → 0-100 (向量化, 对齐 erp_timing_engine._score_d3)"""
    # 计算趋势: 当前 vs 3个月前 (约63个交易日)
    m1_3m_ago = m1_yoy.shift(63).fillna(m1_yoy)
    m1_1m_ago = m1_yoy.shift(21).fillna(m1_yoy)

    is_positive = m1_yoy > 0
    is_rising = m1_yoy > m1_1m_ago
    is_3m_rising = m1_yoy > m1_3m_ago

    score = pd.Series(50.0, index=m1_yoy.index)

    # 正增长 + 3月趋势上行 → 80-100
    cond1 = is_positive & is_3m_rising
    score = np.where(cond1, np.clip(80 + m1_yoy * 2, 80, 100), score)

    # 正增长 + 环比回升 → 60-80
    cond2 = is_positive & is_rising & ~is_3m_rising
    score = np.where(cond2, np.clip(60 + m1_yoy * 2, 60, 80), score)

    # 正增长但趋势下 → 40-60
    cond3 = is_positive & ~is_rising
    score = np.where(cond3, np.clip(40 + m1_yoy * 2, 40, 60), score)

    # 负增长但拐头 → 30
    cond4 = ~is_positive & is_rising
    score = np.where(cond4, 30, score)

    # 负增长且下行 → 0-20
    cond5 = ~is_positive & ~is_rising
    score = np.where(cond5, np.clip(20 + m1_yoy * 2, 0, 20), score)

    return pd.Series(np.clip(score, 0, 100), index=m1_yoy.index)


def _score_d4_vol_vec(pe_vol: pd.Series) -> pd.Series:
    """D4: PE波动率 → 0-100 (逆向: 高波低分, 对齐 erp_timing_engine._score_d4)"""
    # 滚动分位
    def rolling_vol_pct(arr):
        if len(arr) < 20:
            return 50.0
        current = arr[-1]
        return (arr[:-1] < current).mean() * 100

    vol_pct = pe_vol.rolling(500, min_periods=60).apply(rolling_vol_pct, raw=True).fillna(50.0)

    score = pd.Series(70.0, index=pe_vol.index)
    score = np.where(vol_pct >= 90, 15,      # 极度恐慌 (逆向机会)
            np.where(vol_pct >= 70, 35,      # 高波
            np.where(vol_pct >= 30, 70,      # 正常
            90)))                              # 平静
    return pd.Series(np.clip(score, 0, 100), index=pe_vol.index)


def _score_d5_credit_vec(scissor: pd.Series, m1_yoy: pd.Series) -> pd.Series:
    """D5: 信用环境(M1-M2剪刀差) → 0-100 (对齐 erp_timing_engine._score_d5)"""
    score = pd.Series(50.0, index=scissor.index)
    score = np.where(scissor >= 0, np.clip(85 + scissor * 3, 85, 100),
            np.where(scissor >= -3, 55 + (scissor + 3) * 10,
            np.where(scissor >= -6, 25 + (scissor + 6) * 10,
            np.clip(10 + scissor, 0, 25))))

    # 趋势修正: M1 3月趋势上行且剪刀差为负 → +10
    m1_3m_ago = m1_yoy.shift(63).fillna(m1_yoy)
    is_improving = (m1_yoy > m1_3m_ago) & (scissor < 0)
    score = np.where(is_improving, score + 10, score)

    return pd.Series(np.clip(score, 0, 100), index=scissor.index)


def erp_timing_strategy_vectorized(
    df: pd.DataFrame,
    macro_df: pd.DataFrame = None,
    buy_threshold: float = 65.0,
    sell_threshold: float = 40.0,
    erp_window: int = 1260,
    vol_window: int = 60,
    w_erp_abs: float = 0.25,
    w_erp_pct: float = 0.25,
    w_m1: float = 0.30,
    w_vol: float = 0.10,
    w_credit: float = 0.10,
    stop_loss: float = 10.0,
) -> pd.Series:
    """
    宏观ERP择时策略 V1.0 — 与 erp_timing_engine.py V2.0 五维评分完全对齐

    核心逻辑:
      1. 五维宏观评分 (D1-D5) 加权合成 composite_score
      2. composite >= buy_threshold  → 买入信号 (1)
      3. composite <= sell_threshold → 卖出信号 (-1)
      4. 其他 → 保持 (0)
      5. 内嵌止损

    参数:
      df:             ETF 价格 DataFrame (需含 close 列, DatetimeIndex)
      macro_df:       宏观数据 DataFrame (由 erp_backtest_data.prepare_erp_backtest_data 生成)
                      需含: trade_date, erp, m1_yoy, m2_yoy, scissor, pe_vol
      buy_threshold:  买入阈值 (综合得分)
      sell_threshold: 卖出阈值 (综合得分)
      erp_window:     ERP分位回溯窗口 (交易日数)
      vol_window:     (预留, 当前由 macro_df.pe_vol 自带60日)
      w_*:            五维权重 (须总和=1.0)
      stop_loss:      止损幅度 % (0=不止损)

    返回: pd.Series, 索引与 df 一致, 值为 {1, 0, -1}
    """
    if macro_df is None:
        raise ValueError("ERP策略需要 macro_df 参数 (宏观日频宽表)")

    # 对齐日期: 以ETF价格数据的日期为准
    close = df['close']
    dates = df.index

    # 将 macro_df 索引化
    m = macro_df.copy()
    if 'trade_date' in m.columns:
        m['trade_date'] = pd.to_datetime(m['trade_date'])
        m = m.set_index('trade_date')
    m = m.sort_index()

    # 按日期对齐 (前向填充宏观数据到ETF交易日)
    aligned = m.reindex(dates, method='ffill')
    aligned = aligned.ffill().bfill()

    # 五维评分
    d1 = _score_d1_erp_abs_vec(aligned['erp'])
    d2 = _score_d2_erp_pct_vec(aligned['erp'], window=erp_window)
    d3 = _score_d3_m1_vec(aligned['m1_yoy'])
    d4 = _score_d4_vol_vec(aligned['pe_vol'])
    d5 = _score_d5_credit_vec(aligned['scissor'], aligned['m1_yoy'])

    # 加权合成
    composite = (d1 * w_erp_abs + d2 * w_erp_pct + d3 * w_m1 +
                 d4 * w_vol + d5 * w_credit)

    # 信号生成
    signals = pd.Series(0, index=dates)
    signals[composite >= buy_threshold] = 1
    signals[composite <= sell_threshold] = -1

    # 内嵌止损
    if stop_loss > 0:
        signals = _apply_stop_loss(df, signals, stop_loss / 100.0)

    return signals
