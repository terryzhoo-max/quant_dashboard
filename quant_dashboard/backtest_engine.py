"""
AlphaCore Backtest Engine V3.0
 - Signal → Position Tracking (致命修复: 脉冲信号→连续持仓)
 - Round-Trip Trade Analysis (交易轮次统计)
 - Strategy Grading S-A-B-C-D-F (策略评级)
 - Block Bootstrap Monte Carlo 500x (蒙特卡洛增强)
 - Structured Diagnosis Cards (结构化诊断卡片)
 - Enhanced Trade Log (单笔PnL + 盈亏标注)
 - Alpha / Information Ratio / Recovery Days
"""
import pandas as pd
import numpy as np
import time
import tushare as ts
from typing import Dict, List, Optional, Callable
import traceback
from datetime import datetime, timedelta

# Tushare Token
from config import TUSHARE_TOKEN
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
    AlphaCore Backtest Engine V3.0
    Industrial-Grade: Signal→Position fix, Round-Trip analysis, Strategy Grading, Block Bootstrap MC,
    Structured Diagnosis, Alpha/IR/Recovery metrics.
    """
    VERSION = "3.0"

    def __init__(self,
                 initial_cash: float = 1000000.0,
                 commission: float = 0.0005,
                 stamp_duty: float = 0.0005,
                 slippage_base: float = 0.001,
                 benchmark_code: str = "000300.SH"):
        self.initial_cash = initial_cash
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slippage_base = slippage_base
        self.benchmark_code = benchmark_code
        self.pro = pro

    # ========== Data Fetching ==========
    def fetch_tushare_data(self, ts_code: str, start_date: str, end_date: str, adj: str = 'qfq') -> pd.DataFrame:
        """Fetch historical fund daily data from Tushare with adjustment factors and retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f">>> [Tushare Fetch] Code: {ts_code}, Range: {start_date} to {end_date}, Attempt: {attempt+1}")
                df = self.pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    print(f">>> [Tushare Fetch] SUCCESS: {len(df)} rows for {ts_code}")
                    break
                else:
                    print(f">>> [Tushare Fetch] EMPTY/NONE Result for {ts_code}")
            except Exception as e:
                print(f">>> [Tushare Fetch] ATTEMPT {attempt+1} FAILED: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                else:
                    return pd.DataFrame()
        else:
            return pd.DataFrame()

        try:
            df = df.sort_values("trade_date").reset_index(drop=True)

            # Adjustment Factors (QFQ)
            if adj:
                try:
                    adj_df = self.pro.fund_adj(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    if adj_df is not None and not adj_df.empty:
                        df = pd.merge(df, adj_df[['trade_date', 'adj_factor']], on='trade_date', how='left')
                        df['adj_factor'] = df['adj_factor'].ffill().bfill().fillna(1.0)
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

    # ========== V2.0 Core: Signal → Position ==========
    def _signal_to_position(self, signals: pd.Series) -> pd.Series:
        """
        V2.0 致命修复: 将脉冲信号 {-1, 0, 1} 转为连续持仓 {0, 1}。
        规则: 1 → 开仓; -1 → 平仓; 0 → 保持前一状态 (forward-fill)。
        """
        position = pd.Series(0.0, index=signals.index)
        pos = 0.0
        for i in range(len(signals)):
            sig = signals.iloc[i]
            if sig == 1:
                pos = 1.0
            elif sig == -1:
                pos = 0.0
            # sig == 0 → pos stays unchanged
            position.iloc[i] = pos
        return position

    # ========== V2.0: Round-Trip Trade Analysis ==========
    def _extract_round_trips(self, data: pd.DataFrame, price_col: str = 'close') -> Dict:
        """
        提取完整交易轮次 (开仓→平仓) 并计算:
        - 交易轮次数, 轮次胜率, 盈亏比
        - 持仓天数中位数, 最大连续亏损笔数, 最大单笔亏损
        """
        pos = data['position']
        trades = []
        entry_date = None
        entry_price = None

        for i in range(1, len(pos)):
            # Entry: 0 → 1
            if pos.iloc[i] == 1 and pos.iloc[i-1] == 0:
                entry_date = data.index[i]
                entry_price = data[price_col].iloc[i]
            # Exit: 1 → 0
            elif pos.iloc[i] == 0 and pos.iloc[i-1] == 1:
                if entry_date is not None and entry_price is not None:
                    exit_date = data.index[i]
                    exit_price = data[price_col].iloc[i]
                    hold_days = (exit_date - entry_date).days
                    pnl_pct = (exit_price / entry_price - 1) * 100  # %
                    trades.append({
                        "entry_date": entry_date.strftime("%Y-%m-%d"),
                        "exit_date": exit_date.strftime("%Y-%m-%d"),
                        "entry_price": float(entry_price),
                        "exit_price": float(exit_price),
                        "hold_days": int(hold_days),
                        "pnl_pct": round(float(pnl_pct), 2),
                        "is_win": bool(pnl_pct > 0)
                    })
                    entry_date = None
                    entry_price = None

        if len(trades) == 0:
            return {
                "total_trades": 0, "win_trades": 0, "loss_trades": 0,
                "win_rate": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
                "profit_loss_ratio": 0, "median_hold_days": 0,
                "max_consecutive_loss": 0, "max_single_loss": 0,
                "trades": []
            }

        wins = [t for t in trades if t['is_win']]
        losses = [t for t in trades if not t['is_win']]
        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t['pnl_pct'] for t in losses])) if losses else 0.001

        # Max consecutive losses
        max_consec = 0
        consec = 0
        for t in trades:
            if not t['is_win']:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0

        return {
            "total_trades": len(trades),
            "win_trades": len(wins),
            "loss_trades": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_loss_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
            "median_hold_days": int(np.median([t['hold_days'] for t in trades])),
            "max_consecutive_loss": max_consec,
            "max_single_loss": round(min(t['pnl_pct'] for t in trades), 2) if trades else 0,
            "trades": trades[-50:]  # last 50 for display
        }

    # ========== V2.0: Strategy Grading ==========
    def _calculate_strategy_grade(self, metrics: Dict, round_trips: Dict) -> Dict:
        """
        策略评级 S-A-B-C-D-F (基于A股实证阈值)
        六维计分: Sharpe, Calmar, MDD, 轮次胜率, 盈亏比, Sortino
        """
        sharpe = metrics.get("sharpe_ratio", 0)
        calmar = metrics.get("calmar_ratio", 0)
        mdd = abs(metrics.get("max_drawdown", 0))
        sortino = metrics.get("sortino_ratio", 0)
        win_rate = round_trips.get("win_rate", 0)
        plr = round_trips.get("profit_loss_ratio", 0)

        # 每维 0-100 分
        def score_sharpe(v):
            if v >= 2.5: return 100
            if v >= 2.0: return 90
            if v >= 1.5: return 75
            if v >= 1.0: return 60
            if v >= 0.5: return 40
            if v >= 0: return 20
            return 0

        def score_calmar(v):
            if v >= 3.0: return 100
            if v >= 2.0: return 85
            if v >= 1.0: return 65
            if v >= 0.5: return 45
            if v >= 0: return 20
            return 0

        def score_mdd(v):
            if v <= 0.05: return 100
            if v <= 0.10: return 85
            if v <= 0.15: return 70
            if v <= 0.20: return 55
            if v <= 0.30: return 35
            return 15

        def score_sortino(v):
            if v >= 3.0: return 100
            if v >= 2.0: return 80
            if v >= 1.0: return 60
            if v >= 0.5: return 40
            if v >= 0: return 20
            return 0

        def score_winrate(v):
            if v >= 70: return 100
            if v >= 60: return 80
            if v >= 55: return 65
            if v >= 50: return 50
            if v >= 45: return 35
            return 15

        def score_plr(v):
            if v >= 3.0: return 100
            if v >= 2.0: return 80
            if v >= 1.5: return 65
            if v >= 1.0: return 45
            if v >= 0.5: return 25
            return 10

        breakdown = {
            "sharpe": score_sharpe(sharpe),
            "calmar": score_calmar(calmar),
            "drawdown": score_mdd(mdd),
            "sortino": score_sortino(sortino),
            "win_rate": score_winrate(win_rate),
            "profit_loss": score_plr(plr)
        }

        # Weighted: Sharpe 25%, Calmar 20%, MDD 20%, Sortino 15%, WinRate 10%, PLR 10%
        weights = {"sharpe": 0.25, "calmar": 0.20, "drawdown": 0.20,
                   "sortino": 0.15, "win_rate": 0.10, "profit_loss": 0.10}
        total_score = sum(breakdown[k] * weights[k] for k in weights)
        total_score = round(total_score, 1)

        # Grade mapping
        if total_score >= 85:
            grade = "S"
        elif total_score >= 70:
            grade = "A"
        elif total_score >= 55:
            grade = "B"
        elif total_score >= 40:
            grade = "C"
        elif total_score >= 25:
            grade = "D"
        else:
            grade = "F"

        return {
            "score": total_score,
            "grade": grade,
            "breakdown": breakdown
        }

    # ========== V3.0: Structured Diagnosis Cards ==========
    def _generate_diagnosis(self, metrics: Dict, bench_metrics: Dict,
                            round_trips: Dict, grade_info: Dict) -> list:
        """V3.0: 返回结构化诊断卡片列表 [{label, text, level}]"""
        cards = []

        ann_ret = metrics.get("annualized_return", 0) * 100
        alpha_val = metrics.get("alpha", 0) * 100
        sharpe = metrics.get("sharpe_ratio", 0)
        mdd = abs(metrics.get("max_drawdown", 0)) * 100
        recovery = metrics.get("recovery_days", -1)
        ir = metrics.get("information_ratio", 0)
        rt = round_trips

        # Card 1: 综合评级
        grade_labels = {"S": "顶级策略", "A": "优质策略", "B": "可用策略",
                        "C": "边缘策略", "D": "劣质策略", "F": "无效策略"}
        g = grade_info['grade']
        level_map = {"S": "success", "A": "success", "B": "info", "C": "warning", "D": "danger", "F": "danger"}
        cards.append({
            "label": "综合评级",
            "text": f"{g}级 ({grade_info['score']}分) — {grade_labels.get(g, '')}",
            "level": level_map.get(g, "info")
        })

        # Card 2: 收益 & Alpha
        if alpha_val > 0:
            cards.append({"label": "收益", "text": f"年化 {ann_ret:.1f}%，Alpha {alpha_val:+.1f}%", "level": "success"})
        else:
            cards.append({"label": "收益", "text": f"年化 {ann_ret:.1f}%，Alpha {alpha_val:+.1f}%", "level": "danger"})

        # Card 3: 风险效率
        if sharpe >= 1.5:
            cards.append({"label": "风险效率", "text": f"Sharpe {sharpe:.2f} · IR {ir:.2f} → 优秀", "level": "success"})
        elif sharpe >= 0.5:
            cards.append({"label": "风险效率", "text": f"Sharpe {sharpe:.2f} · IR {ir:.2f} → 偏弱", "level": "warning"})
        else:
            cards.append({"label": "风险效率", "text": f"Sharpe {sharpe:.2f} · IR {ir:.2f} → 无效", "level": "danger"})

        # Card 4: 回撤 & 修复
        recovery_text = f"{recovery}天修复" if recovery > 0 else "未修复" if recovery < 0 else "无回撤"
        if mdd > 25:
            cards.append({"label": "风控", "text": f"MDD -{mdd:.1f}% · {recovery_text}", "level": "danger"})
        elif mdd > 15:
            cards.append({"label": "风控", "text": f"MDD -{mdd:.1f}% · {recovery_text}", "level": "warning"})
        else:
            cards.append({"label": "风控", "text": f"MDD -{mdd:.1f}% · {recovery_text}", "level": "success"})

        # Card 5: 交易质量
        if rt["total_trades"] > 0:
            txt = f"{rt['total_trades']}轮 · 胜率{rt['win_rate']}% · 盈亏比{rt['profit_loss_ratio']}:1"
            if rt["max_consecutive_loss"] >= 5:
                txt += f" · 连亏{rt['max_consecutive_loss']}笔"
            lvl = "success" if rt['win_rate'] >= 55 and rt['profit_loss_ratio'] >= 1.5 else \
                  "warning" if rt['win_rate'] >= 45 else "danger"
            cards.append({"label": "交易质量", "text": txt, "level": lvl})
        else:
            cards.append({"label": "交易质量", "text": "无完整交易轮次，信号过于稀疏", "level": "danger"})

        return cards

    # ========== Core Metrics (V3.0) ==========
    def calculate_metrics(self, equity_series: pd.Series, returns: pd.Series,
                          bench_returns: pd.Series = None) -> Dict:
        """Calculate professional risk-adjusted metrics (V3.0: +Alpha, IR, Recovery)."""
        if len(equity_series) < 2:
            return {}

        total_return = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1
        days = (equity_series.index[-1] - equity_series.index[0]).days
        if days == 0:
            days = 1
        annualized_return = (1 + total_return) ** (365 / days) - 1

        # Volatility
        daily_vol = returns.std()
        annualized_vol = daily_vol * np.sqrt(243)  # A-share: 243 trading days

        downside_returns = returns[returns < 0]
        downside_vol = (downside_returns.std() * np.sqrt(243)) if not downside_returns.empty else 0.001

        # Drawdown
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()

        # === V3.0: Recovery Days (MDD → New High) ===
        recovery_days = 0
        try:
            mdd_idx = drawdown.idxmin()
            post_mdd = equity_series.loc[mdd_idx:]
            recovery_mask = post_mdd >= rolling_max.loc[mdd_idx]
            if recovery_mask.any():
                recovery_date = recovery_mask.idxmax()
                recovery_days = (recovery_date - mdd_idx).days
            else:
                recovery_days = -1  # Never recovered
        except Exception:
            recovery_days = -1

        # Ratios
        rf_rate = 0.02
        excess_return = annualized_return - rf_rate

        sharpe_ratio = excess_return / annualized_vol if annualized_vol > 0 else 0
        sortino_ratio = excess_return / downside_vol if downside_vol > 0 else 0
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0

        # === V3.0: Alpha & Information Ratio ===
        alpha = 0.0
        information_ratio = 0.0
        if bench_returns is not None and len(bench_returns) == len(returns):
            bench_total = (1 + bench_returns).prod() - 1
            bench_ann = (1 + bench_total) ** (365 / days) - 1
            alpha = annualized_return - bench_ann
            # Tracking Error = std(strategy_returns - benchmark_returns) * sqrt(243)
            active_returns = returns - bench_returns
            tracking_error = active_returns.std() * np.sqrt(243)
            information_ratio = alpha / tracking_error if tracking_error > 0 else 0

        # Tail Risk
        var_95 = np.percentile(returns, 5) if not returns.empty else 0
        expected_shortfall = returns[returns <= var_95].mean() if not returns.empty else 0
        skew = returns.skew() if len(returns) > 2 else 0
        kurt = returns.kurtosis() if len(returns) > 2 else 0

        # Daily win stats
        win_rate = len(returns[returns > 0]) / len(returns) if len(returns) > 0 else 0
        avg_win = returns[returns > 0].mean() if not returns[returns > 0].empty else 0
        avg_loss = abs(returns[returns < 0].mean()) if not returns[returns < 0].empty else 0.001
        profit_factor = (returns[returns > 0].sum() / abs(returns[returns < 0].sum())) if abs(returns[returns < 0].sum()) > 0 else 1.0

        # Kelly Criterion
        r_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        kelly = win_rate - (1 - win_rate) / r_ratio if r_ratio > 0 else 0

        return {
            "total_return": float(total_return),
            "annualized_return": float(annualized_return),
            "annualized_vol": float(annualized_vol),
            "max_drawdown": float(max_drawdown),
            "recovery_days": int(recovery_days),
            "sharpe_ratio": float(sharpe_ratio),
            "sortino_ratio": float(sortino_ratio),
            "calmar_ratio": float(calmar_ratio),
            "alpha": float(alpha),
            "information_ratio": float(information_ratio),
            "var_95": float(var_95),
            "expected_shortfall": float(expected_shortfall),
            "skew": float(skew),
            "kurtosis": float(kurt),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor),
            "kelly_criterion": float(kelly),
            "days_tested": int(days)
        }

    # ========== V2.0: Vectorized Simulation ==========
    def run_vectorized(self,
                       df: pd.DataFrame,
                       signal_df: pd.Series,
                       ts_code: str = "Unknown",
                       order_pct: float = 0.01,
                       price_col: str = 'close',
                       pov_penalty: float = 0.2) -> Dict:
        """
        V2.0 向量化回测引擎:
        - Signal → Position 持仓转换 (修复致命Bug)
        - Round-Trip 交易轮次分析
        - 策略评级 S-F
        - 诊断文本
        """
        if df.empty or signal_df.empty:
            return {"error": "Empty data or signals"}

        data = df.copy()
        data['signal'] = signal_df

        # === V2.0 致命修复: Signal → Continuous Position ===
        data['position'] = self._signal_to_position(data['signal'])

        # Anti Look-ahead: 用T日信号决定T+1日仓位
        data['position'] = data['position'].shift(1).fillna(0)

        # === POV Impact Model ===
        if 'volume' in data.columns:
            data['adv'] = data['volume'].rolling(window=20).mean()
        data['pov_impact'] = order_pct * pov_penalty
        data['slippage'] = self.slippage_base + data['pov_impact']

        data['trades'] = data['position'].diff().fillna(0).abs()
        data['fees'] = data['trades'] * (self.commission + data['slippage'])

        # Stamp duty on SELL only
        sell_signals = (data['position'].diff() < 0).astype(int)
        data['fees'] += sell_signals * self.stamp_duty

        # Returns
        data['daily_pct'] = data[price_col].pct_change().fillna(0)
        data['strat_returns'] = data['position'] * data['daily_pct'] - data['fees']
        data['equity_curve'] = (1 + data['strat_returns']).cumprod() * self.initial_cash

        # Benchmark
        data['bench_returns'] = data[price_col].pct_change().fillna(0)
        data['bench_curve'] = (1 + data['bench_returns']).cumprod() * self.initial_cash

        # Metrics (V3.0: pass bench_returns for Alpha/IR)
        metrics = self.calculate_metrics(data['equity_curve'], data['strat_returns'],
                                         bench_returns=data['bench_returns'])
        bench_metrics = self.calculate_metrics(data['bench_curve'], data['bench_returns'])

        # === V3.0: Round-Trip Analysis ===
        round_trips = self._extract_round_trips(data, price_col)

        # === V3.0: Strategy Grade ===
        grade_info = self._calculate_strategy_grade(metrics, round_trips)

        # === V3.0: Structured Diagnosis ===
        diagnosis = self._generate_diagnosis(metrics, bench_metrics, round_trips, grade_info)

        # Enhanced Trade Log (V3.0: SELL entries get PnL from round_trips)
        trades_idx = data[data['trades'] > 0].index
        trade_log = []
        rt_trades = round_trips.get('trades', [])
        rt_sell_map = {t['exit_date']: t['pnl_pct'] for t in rt_trades}  # date → pnl%

        for i in range(len(trades_idx)):
            idx = trades_idx[i]
            row = data.loc[idx]
            is_buy = row['position'] > (data['position'].shift(1).get(idx, 0))
            entry = {
                "date": idx.strftime("%Y-%m-%d"),
                "price": round(float(row[price_col]), 4),
                "type": "BUY" if is_buy else "SELL",
                "position": float(row['position']),
                "equity": round(float(row['equity_curve']), 0)
            }
            # V3.0: Attach PnL to SELL entries
            if not is_buy:
                date_str = idx.strftime("%Y-%m-%d")
                entry["pnl_pct"] = rt_sell_map.get(date_str, None)
            trade_log.append(entry)

        # Monthly Returns for Heatmap
        monthly_returns = {}
        try:
            monthly_eq = data['equity_curve'].resample('ME').last()
            monthly_pct = monthly_eq.pct_change().dropna()
            for idx_m, val in monthly_pct.items():
                monthly_returns[idx_m.strftime("%Y-%m")] = float(val)
        except Exception as e:
            print(f"Monthly returns calc warning: {e}")

        # Yearly summary for heatmap
        yearly_returns = {}
        try:
            yearly_eq = data['equity_curve'].resample('YE').last()
            yearly_pct = yearly_eq.pct_change().dropna()
            for idx_y, val in yearly_pct.items():
                yearly_returns[str(idx_y.year)] = float(val)
        except Exception:
            pass

        return {
            "ts_code": ts_code,
            "version": "V3.0",
            "metrics": metrics,
            "bench_metrics": bench_metrics,
            "grade": grade_info,
            "round_trips": round_trips,
            "diagnosis": diagnosis,
            "equity_curve": data['equity_curve'].tolist(),
            "bench_curve": data['bench_curve'].tolist(),
            "dates": data.index.strftime("%Y-%m-%d").tolist(),
            "drawdown": ((data['equity_curve'] - data['equity_curve'].cummax()) / data['equity_curve'].cummax()).tolist(),
            "trade_log": trade_log,
            "monthly_returns": monthly_returns,
            "yearly_returns": yearly_returns
        }

    # ========== V2.0: Block Bootstrap Monte Carlo ==========
    def run_monte_carlo(self, returns: pd.Series, iterations: int = 500, block_size: int = 20) -> Dict:
        """
        V2.0 Block Bootstrap Monte Carlo: 保留序列自相关结构。
        Returns: percentile curves + ruin probability.
        """
        if returns.empty or len(returns) < block_size:
            return {"p5": [], "p50": [], "p95": [], "ruin_pct": 0}

        n = len(returns)
        returns_arr = returns.values
        n_blocks = n // block_size + 1

        # Block bootstrap: sample blocks of consecutive returns
        terminal_values = []
        p5_curve = []
        p50_curve = []
        p95_curve = []

        all_paths = np.zeros((iterations, n))
        for sim in range(iterations):
            # Sample random block start indices
            block_starts = np.random.randint(0, n - block_size + 1, size=n_blocks)
            sampled = np.concatenate([returns_arr[s:s+block_size] for s in block_starts])[:n]
            equity = np.cumprod(1 + sampled) * self.initial_cash
            all_paths[sim] = equity
            terminal_values.append(equity[-1])

        # Percentile curves at each timestep
        for t in range(n):
            col = all_paths[:, t]
            sorted_col = np.sort(col)
            p5_curve.append(float(sorted_col[int(iterations * 0.05)]))
            p50_curve.append(float(sorted_col[int(iterations * 0.50)]))
            p95_curve.append(float(sorted_col[int(iterations * 0.95)]))

        # Ruin probability: P(max_drawdown > 30%)
        ruin_count = 0
        for sim in range(iterations):
            eq = all_paths[sim]
            peak = np.maximum.accumulate(eq)
            dd = (eq - peak) / peak
            if dd.min() < -0.30:
                ruin_count += 1

        return {
            "p5": p5_curve,
            "p50": p50_curve,
            "p95": p95_curve,
            "ruin_pct": round(ruin_count / iterations * 100, 1),
            "terminal_median": round(float(np.median(terminal_values)), 0),
            "terminal_p5": round(float(np.percentile(terminal_values, 5)), 0),
            "terminal_p95": round(float(np.percentile(terminal_values, 95)), 0)
        }

    # ========== Grid Search ==========
    def run_grid_search(self,
                        df: pd.DataFrame,
                        strategy_func: Callable,
                        param_grid: Dict[str, List]) -> List[Dict]:
        """Run grid search over parameters."""
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


# CLI Test
if __name__ == "__main__":
    bt = AlphaBacktester()
    print(f"AlphaCore Backtest Engine {bt.VERSION} — Ready")
