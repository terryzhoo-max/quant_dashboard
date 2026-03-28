import requests
import json

def test_industrial_features():
    url = "http://127.0.0.1:8000/api/v1/backtest"
    
    # 1. Test POV and QFQ
    payload = {
        "strategy": "mr",
        "ts_code": "510300.SH",
        "start_date": "20230101",
        "end_date": "20240101",
        "order_pct": 0.05, # Significant impact
        "adj": "qfq"
    }
    
    print(f"Testing Single Backtest (POV=0.05, Adj=QFQ)...")
    try:
        r = requests.post("http://127.0.0.1:8000/api/v1/backtest", json=payload)
        res = r.json()
        if res.get('status') == 'success':
            m = res['data']['metrics']
            print(f"SUCCESS: Metrics Received: Sharpe={m['sharpe_ratio']:.2f}")
            if 'kelly_criterion' in m:
                print(f"SUCCESS: Kelly: {m['kelly_criterion']:.2f}")
            else:
                print(f"ERROR: Missing Kelly Metric")
            print(f"SUCCESS: Trade Log Count: {len(res['data']['trade_log'])}")
        else:
            print(f"ERROR: Failed: {res.get('message', 'Unknown Error')}")
    except Exception as e:
        print(f"ERROR: Connection Error: {e}")

    # 2. Test Batch PK Mode
    batch_url = "http://127.0.0.1:8000/api/v1/batch-backtest"
    batch_payload = {
        "items": [
            {**payload, "ts_code": "510300.SH"},
            {**payload, "ts_code": "510050.SH"}
        ]
    }
    print(f"\nTesting Batch PK Mode (510300 vs 510050)...")
    try:
        r = requests.post(batch_url, json=batch_payload)
        res = r.json()
        if res['status'] == 'success':
            print(f"SUCCESS: Batch Results: {len(res['data'])} results returned")
        else:
            print(f"ERROR: Batch Failed: {res.get('message')}")
    except Exception as e:
        print(f"ERROR: Connection Error: {e}")

if __name__ == "__main__":
    test_industrial_features()
