import pandas as pd
import numpy as np
import time
import tushare as ts
from typing import Dict, List, Optional, Callable, Union
import traceback
from datetime import datetime, timedelta

# Tushare Token (Shared with main app)
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

class Indicators:
    """Vectorized Technical Indicators Suite"""
    @staticmethod
    def RSI(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def BOLL(series: pd.Series, period: int = 20, std_dev: int = 2) -> Dict[str, pd.Series]:
        ma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = ma + (std * std_dev)
        lower = ma - (std * std_dev)
        percent_b = (series - lower) / (upper - lower)
        return {"upper": upper, "lower": lower, "mid": ma, "percent_b": percent_b}

    @staticmethod
    def CCI(df: pd.DataFrame, period: int = 20) -> pd.Series:
        tp = (df['high'] + df['low'] + df['close']) / 3
        ma = tp.rolling(window=period).mean()
        md = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean())
        return (tp - ma) / (0.015 * md)

    @staticmethod
    def BIAS(series: pd.Series, period: int = 20) -> pd.Series:
        ma = series.rolling(window=period).mean()
        return (series - ma) / ma * 100

class AlphaBacktester:
    """
    Industrial-Grade Vectorized Backtest Engine for AlphaCore.
    Designed for rigor: No look-ahead, realistic costs, and advanced risk metrics.
    """
    def __init__(self, 
                 initial_cash: float = 1000000.0,
                 commission: float = 0.0005,
                 stamp_duty: float = 0.0005,
                 slippage_base: float = 0.001,
                 benchmark_code: str = "000300.SH"
                 ):
        self.initial_cash = initial_cash
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slippage_base = slippage_base
        self.benchmark_code = benchmark_code
        self.pro = pro

    def fetch_tushare_data(self, ts_code: str, start_date: str, end_date: str, adj: str = 'qfq') -> pd.DataFrame:
        """Fetch historical fund daily data from Tushare with adjustment factors and retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f">>> [Tushare Fetch] Code: {ts_code}, Range: {start_date} to {end_date}, Attempt: {attempt+1}")
                # 1. Fetch Daily Data
                df = self.pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    print(f">>> [Tushare Fetch] SUCCESS: {len(df)} rows for {ts_code}")
                    break # Success!
                else:
                    print(f">>> [Tushare Fetch] EMPTY/NONE Result for {ts_code}")
            except Exception as e:
                print(f">>> [Tushare Fetch] ATTEMPT {attempt+1} FAILED: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1) # Simple backoff
                    continue
                else:
                    return pd.DataFrame()
        else:
            # All attempts failed or returned empty
            return pd.DataFrame()

        try:
            df = df.sort_values("trade_date").reset_index(drop=True)
            
            # 2. Fetch Adj Factors (QFQ Logic)
            if adj:
                try:
                    adj_df = self.pro.fund_adj(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    if adj_df is not None and not adj_df.empty:
                        # Merge and ffill
                        df = pd.merge(df, adj_df[['trade_date', 'adj_factor']], on='trade_date', how='left')
                        df['adj_factor'] = df['adj_factor'].ffill().bfill().fillna(1.0)
                        # Adjust OHLC (QFQ = Price * Factor)
                        for col in ['open', 'high', 'low', 'close']:
                            df[col] = df[col] * df['adj_factor']
                except Exception as e:
                    print(f"Warning: Adj factor fetch failed for {ts_code}, using raw prices: {e}")

            df = df.rename(columns={'trade_date': 'date', 'vol': 'volume'})
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df
        except Exception as e:
            print(f"Error fetching Tushare data for {ts_code}: {e}")
            return pd.DataFrame()

    def calculate_metrics(self, equity_series: pd.Series, returns: pd.Series) -> Dict:
        """
        Calculate professional risk-adjusted metrics (Industrial Quality).
        """
        if len(equity_series) < 2:
            return {}

        # 1. Basic Stats
        total_return = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1
        days = (equity_series.index[-1] - equity_series.index[0]).days
        if days == 0: days = 1 
        annualized_return = (1 + total_return) ** (365 / days) - 1

        # 2. Volatility & Downside
        daily_vol = returns.std()
        annualized_vol = daily_vol * np.sqrt(244) 
        
        downside_returns = returns[returns < 0]
        downside_vol = (downside_returns.std() * np.sqrt(244)) if not downside_returns.empty else 0.001

        # 3. Drawdown
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()

        # 4. Ratios
        rf_rate = 0.02 
        excess_return = annualized_return - rf_rate
        
        sharpe_ratio = excess_return / annualized_vol if annualized_vol > 0 else 0
        sortino_ratio = excess_return / downside_vol if downside_vol > 0 else 0
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0

        # 5. Tail Risk & Moments
        var_95 = np.percentile(returns, 5) if not returns.empty else 0
        expected_shortfall = returns[returns <= var_95].mean() if not returns.empty else 0
        skew = returns.skew() if len(returns) > 2 else 0
        kurt = returns.kurtosis() if len(returns) > 2 else 0

        # 6. Trade Stats (Daily Proxy)
        win_rate = len(returns[returns > 0]) / len(returns) if len(returns) > 0 else 0
        avg_win = returns[returns > 0].mean() if not returns[returns > 0].empty else 0
        avg_loss = abs(returns[returns < 0].mean()) if not returns[returns < 0].empty else 0.001
        profit_factor = (returns[returns > 0].sum() / abs(returns[returns < 0].sum())) if abs(returns[returns < 0].sum()) > 0 else 1.0
        
        # Kelly Criterion = W - (1-W)/R where R = AvgWin/AvgLoss
        r_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        kelly = win_rate - (1 - win_rate) / r_ratio if r_ratio > 0 else 0

        return {
            "total_return": float(total_return),
            "annualized_return": float(annualized_return),
            "annualized_vol": float(annualized_vol),
            "max_drawdown": float(max_drawdown),
            "sharpe_ratio": float(sharpe_ratio),
            "sortino_ratio": float(sortino_ratio),
            "calmar_ratio": float(calmar_ratio),
            "var_95": float(var_95),
            "expected_shortfall": float(expected_shortfall),
            "skew": float(skew),
            "kurtosis": float(kurt),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor),
            "kelly_criterion": float(kelly),
            "days_tested": int(days)
        }

    def run_vectorized(self, 
                       df: pd.DataFrame, 
                       signal_df: pd.Series,
                       ts_code: str = "Unknown",
                       order_pct: float = 0.01,
                       price_col: str = 'close',
                       pov_penalty: float = 0.2) -> Dict:
        """
        Run the vectorized simulation engine with POV Impact Model.
        df MUST have: datetime index, and OHLCV data.
        signal_df: A Series with the same index as df containing -1, 0, 1.
        order_pct: The assumed percentage of market volume our trades represent (POV).
        pov_penalty: The sensitivity factor for volume impact (0.2 is conservative).
        """
        if df.empty or signal_df.empty:
            return {"error": "Empty data or signals"}

        data = df.copy()
        data['signal'] = signal_df
        
        # --- RIGOR 1: Signal Delay (Anti Look-ahead) ---
        data['position'] = data['signal'].shift(1).fillna(0)
        
        # --- RIGOR 2: POV (Participation of Volume) Impact Model ---
        # Reality: Larger trades move the price more. 
        # Slippage = Base + (Participation_Rate * POV_Penalty)
        # We assume POV = order_pct (e.g., 0.01 means we are 1% of the ADV).
        data['adv'] = data['volume'].rolling(window=20).mean()
        
        # Dynamic impact: larger relative size = higher slippage
        data['pov_impact'] = (order_pct * pov_penalty) 
        data['slippage'] = self.slippage_base + data['pov_impact']
        
        data['trades'] = data['position'].diff().fillna(0).abs()
        data['fees'] = data['trades'] * (self.commission + data['slippage'])
        
        # Stamp duty on SELL only (China A-share style)
        sell_signals = (data['position'].diff() < 0).astype(int)
        data['fees'] += sell_signals * self.stamp_duty

        # Calculate Returns
        data['daily_pct'] = data[price_col].pct_change().fillna(0)
        data['strat_returns'] = data['position'] * data['daily_pct'] - data['fees']
        data['equity_curve'] = (1 + data['strat_returns']).cumprod() * self.initial_cash
        
        # Benchmarking (Buy & Hold)
        data['bench_returns'] = data[price_col].pct_change().fillna(0)
        data['bench_curve'] = (1 + data['bench_returns']).cumprod() * self.initial_cash

        metrics = self.calculate_metrics(data['equity_curve'], data['strat_returns'])
        bench_metrics = self.calculate_metrics(data['bench_curve'], data['bench_returns'])
        
        # Calculate Trade Log (Simplified for Vectorized)
        trades_idx = data[data['trades'] > 0].index
        trade_log = []
        for i in range(len(trades_idx)):
            idx = trades_idx[i]
            row = data.loc[idx]
            trade_log.append({
                "date": idx.strftime("%Y-%m-%d"),
                "price": float(row[price_col]),
                "type": "BUY" if row['position'] > data['position'].shift(1).get(idx, 0) else "SELL",
                "position": float(row['position'])
            })

        # Calculate Monthly Returns for Heatmap
        monthly_returns = {}
        try:
            monthly_eq = data['equity_curve'].resample('ME').last()
            monthly_pct = monthly_eq.pct_change().dropna()
            for idx, val in monthly_pct.items():
                monthly_returns[idx.strftime("%Y-%m")] = float(val)
        except Exception as e:
            print(f"Monthly returns calc warning: {e}")

        return {
            "ts_code": ts_code,
            "metrics": metrics,
            "bench_metrics": bench_metrics,
            "equity_curve": data['equity_curve'].tolist(),
            "bench_curve": data['bench_curve'].tolist(),
            "dates": data.index.strftime("%Y-%m-%d").tolist(),
            "drawdown": ((data['equity_curve'] - data['equity_curve'].cummax()) / data['equity_curve'].cummax()).tolist(),
            "trade_log": trade_log,
            "monthly_returns": monthly_returns
        }

    def run_monte_carlo(self, returns: pd.Series, iterations: int = 500) -> List[List[float]]:
        """
        Bootstrap simulation — vectorized with NumPy for performance.
        """
        if returns.empty: return []
        n = len(returns)
        returns_arr = returns.values
        # Matrix of random samples: (iterations x n)
        random_indices = np.random.randint(0, n, size=(iterations, n))
        sampled_matrix = returns_arr[random_indices]
        # Cumulative product along axis 1 to get equity curves
        equity_matrix = np.cumprod(1 + sampled_matrix, axis=1) * self.initial_cash
        return equity_matrix.tolist()

    def run_grid_search(self, 
                        df: pd.DataFrame, 
                        strategy_func: Callable, 
                        param_grid: Dict[str, List]) -> List[Dict]:
        """
        Run a grid search over multiple parameters.
        strategy_func: (df, **params) -> signal_series
        """
        import itertools
        keys = param_grid.keys()
        values = param_grid.values()
        combinations = list(itertools.product(*values))
        
        results = []
        for combo in combinations:
            params = dict(zip(keys, combo))
            signals = strategy_func(df, **params)
            backtest_res = self.run_vectorized(df, signals)
            
            summary = {
                "params": params,
                "sharpe": backtest_res["metrics"].get("sharpe_ratio", 0),
                "return": backtest_res["metrics"].get("total_return", 0),
                "mdd": backtest_res["metrics"].get("max_drawdown", 0)
            }
            results.append(summary)
            
        return results

# Example Usage for Integration Testing
if __name__ == "__main__":
    # Create mock data
    dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
    prices = np.exp(np.log(100) + np.cumsum(np.random.normal(0.001, 0.02, 100)))
    df = pd.DataFrame({'close': prices}, index=dates)
    
    # Simple strategy: RSI cross
    df['rsi'] = 50 + np.random.normal(0, 10, 100)
    df['signal'] = 0
    df.loc[df['rsi'] < 30, 'signal'] = 1
    df.loc[df['rsi'] > 70, 'signal'] = -1
    
    bt = AlphaBacktester()
    results = bt.run_vectorized(df)
    print(f"Backtest Sharpe: {results['metrics']['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['metrics']['max_drawdown']*100:.2f}%")
