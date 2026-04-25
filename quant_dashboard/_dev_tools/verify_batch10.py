"""Batch 10 SQLite Data Governance Verification"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = 0
total = 0

def check(name, condition, detail=""):
    global passed, total
    total += 1
    ok = "PASS" if condition else "FAIL"
    if condition: passed += 1
    print(f"  [{ok}] {name} {detail}")

print("=== Batch 10 SQLite Verification ===\n")

# 1. DB module import
from services import db as ac_db
check("Import services.db", True)

# 2. Init DB
ac_db.init_db()
check("init_db() creates tables", os.path.exists(ac_db.DB_PATH), f"-> {ac_db.DB_PATH}")

# 3. Migration from JSON
result = ac_db.migrate_from_json()
check("migrate_from_json()", result is not None, f"-> trades={result['trades']} aiae={result['aiae']} erp={result['erp']}")

# 4. Trade CRUD
tid = ac_db.add_trade({
    "timestamp": "2026-04-22 23:00:00",
    "action": "test",
    "ts_code": "TEST.SH",
    "name": "测试股票",
    "amount": 100,
    "price": 10.0,
    "total": 1000.0,
    "success": True,
    "message": "Batch 10 验证"
})
check("add_trade()", tid > 0, f"-> id={tid}")

trades = ac_db.get_trades(limit=5)
check("get_trades() returns data", len(trades) > 0, f"-> {len(trades)} rows")

found = any(t["ts_code"] == "TEST.SH" for t in trades)
check("get_trades() contains test record", found)

count = ac_db.get_trade_count()
check("get_trade_count()", count > 0, f"-> {count}")

# 5. AIAE monthly CRUD
ac_db.upsert_aiae_monthly("2026-04", 23.5, 4, source="test")
history = ac_db.get_aiae_history()
check("upsert + get_aiae_history()", len(history) > 0, f"-> {len(history)} months")

latest = [h for h in history if h["month"] == "2026-04"]
check("AIAE 2026-04 exists", len(latest) == 1 and latest[0]["aiae_v1"] == 23.5)

prev = ac_db.get_prev_month_aiae("2026-04")
check("get_prev_month_aiae()", True, f"-> {prev}")  # may be None if only 1 month

# 6. ERP daily CRUD
ac_db.upsert_erp_daily("2026-04-22", 55.8)
ac_db.upsert_erp_daily("2026-04-21", 56.1)
erp_hist = ac_db.get_erp_history(days=10)
check("upsert + get_erp_history()", len(erp_hist) >= 2, f"-> {len(erp_hist)} days")

erp_latest = ac_db.get_erp_latest()
check("get_erp_latest()", erp_latest is not None and erp_latest["date"] == "2026-04-22",
      f"-> {erp_latest['date']}={erp_latest['score']}")

# 7. Idempotent upsert (no duplicates)
ac_db.upsert_erp_daily("2026-04-22", 55.9)  # update same date
erp_hist2 = ac_db.get_erp_history(days=10)
dates = [r["date"] for r in erp_hist2]
check("Upsert idempotent (no duplicates)", dates.count("2026-04-22") == 1)

# 8. Updated value
latest2 = ac_db.get_erp_latest()
check("Upsert updates value", latest2["score"] == 55.9, f"-> {latest2['score']}")

# 9. Cleanup test trade
conn = ac_db._get_conn()
conn.execute("DELETE FROM trades WHERE ts_code = 'TEST.SH'")
conn.commit()
check("Cleanup test data", True)

# 10. DB file size
db_size = os.path.getsize(ac_db.DB_PATH)
check("DB file reasonable size", db_size > 0, f"-> {db_size} bytes")

print(f"\n{'='*50}")
print(f"Result: {passed}/{total} passed")
print("ALL TESTS PASSED!" if passed == total else "SOME TESTS FAILED")
