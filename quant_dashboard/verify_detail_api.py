import requests
import json

def verify_industry_detail():
    code = "512760.SH" # Semiconductor
    url = f"http://127.0.0.1:8000/api/v1/industry-detail?code={code}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data["status"] == "success":
            detail = data["data"]
            print(f"Code: {detail['code']}")
            print(f"Metrics: {detail['metrics']}")
            print(f"Chart Data Points: {len(detail['chart_data']['prices'])}")
            print(f"Constituents: {len(detail['metrics']['constituents'])}")
        else:
            print(f"API Error: {data.get('message')}")
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    verify_industry_detail()
