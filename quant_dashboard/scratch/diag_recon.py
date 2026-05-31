"""Quick diagnostic: check SQLite DB tables and reconciliation data sources."""
import sqlite3
import os
import json
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DB_PATH = 'alpha_core.db'

print("=" * 60)
print("  Reconciliation Data Pipeline Diagnostic")
print("=" * 60)

# 1. Check DB exists
if not os.path.exists(DB_PATH):
    print(f"\n[FATAL] {DB_PATH} NOT FOUND")
else:
    size = os.path.getsize(DB_PATH)
    print(f"\n[OK] {DB_PATH} exists ({size:,} bytes)")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # List all tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print(f"\nTables ({len(tables)}):")
    for t in tables:
        count = c.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]
        print(f"  {t}: {count} rows")
    
    # 2. Check decision_log (needed for reconciliation)
    if 'decision_log' in tables:
        print("\n--- decision_log ---")
        c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM decision_log")
        mn, mx, cnt = c.fetchone()
        print(f"  Range: {mn} to {mx} ({cnt} entries)")
        
        # Check if position data exists
        c.execute("""
            SELECT date, json_extract(data, '$.position.matrix_position') as suggested,
                   json_extract(data, '$.position.gap') as gap
            FROM decision_log
            WHERE json_extract(data, '$.position.matrix_position') IS NOT NULL
            ORDER BY date DESC LIMIT 5
        """)
        rows = c.fetchall()
        print(f"  Entries with matrix_position: {len(rows)}")
        for r in rows:
            print(f"    {r[0]}: suggested={r[1]}, gap={r[2]}")
    else:
        print("\n[MISSING] decision_log table NOT FOUND")
    
    # 3. Check portfolio_daily_snapshots
    if 'portfolio_daily_snapshots' in tables:
        print("\n--- portfolio_daily_snapshots ---")
        c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM portfolio_daily_snapshots")
        mn, mx, cnt = c.fetchone()
        print(f"  Range: {mn} to {mx} ({cnt} entries)")
        
        # Show schema
        c.execute("PRAGMA table_info(portfolio_daily_snapshots)")
        cols = [r[1] for r in c.fetchall()]
        print(f"  Columns: {cols}")
        
        # Show sample
        c.execute("SELECT * FROM portfolio_daily_snapshots ORDER BY date DESC LIMIT 3")
        for r in c.fetchall():
            print(f"    {r}")
    else:
        print("\n[MISSING] portfolio_daily_snapshots table NOT FOUND")
    
    # 4. Check portfolio_snapshots (alternative name)
    for alt_name in ['portfolio_snapshots', 'daily_snapshots', 'portfolio_nav']:
        if alt_name in tables:
            print(f"\n--- {alt_name} ---")
            c.execute(f"SELECT MIN(date), MAX(date), COUNT(*) FROM [{alt_name}]")
            mn, mx, cnt = c.fetchone()
            print(f"  Range: {mn} to {mx} ({cnt} entries)")
    
    # 5. Check trade_history
    if 'trade_history' in tables:
        print("\n--- trade_history ---")
        c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM trade_history")
        mn, mx, cnt = c.fetchone()
        print(f"  Range: {mn} to {mx} ({cnt} entries)")
        c.execute("SELECT action, COUNT(*) FROM trade_history GROUP BY action")
        for action, count in c.fetchall():
            print(f"    {action}: {count}")
    else:
        print("\n[MISSING] trade_history table NOT FOUND")
    
    # 6. Check market_daily (for regime accuracy)
    if 'market_daily' in tables:
        print("\n--- market_daily ---")
        c.execute("SELECT COUNT(*) FROM market_daily WHERE index_code = '000300.SH'")
        cnt = c.fetchone()[0]
        print(f"  CSI300 entries: {cnt}")
    else:
        print("\n[MISSING] market_daily table NOT FOUND")
    
    conn.close()

# 7. Check trade_history.json (file-based fallback)
th_path = 'trade_history.json'
if os.path.exists(th_path):
    with open(th_path, 'r', encoding='utf-8') as f:
        th = json.load(f)
    entries = th if isinstance(th, list) else th.get('trades', [])
    print(f"\n--- trade_history.json ---")
    print(f"  {len(entries)} entries")
    if entries:
        print(f"  Last: {entries[-1]}")

# 8. Check audit_enforcement_log.json
ael_path = 'audit_enforcement_log.json'
if os.path.exists(ael_path):
    with open(ael_path, 'r', encoding='utf-8') as f:
        ael = json.load(f)
    actions = ael if isinstance(ael, list) else ael.get('actions', [])
    print(f"\n--- audit_enforcement_log.json ---")
    print(f"  {len(actions)} entries")
    if actions and len(actions) > 0:
        print(f"  Last: {actions[-1]}")

print(f"\n{'=' * 60}")
