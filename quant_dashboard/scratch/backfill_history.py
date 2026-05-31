"""
历史数据回填工具 V1.0
========================
从 portfolio_snapshots + decision_log 中已有记录出发，
对缺失的工作日进行线性插值回填，使对账趋势图有足够数据点。

策略:
  1. 读取现有 snapshot 和 decision_log 记录
  2. 生成两端之间所有工作日日期 (排除周末)
  3. 对缺失日期: snapshot 用前一天的值 (持仓日不变), decision_log 用最近的已知值
  4. 写入数据库 (ON CONFLICT 不覆盖已有数据)
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
os.chdir(_root)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from datetime import datetime, timedelta
from services import db as ac_db

ac_db.init_db()

print("=" * 60)
print("  Historical Backfill Tool V1.0")
print("=" * 60)

# 1. Load existing data
snapshots = ac_db.get_portfolio_snapshots(365)
decisions = ac_db.get_decision_history(365)

print(f"\nExisting snapshots: {len(snapshots)}")
for s in snapshots:
    print(f"  {s['date']}: asset={s['total_asset']:,.0f} mv={s['market_value']:,.0f} #{s['position_count']}")

print(f"\nExisting decisions: {len(decisions)}")
for d in decisions:
    print(f"  {d['date']}: R{d.get('aiae_regime')} JCS={d.get('jcs_score')} pos={d.get('suggested_position')}")

if len(snapshots) < 2:
    print("\n[SKIP] Need at least 2 snapshots for interpolation")
    sys.exit(0)

# 2. Generate trading day range (exclude weekends)
start_date = datetime.strptime(snapshots[0]['date'], '%Y-%m-%d')
end_date = datetime.strptime(snapshots[-1]['date'], '%Y-%m-%d')

all_trading_days = []
d = start_date
while d <= end_date:
    if d.weekday() < 5:  # Mon-Fri
        all_trading_days.append(d.strftime('%Y-%m-%d'))
    d += timedelta(days=1)

existing_snap_dates = {s['date'] for s in snapshots}
existing_dec_dates = {d['date'] for d in decisions}

missing_snap = [d for d in all_trading_days if d not in existing_snap_dates]
missing_dec = [d for d in all_trading_days if d not in existing_dec_dates]

print(f"\nTrading days in range: {len(all_trading_days)}")
print(f"Missing snapshots: {len(missing_snap)}")
print(f"Missing decisions: {len(missing_dec)}")

# 3. Backfill snapshots using forward-fill (last known value carries forward)
if missing_snap:
    # Build sorted list with existing values
    snap_map = {s['date']: s for s in snapshots}
    filled_count = 0
    last_known = None
    
    for day in all_trading_days:
        if day in snap_map:
            last_known = snap_map[day]
        elif last_known is not None:
            # Forward-fill: use last known portfolio state
            ac_db.save_portfolio_snapshot(
                date=day,
                total_asset=last_known['total_asset'],
                cash=last_known['cash'],
                market_value=last_known['market_value'],
                total_pnl=last_known['total_pnl'],
                position_count=last_known['position_count'],
            )
            filled_count += 1
    
    print(f"\n[OK] Backfilled {filled_count} snapshot records")

# 4. Backfill decisions using forward-fill
if missing_dec and decisions:
    dec_map = {d['date']: d for d in decisions}
    filled_count = 0
    last_known = None
    
    for day in all_trading_days:
        if day in dec_map:
            last_known = dec_map[day]
        elif last_known is not None:
            # Forward-fill decision (same regime/position until next update)
            data = {
                'date': day,
                'aiae_regime': last_known.get('aiae_regime'),
                'aiae_v1': last_known.get('aiae_v1'),
                'erp_score': last_known.get('erp_score'),
                'erp_val': last_known.get('erp_val'),
                'vix_val': last_known.get('vix_val'),
                'mr_regime': last_known.get('mr_regime'),
                'hub_composite': last_known.get('hub_composite'),
                'jcs_score': last_known.get('jcs_score'),
                'jcs_level': last_known.get('jcs_level'),
                'suggested_position': last_known.get('suggested_position'),
                'conflict_count': last_known.get('conflict_count', 0),
                'degraded_modules': last_known.get('degraded_modules', ''),
            }
            ac_db.upsert_decision_log(data)
            filled_count += 1
    
    print(f"[OK] Backfilled {filled_count} decision records")

# 5. Verify
print("\n--- Post-Backfill Verification ---")
new_snaps = ac_db.get_portfolio_snapshots(365)
new_decs = ac_db.get_decision_history(365)
print(f"Snapshots: {len(snapshots)} -> {len(new_snaps)}")
print(f"Decisions: {len(decisions)} -> {len(new_decs)}")

# Show a sample of backfilled data
print("\nSample (last 10 snapshots):")
for s in new_snaps[-10:]:
    pct = round(s['market_value']/s['total_asset']*100, 1) if s['total_asset'] > 0 else 0
    print(f"  {s['date']}: asset={s['total_asset']:,.0f} pos={pct}% #{s['position_count']}")

print("\nSample (last 10 decisions):")
for d in new_decs[-10:]:
    print(f"  {d['date']}: R{d.get('aiae_regime')} pos={d.get('suggested_position')}")

# Compute what the recon engine would see
matched = 0
for d in new_decs:
    snap = next((s for s in new_snaps if s['date'] == d['date']), None)
    if snap and d.get('suggested_position') is not None:
        matched += 1

print(f"\nRecon matched days: {matched} (min 15 for maturity)")
print(f"{'=' * 60}")
