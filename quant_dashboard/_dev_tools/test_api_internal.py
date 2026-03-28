import requests
import json
import time

url = "http://127.0.0.1:8000/api/v1/backtest"
payload = {
    "strategy": "mr",
    "ts_code": "510300.SH",
    "start_date": "20240101",
    "end_date": "20250101",
    "initial_cash": 1000000,
    "params": {"rsi_period": 3, "rsi_buy": 10, "rsi_sell": 85}
}

for i in range(3):
    try:
        print(f"[{i+1}] Testing POST to {url}...")
        response = requests.post(url, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                metrics = data['data']['metrics']
                print(f"Backtest Success! Sharpe: {metrics.get('sharpe_ratio'):.2f}")
                break
            else:
                print(f"API Error: {data.get('message')}")
        else:
            print(f"HTTP Error: {response.text}")
    except Exception as e:
        print(f"Attempt {i+1} failed: {e}")
        time.sleep(2)
