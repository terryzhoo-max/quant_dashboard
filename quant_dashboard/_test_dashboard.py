"""Quick test: Dashboard Overview endpoint — inspect full structure"""
import requests, time, json

t0 = time.time()
r = requests.get("http://localhost:8888/api/v1/dashboard-data", timeout=300)
elapsed = time.time() - t0
d = r.json()

print(f"Status: {r.status_code} ({elapsed:.1f}s)")
print(f"Top keys: {list(d.keys())}")
print()

# Check if data is nested
data = d.get("data", d)
print(f"Data keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
print()

# Print full response (truncated)
formatted = json.dumps(d, indent=2, ensure_ascii=False, default=str)
print(formatted[:3000])
