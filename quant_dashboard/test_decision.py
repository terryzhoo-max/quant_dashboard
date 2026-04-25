"""AlphaCore V16.0 Phase 2 — 本地验证脚本"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("  AlphaCore V16.0 Phase 2 - Local Verification")
print("=" * 60)

# 1. 语法检查
import py_compile
files = [
    "dashboard_modules/decision_engine.py",
    "routers/decision.py",
    "services/db.py",
    "services/warmup_pipeline.py",
    "main.py",
]
for f in files:
    py_compile.compile(f, doraise=True)
print(f"\n[1] Syntax check: ALL {len(files)} files PASSED")

# 2. 模块导入
from dashboard_modules.decision_engine import (
    compute_conflict_matrix, compute_jcs, simulate_scenario,
    SCENARIOS, compute_risk_matrix, backfill_signal_accuracy
)
print("[2] Import (Phase 2 functions): PASSED")

# 3. DB 迁移测试
from services import db as ac_db
ac_db.init_db()
ac_db.migrate_decision_log_v2()
import sqlite3
conn = sqlite3.connect(ac_db.DB_PATH)
cols = [row[1] for row in conn.execute("PRAGMA table_info(decision_log)").fetchall()]
assert "market_return_5d" in cols, f"Missing market_return_5d column, got: {cols}"
assert "signal_correct" in cols, f"Missing signal_correct column, got: {cols}"
print(f"[3] DB migration v2: PASSED  ({len(cols)} columns)")
conn.close()

# 4. 准确率回填测试
test_data = {
    "date": "2098-12-01", "aiae_regime": 3, "aiae_v1": 22.0,
    "erp_score": 60.0, "erp_val": 4.5, "vix_val": 20.0,
    "mr_regime": "BULL", "hub_composite": 52.0, "jcs_score": 75.0,
    "jcs_level": "high", "suggested_position": 65.0,
    "conflict_count": 0, "degraded_modules": "",
}
ac_db.upsert_decision_log(test_data)
ac_db.backfill_accuracy("2098-12-01", 0.025)
conn2 = sqlite3.connect(ac_db.DB_PATH)
conn2.row_factory = sqlite3.Row
row = conn2.execute("SELECT * FROM decision_log WHERE date = '2098-12-01'").fetchone()
assert row is not None, "Test record should exist"
assert row["market_return_5d"] == 0.025, f"Expected 0.025, got {row['market_return_5d']}"
assert row["signal_correct"] == 1, f"Expected correct=1 (pos=65, return>0), got {row['signal_correct']}"
print(f"[4] Accuracy backfill: PASSED  return_5d={row['market_return_5d']} correct={row['signal_correct']}")

# 5. 反向准确率测试 (信号错误)
test_data2 = {**test_data, "date": "2098-12-02", "suggested_position": 30.0}
ac_db.upsert_decision_log(test_data2)
ac_db.backfill_accuracy("2098-12-02", 0.01)  # pos<45, but return>0 -> wrong
row2 = conn2.execute("SELECT signal_correct FROM decision_log WHERE date = '2098-12-02'").fetchone()
assert row2["signal_correct"] == 0, f"Expected wrong=0, got {row2['signal_correct']}"
print(f"[5] Accuracy (wrong signal): PASSED  correct={row2['signal_correct']}")

# 6. 准确率统计
stats = ac_db.get_accuracy_stats()
assert stats["total_decisions"] >= 2, f"Expected >= 2 decisions, got {stats['total_decisions']}"
print(f"[6] Accuracy stats: PASSED  total={stats['total_decisions']} accuracy={stats['accuracy_pct']}%")

# 7. 日历查询
cal = ac_db.get_calendar_data(2098, 12)
assert len(cal) >= 2, f"Expected >= 2 calendar entries, got {len(cal)}"
print(f"[7] Calendar query: PASSED  entries={len(cal)}")

# 8. 风险矩阵 (空缓存也不应崩溃)
risk = compute_risk_matrix()
assert "tail_risk" in risk, "Missing tail_risk in risk matrix"
assert "overlap_matrix" in risk, "Missing overlap_matrix"
assert "sector_concentration" in risk, "Missing sector_concentration"
assert risk["tail_risk"]["score"] >= 0, "Tail risk should be non-negative"
print(f"[8] Risk matrix: PASSED  tail_risk={risk['tail_risk']['score']} level={risk['tail_risk']['level']}")

# 9. Router 路由验证
from routers.decision import router
route_paths = [r.path for r in router.routes]
route_str = str(route_paths)
for ep in ["hub", "simulate", "history", "scenarios", "risk-matrix", "accuracy", "calendar"]:
    assert ep in route_str, f"Missing route: {ep}"
print(f"[9] Router (7 endpoints): PASSED  {route_paths}")

# 10. 清理测试数据
conn2.execute("DELETE FROM decision_log WHERE date LIKE '2098-%'")
conn2.commit()
conn2.close()
remaining = ac_db.get_decision_history(365)
test_remaining = [r for r in remaining if r.get("date", "").startswith("2098")]
assert len(test_remaining) == 0, "Test data should be cleaned up"
print("[10] Cleanup: PASSED")

# 11. Phase 1 回归 (确保 P1 功能不受影响)
snap = {"aiae_regime": 2, "erp_score": 75, "vix_val": 16, "vix_score": 73.1,
        "mr_regime": "BULL", "suggested_position": 55, "liquidity_score": 50, "macro_temp_score": 50}
jcs = compute_jcs(snap)
assert jcs["score"] > 50, "JCS should be > 50 for aligned signals"
sim = simulate_scenario("vix_spike_40", snap)
assert "error" not in sim, "VIX spike should work"
conflicts = compute_conflict_matrix(snap)
assert conflicts["conflict_count"] == 0, "Aligned signals should have 0 conflicts"
print(f"[11] Phase 1 regression: PASSED  jcs={jcs['score']} sim_ok=True conflicts=0")

print("\n" + "=" * 60)
print("  ALL 11 TESTS PASSED — Phase 2 Ready")
print("=" * 60)
