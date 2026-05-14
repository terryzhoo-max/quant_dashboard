"""
AlphaCore · 决策引擎包 (P2-A 渐进式拆分 — 全部完成)
=====================================================
兼容层: 所有外部消费者继续使用
  from dashboard_modules.decision_engine import X
无需修改。

本 __init__.py 的作用:
  from dashboard_modules.decision import X
也能正常工作。

拆分完成:
  - [x] conflicts.py     信号矛盾检测 + 方向解析
  - [x] jcs.py           联合置信度引擎
  - [x] temperature.py   全球市场温度聚合
  - [x] snapshot.py      快照构建器
  - [x] action_plan.py   执行建议 + 警示
  - [x] scenarios.py     情景模拟 + 冲击传播
  - [x] position_path.py 仓位路径 + 执行成本
  - [x] events.py        事件监控引擎
"""

# ── 已拆分模块: 从子模块导出 ──
from dashboard_modules.decision.conflicts import (  # noqa: F401
    _signal_direction,
    _CONFLICT_RULES,
    compute_conflict_matrix,
)

from dashboard_modules.decision.jcs import (  # noqa: F401
    _JCS_WEIGHTS,
    _REGIME_CN_MAP,
    _REGIME_CAP_MAP,
    _recalc_vix_score,
    _recalc_hub_composite,
    compute_jcs,
)

from dashboard_modules.decision.temperature import (  # noqa: F401
    _GLOBAL_REGIMES,
    _GLOBAL_GAUGE_BANDS,
    _REGIME_CAP_LOOKUP,
    _build_global_temperature,
)

from dashboard_modules.decision.snapshot import (  # noqa: F401
    _parse_erp_value,
    _build_snapshot_from_cache,
)

from dashboard_modules.decision.action_plan import (  # noqa: F401
    _get_current_position,
    _apply_position_gap_note,
    generate_action_plan,
    generate_alerts,
)

from dashboard_modules.decision.scenarios import (  # noqa: F401
    SCENARIOS,
    _SHOCK_NODES,
    _SHOCK_EDGES,
    _SHOCK_SOURCES,
    _SNAPSHOT_DELTA_MAP,
    propagate_shock,
    apply_shock_to_snapshot,
    run_shock_simulation,
    simulate_scenario,
)

from dashboard_modules.decision.position_path import (  # noqa: F401
    _POSITION_RULES,
    generate_position_path,
    estimate_execution_cost,
    estimate_position_path_costs,
)

from dashboard_modules.decision.events import (  # noqa: F401
    detect_market_events,
    get_recent_events,
)

# ── 仍在原文件中的函数 (聚合函数, 依赖多个子模块) ──
# get_hub_data, get_hub_data_with_events, log_daily_decision
# compute_risk_matrix, compute_contagion_matrix
# backfill_signal_accuracy
from dashboard_modules.decision_engine import *  # noqa: F401,F403
