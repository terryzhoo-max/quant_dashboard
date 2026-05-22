"""V3.1 Live Smoke Test — 真实数据完整链路"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.momentum_rotation_engine import run_momentum_strategy

print("=" * 70)
print("  V3.1 LIVE SMOKE TEST")
print("=" * 70)

result = run_momentum_strategy()

status = result.get("status")
print("\n[STATUS] %s" % status)

if status != "success":
    print("[FAIL] Strategy returned non-success: %s" % json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(1)

data = result.get("data", {})
overview = data.get("market_overview", {})
buy_signals = data.get("buy_signals", [])
sell_signals = data.get("sell_signals", [])
signals = data.get("signals", [])
errors = data.get("errors", [])

print("\n" + "=" * 70)
print("  MARKET OVERVIEW")
print("=" * 70)
for k in ["regime", "regime_label", "regime_strategy", "position_cap",
           "layer1_trend", "layer2_vix", "layer3_crash",
           "rebalance_days", "rebalance_note",
           "stop_loss_count", "cum_stop_threshold", "tracked_holdings",
           "buy_count", "sell_count", "total_suggested_pos",
           "total_etfs", "pool_offense", "pool_defense", "xv_warnings"]:
    print("  %-25s: %s" % (k, overview.get(k, "MISSING")))

fw = overview.get("factor_weights", {})
print("  factor_weights:          %s" % fw)
has_trend = "TREND" in fw
print("  [%s] TREND in factor_weights" % ("PASS" if has_trend else "FAIL"))

print("\n" + "=" * 70)
print("  BUY SIGNALS (%d)" % len(buy_signals))
print("=" * 70)
for s in buy_signals:
    stop_msg = s.get("stop_loss_message", "")
    pnl = s.get("cum_pnl", "N/A")
    print("  %-6s %-16s score=%3s  pos=%5s%%  pnl=%s%%  %s" % (
        s.get("code"), s.get("name"), s.get("momentum_score"),
        s.get("suggested_position"), pnl, stop_msg))
    # Check 7-dim breakdown
    bd = s.get("score_breakdown", {})
    if "trend" not in bd:
        print("    [WARN] Missing 'trend' in score_breakdown")

print("\n  SELL/STOP signals: %d" % len(sell_signals))
for s in sell_signals[:5]:
    sig_type = s.get("signal", "?")
    msg = s.get("stop_loss_message", "")
    print("  %-6s %-16s signal=%s  %s" % (s.get("code"), s.get("name"), sig_type, msg))

if errors:
    print("\n  ERRORS: %d" % len(errors))
    for e in errors[:5]:
        print("    %s: %s" % (e.get("code"), e.get("error")))

# V3.1 field completeness check
print("\n" + "=" * 70)
print("  V3.1 FIELD COMPLETENESS CHECK")
print("=" * 70)
checks = [
    ("rebalance_days in overview", "rebalance_days" in overview),
    ("rebalance_note in overview", "rebalance_note" in overview),
    ("TREND in factor_weights", "TREND" in overview.get("factor_weights", {})),
    ("stop_loss_count in overview", "stop_loss_count" in overview),
    ("cum_stop_threshold in overview", "cum_stop_threshold" in overview),
    ("tracked_holdings in overview", "tracked_holdings" in overview),
]
if signals:
    s0 = signals[0]
    checks.extend([
        ("cum_pnl in signals", "cum_pnl" in s0),
        ("cum_stop_threshold in signals", "cum_stop_threshold" in s0),
        ("stop_loss_message in signals", "stop_loss_message" in s0),
        ("trend in score_breakdown", "trend" in s0.get("score_breakdown", {})),
    ])

passed = 0
for name, ok in checks:
    status = "PASS" if ok else "FAIL"
    print("  [%s] %s" % (status, name))
    if ok: passed += 1

print("\n  RESULT: %d/%d passed" % (passed, len(checks)))
print("=" * 70)
