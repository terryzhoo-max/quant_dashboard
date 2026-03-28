import requests
import json
from datetime import datetime, timedelta

def test_backtest_api():
    url = "http://127.0.0.1:8000/api/v1/backtest"
    
    # 1. Mean Reversion Backtest Request
    payload = {
        "strategy": "mr",
        "ts_code": "510300.SH", # 沪深300 ETF
        "start_date": "20230101",
        "end_date": "20240320",
        "initial_cash": 1000000.0,
        "params": {
            "rsi_period": 3,
            "rsi_buy": 15,
            "rsi_sell": 80
        }
    }
    
    print(f"Sending backtest request for {payload['ts_code']}...")
    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            res_data = response.json()
            if "error" in res_data:
                print(f"API Error: {res_data['error']}")
            else:
                metrics = res_data["metrics"]
                print("\n✅ Backtest Successful!")
                print(f"Total Return: {metrics['total_return']*100:.2f}%")
                print(f"Annualized Return: {metrics['annualized_return']*100:.2f}%")
                print(f"Max Drawdown: {metrics['max_drawdown']*100:.2f}%")
                print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
                print(f"Profit Factor: {metrics['profit_factor']:.2f}")
                print(f"Days Tested: {metrics['days_tested']}")
                print(f"Equity Curve Points: {len(res_data['equity_curve'])}")
        else:
            print(f"HTTP Error: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    # Ensure the server is running before executing this
    test_backtest_api()
