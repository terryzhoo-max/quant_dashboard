"""Check the REAL database at data_lake/alphacore.db"""
import sqlite3
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DB_PATH = os.path.join("data_lake", "alphacore.db")

print("=" * 60)
print(f"  Checking: {DB_PATH}")
print("=" * 60)

if not os.path.exists(DB_PATH):
    print(f"[FATAL] {DB_PATH} NOT FOUND")
    sys.exit(1)

size = os.path.getsize(DB_PATH)
print(f"\n[OK] exists ({size:,} bytes = {size/1024:.1f} KB)")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"\nTables ({len(tables)}):")
for t in tables:
    count = c.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]
    print(f"  {t}: {count} rows")

# decision_log details
if 'decision_log' in tables:
    print(f"\n--- decision_log ---")
    c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM decision_log")
    mn, mx, cnt = c.fetchone()
    print(f"  Range: {mn} to {mx} ({cnt} entries)")
    
    c.execute("SELECT date, aiae_regime, suggested_position, jcs_score FROM decision_log ORDER BY date DESC LIMIT 5")
    for r in c.fetchall():
        print(f"    {r[0]}: R{r[1]}, pos={r[2]}, JCS={r[3]}")
    
    # Check market_return_5d population
    c.execute("SELECT COUNT(*) FROM decision_log WHERE market_return_5d IS NOT NULL")
    ret_count = c.fetchone()[0]
    print(f"  Entries with market_return_5d: {ret_count}/{cnt}")

# portfolio_snapshots
if 'portfolio_snapshots' in tables:
    print(f"\n--- portfolio_snapshots ---")
    c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM portfolio_snapshots")
    mn, mx, cnt = c.fetchone()
    print(f"  Range: {mn} to {mx} ({cnt} entries)")
    c.execute("SELECT date, total_asset, market_value, position_count FROM portfolio_snapshots ORDER BY date DESC LIMIT 5")
    for r in c.fetchall():
        pct = round(r[2]/r[1]*100, 1) if r[1] > 0 else 0
        print(f"    {r[0]}: asset={r[1]:,.0f} mv={r[2]:,.0f} pos={pct}% #{r[3]}")

# trades
if 'trades' in tables:
    print(f"\n--- trades ---")
    c.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM trades")
    mn, mx, cnt = c.fetchone()
    print(f"  Range: {mn} to {mx} ({cnt} entries)")
    c.execute("SELECT action, COUNT(*) FROM trades GROUP BY action ORDER BY COUNT(*) DESC")
    for action, count in c.fetchall():
        print(f"    {action}: {count}")

conn.close()
print(f"\n{'=' * 60}")
