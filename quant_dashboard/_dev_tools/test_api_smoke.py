import requests
import json

url = "http://127.0.0.1:8000/api/v1/backtest"
payload = {
    "strategy": "mr",
    "ts_code": "510300.SH",
    "start_date": "20230101",
    "end_date": "20231231",
    "initial_cash": 1000000,
    "order_pct": 0.01,
    "adj": "qfq",
    "benchmark_code": "000300.SH",
    "params": {"rsi_period": 3, "rsi_buy": 15, "rsi_sell": 85}
}

print("Testing MR strategy for 510300.SH...")
r = requests.post(url, json=payload, timeout=60)
result = r.json()
print(f"Status: {result['status']}")
if result['status'] == 'success':
    data = result['data']
    print(f"ts_code in result: {data.get('ts_code', 'MISSING')}")
    print(f"Equity curve length: {len(data.get('equity_curve', []))}")
    print(f"Dates length: {len(data.get('dates', []))}")
    m = data['metrics']
    print(f"Total Return: {m['total_return']*100:.2f}%")
    print(f"Sharpe: {m['sharpe_ratio']:.2f}")
    print(f"Max DD: {m['max_drawdown']*100:.2f}%")
else:
    print(f"Error: {result.get('message', 'unknown')}")

# Test momentum strategy (should NOT crash with rsi params)
print("\n--- Testing MOM strategy ---")
payload2 = {**payload, "strategy": "mom"}
r2 = requests.post(url, json=payload2, timeout=60)
result2 = r2.json()
print(f"MOM Status: {result2['status']}")
if result2['status'] == 'success':
    print(f"MOM Return: {result2['data']['metrics']['total_return']*100:.2f}%")
else:
    print(f"MOM Error: {result2.get('message')}")
