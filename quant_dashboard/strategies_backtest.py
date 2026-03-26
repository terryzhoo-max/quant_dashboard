import pandas as pd
import numpy as np
from backtest_engine import Indicators

def mean_reversion_strategy_vectorized(df: pd.DataFrame, 
                                       rsi_period=3, 
                                       rsi_buy=10, 
                                       rsi_sell=85,
                                       boll_period=20,
                                       ma_trend_period=60) -> pd.Series:
    """
    Vectorized version of the Mean Reversion strategy V2.0.
    """
    close = df['close']
    
    # 1. Indicators
    rsi_3 = Indicators.RSI(close, period=rsi_period)
    boll = Indicators.BOLL(close, period=boll_period)
    ma_trend = close.rolling(ma_trend_period).mean()
    ma20 = close.rolling(20).mean()
    
    # 2. Logic
    # Buy: RSI < 10 and Close < Lower Boll and Trend is OK (Close > MA_Trend * 0.9)
    buy_sig = (rsi_3 < rsi_buy) & (close < boll['lower']) & (close > ma_trend * 0.9)
    
    # Sell: RSI > 85 or Close > Upper Boll or %B > 1
    sell_sig = (rsi_3 > rsi_sell) | (close > boll['upper']) | (boll['percent_b'] > 1.0)
    
    # 3. Combine into Signal (-1, 0, 1)
    signals = pd.Series(0, index=df.index)
    signals[buy_sig] = 1
    signals[sell_sig] = -1
    
    # Forward fill to maintain position? 
    # For a "strategy" signal series in AlphaBacktester, it usually represents the *target* state.
    # We will let the user decide if they want a "rebalancing" signal or a "continuous" position.
    # Here we return raw signals.
    return signals

def dividend_trend_strategy_vectorized(df: pd.DataFrame,
                                        ma_slow=120,
                                        ma_fast=20,
                                        rsi_period=9,
                                        rsi_buy=40) -> pd.Series:
    """
    Vectorized version of the Dividend Trend strategy V2.0.
    """
    close = df['close']
    ma_s = close.rolling(ma_slow).mean()
    ma_f = close.rolling(ma_fast).mean()
    rsi = Indicators.RSI(close, rsi_period)
    
    # Buy: Price > MA120 (Bull) AND (RSI < 40 or Price < MA20)
    buy_sig = (close > ma_s) & ((rsi < rsi_buy) | (close < ma_f))
    
    # Sell: Price < MA20 (Trend Break) or RSI > 75
    sell_sig = (close < ma_f) | (rsi > 75)
    
    signals = pd.Series(0, index=df.index)
    signals[buy_sig] = 1
    signals[sell_sig] = -1
    return signals

def momentum_rotation_strategy_vectorized(df: pd.DataFrame,
                                           lookback=20,
                                           top_n=5) -> pd.Series:
    """
    Vectorized version of Momentum Rotation.
    Note: For a single ticker, this is just trend following. 
    Cross-ticker rotation requires a different handling in the backtester.
    """
    momentum = df['close'].pct_change(lookback)
    
    # Simple single-ticker momentum logic: Buy if positive, Sell if negative
    buy_sig = momentum > 0.02 # 2% growth threshold
    sell_sig = momentum < 0
    
    signals = pd.Series(0, index=df.index)
    signals[buy_sig] = 1
    signals[sell_sig] = -1
    return signals
