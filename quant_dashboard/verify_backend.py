import requests
import json

def test_api():
    try:
        url = "http://127.0.0.1:8000/api/v1/dashboard-data"
        print(f"Requesting {url}...")
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            print("API Response Success:")
            macro = data['data']['macro_cards']
            print(f"Capital Value: {macro['capital']['value']}")
            print(f"Capital Trend: {macro['capital']['trend']}")
            print(f"Market Temp: {macro['market_temp']['value']}° ({macro['market_temp']['label']})")
            print(f"Position Advice: {macro['market_temp']['advice']}")
            
            print("\nSector Heatmap (Sample):")
            heatmap = data['data']['sector_heatmap']
            if heatmap and len(heatmap) > 0:
                s = heatmap[0]
                print(f"Name: {s['name']}, 1D: {s['change']}%, 5D: {s.get('trend_5d', 'N/A')}%, RPS: {s.get('rps', 'N/A')}")
            else:
                print("No heatmap data")
        else:
            print(f"API Error: {resp.status_code}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_api()
