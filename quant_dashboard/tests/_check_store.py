import json, os

path = "portfolio_store.json"
abs_path = os.path.abspath(path)
print(f"Path: {abs_path}")
print(f"Exists: {os.path.exists(path)}")
print(f"Size: {os.path.getsize(path)} bytes")
print(f"Modified: {os.path.getmtime(path)}")

with open(path, 'r', encoding='utf-8') as f:
    d = json.load(f)

print(f"Cash: {d.get('cash', 0):,.2f}")
print(f"Positions: {len(d.get('positions', {}))}")
print(f"Import date: {d.get('import_date', 'N/A')}")
print(f"Broker ref MV: {d.get('broker_ref_market_value', 'N/A')}")
print(f"Broker total PnL: {d.get('broker_total_pnl', 'N/A')}")

print("\n--- Top 5 positions ---")
for i, (k, v) in enumerate(d.get('positions', {}).items()):
    if i >= 5:
        break
    print(f"  {k}: {v.get('name', '?')} x{v.get('amount', 0)} @ cost={v.get('cost', 0):.3f} import={v.get('import_date', '?')}")
