"""One-time: manually trigger today's snapshot + decision log write."""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
os.chdir(_root)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from services import db as ac_db
from datetime import datetime

# Init DB tables
ac_db.init_db()

# 1. Portfolio snapshot
try:
    from portfolio_engine import get_portfolio_engine
    engine = get_portfolio_engine()
    val = engine.get_valuation()
    if val.get("position_count", 0) > 0:
        today = datetime.now().strftime("%Y-%m-%d")
        ac_db.save_portfolio_snapshot(
            date=today,
            total_asset=val["total_asset"],
            cash=val["cash"],
            market_value=val["market_value"],
            total_pnl=val["total_pnl"],
            position_count=val["position_count"],
        )
        print(f"[OK] Portfolio snapshot saved: {today}")
        print(f"     Asset: {val['total_asset']:,.0f}")
        print(f"     MV:    {val['market_value']:,.0f}")
        print(f"     Pos:   {val['position_count']}")
    else:
        print("[SKIP] No positions found")
except Exception as e:
    print(f"[FAIL] Portfolio snapshot: {e}")

# 2. Decision log
try:
    from dashboard_modules.decision_engine import log_daily_decision
    log_daily_decision()
    print("[OK] Decision log saved")
except Exception as e:
    print(f"[SKIP] Decision log: {e}")

# 3. Verify
print("\n--- Verification ---")
snaps = ac_db.get_portfolio_snapshots(10)
print(f"Portfolio snapshots: {len(snaps)} entries")
for s in snaps[-3:]:
    pct = round(s['market_value']/s['total_asset']*100, 1) if s['total_asset'] > 0 else 0
    print(f"  {s['date']}: asset={s['total_asset']:,.0f} pos={pct}% #{s['position_count']}")

decisions = ac_db.get_decision_history(10)
print(f"Decision log: {len(decisions)} entries")
for d in decisions[-3:]:
    print(f"  {d['date']}: R{d.get('aiae_regime')} JCS={d.get('jcs_score')} pos={d.get('suggested_position')}")
