from dividend_backtest_engine import *
import warnings
warnings.filterwarnings('ignore')

codes = [item['code'] for item in DIVIDEND_POOL] + [BENCHMARK_CODE]
prices = load_prices(codes, '2022-01-01', '2023-12-31')
bm = prices[BENCHMARK_CODE]
etf = prices.drop(columns=[BENCHMARK_CODE])

m = fast_backtest(etf, bm, DEFAULT_PARAMS)
print('默认参数单次回测验证:')
print(f'  年化收益: {m["ann_ret"]}% vs 基准: {m["ann_bm"]}%')
print(f'  Alpha: {m["alpha"]}%  MaxDD: {m["max_dd"]}%')
print(f'  Sharpe: {m["sharpe"]}  Calmar: {m["calmar"]}')
print(f'  WinRate: {m["win_rate"]}%  Score: {m["score"]}')
