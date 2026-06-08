import requests

r = requests.get(
    "https://api.stlouisfed.org/fred/series/observations",
    params={
        "series_id": "VIXCLS",
        "api_key": "64f63f8d24fda344481f02848f71f6ac",
        "sort_order": "desc",
        "limit": "10",
        "file_type": "json",
    },
    timeout=15,
)
data = r.json()
print("=== FRED VIXCLS 最近10个交易日 ===")
for o in data["observations"][:10]:
    print(f"  {o['date']}  →  {o['value']}")
