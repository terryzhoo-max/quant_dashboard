"""快速冒烟测试：ERP策略单次回测"""
from erp_backtest_data import prepare_erp_backtest_data
from backtest_engine import AlphaBacktester
from strategies_backtest import erp_timing_strategy_vectorized

print("=== ERP Strategy Smoke Test ===")

# 1. 宏观数据
macro_df = prepare_erp_backtest_data("20170101", "20251231")

# 2. ETF价格
bt = AlphaBacktester()
df = bt.fetch_tushare_data("510300.SH", "20180101", "20251231")
print(f"ETF rows: {len(df)}")

# 3. 信号
signals = erp_timing_strategy_vectorized(
    df, macro_df=macro_df, buy_threshold=65, sell_threshold=40
)
buy_n = (signals == 1).sum()
sell_n = (signals == -1).sum()
print(f"Signals: buy={buy_n}, sell={sell_n}, hold={(signals==0).sum()}")

# 4. 回测
results = bt.run_vectorized(df, signals, ts_code="510300.SH")
m = results["metrics"]
bm = results["bench_metrics"]
rt = results["round_trips"]
g = results["grade"]

print(f"\n--- Results ---")
print(f"Strategy Ann Return: {m['annualized_return']*100:.2f}%")
print(f"Benchmark Ann Return: {bm['annualized_return']*100:.2f}%")
print(f"Alpha: {m['alpha']*100:.2f}%")
print(f"Sharpe: {m['sharpe_ratio']:.3f}")
print(f"Sortino: {m['sortino_ratio']:.3f}")
print(f"Max Drawdown: {m['max_drawdown']*100:.2f}%")
print(f"Trades: {rt['total_trades']}, WinRate: {rt['win_rate']}%")
print(f"PnL Ratio: {rt['profit_loss_ratio']}")
print(f"Grade: {g['grade']} ({g['score']}pts)")
print(f"\n{'PASS - Alpha > 0' if m['alpha'] > 0 else 'CHECK - Alpha <= 0'}")
