import requests
import json

def test_industry_api():
    url = "http://127.0.0.1:8000/api/v1/industry-tracking"
    
    try:
        print("Sending request to Industry Tracking API...")
        response = requests.get(url, timeout=120)
        print(f"Status Code: {response.status_code}")
        
        result = response.json()
        if result.get("status") == "success":
            data = result["data"]
            print("[SUCCESS] Result parsed.")
            print(f"Industries in Performance: {len(data['performance'])}")
            print(f"Industries in Rotation: {list(data['rotation'].keys())}")
            print(f"HSGT Inflow Top: {data['hsgt'][0]['name'] if data['hsgt'] else 'N/A'}")
        else:
            print(f"[ERROR] {result.get('message')}")
            
    except Exception as e:
        print(f"[EXCEPTION] {e}")

if __name__ == "__main__":
    test_industry_api()
