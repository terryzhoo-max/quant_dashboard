"""
AlphaCore SQLite 持久化层 — Batch 10 数据治理
==============================================
统一管理 3 张表:
  - trades:        交易记录 (从 trade_history.json 迁移)
  - aiae_monthly:  AIAE 月度历史 (从 aiae_monthly_history.json 迁移)
  - erp_daily:     ERP 日度历史 (从 erp_daily_history.json 迁移)

设计原则:
  - 线程安全 (check_same_thread=False + 连接池)
  - 零风险迁移 (双写 JSON + SQLite)
  - 启动自动迁移旧 JSON 数据
"""

# ── 连接 & 基础设施 ──
from .connection import (
    _get_conn,
    _close_all_conns,
    init_db,
    migrate_from_json,
    migrate_decision_log_v2,
    logger,
    DB_DIR,
    DB_PATH,
)

# ── 交易记录 ──
from .trades import (
    add_trade,
    get_trades,
    get_trade_count,
)

# ── 信号历史 (AIAE / ERP / 组合快照) ──
from .signal_history import (
    upsert_aiae_monthly,
    get_aiae_history,
    get_prev_month_aiae,
    upsert_erp_daily,
    get_erp_history,
    get_erp_latest,
    save_portfolio_snapshot,
    get_portfolio_snapshots,
    get_portfolio_snapshot_count,
)

# ── 决策日志 ──
from .decision import (
    upsert_decision_log,
    get_decision_history,
    cleanup_old_decisions,
    backfill_accuracy,
    get_accuracy_stats,
    get_accuracy_by_jcs_level,
    get_accuracy_by_regime,
    get_accuracy_rolling,
    get_shadow_comparison,
    get_calendar_data,
)

# ── 预警 & 审计 ──
from .alerts import (
    _ensure_daily_reports_table,
    save_daily_report,
    get_daily_report,
    save_alert,
    get_recent_alerts,
    acknowledge_alert,
    get_last_alert_time,
    get_unread_alert_count,
    ack_all_alerts,
    save_audit_log,
    get_audit_history,
)

# ── 执行指令 (OMS) ──
from .execution import (
    create_execution_order,
    update_execution_fill,
    get_execution_orders,
    get_execution_order_by_id,
    find_pending_order,
    get_today_decision_snapshot,
    upsert_slippage_daily,
    get_slippage_history,
    get_slippage_stats,
    get_execution_order_count,
)

# ── CI/CD 管道 ──
from .ci import (
    save_ci_run,
    get_ci_history,
    get_ci_latest,
    update_ci_status,
)

# ── NLP 情报 ──
from .news import (
    save_news_event,
    get_news_events,
)

__all__ = [
    # connection
    "_get_conn", "_close_all_conns", "init_db", "migrate_from_json",
    "migrate_decision_log_v2", "logger", "DB_DIR", "DB_PATH",
    # trades
    "add_trade", "get_trades", "get_trade_count",
    # signal_history
    "upsert_aiae_monthly", "get_aiae_history", "get_prev_month_aiae",
    "upsert_erp_daily", "get_erp_history", "get_erp_latest",
    "save_portfolio_snapshot", "get_portfolio_snapshots", "get_portfolio_snapshot_count",
    # decision
    "upsert_decision_log", "get_decision_history", "cleanup_old_decisions",
    "backfill_accuracy", "get_accuracy_stats", "get_accuracy_by_jcs_level",
    "get_accuracy_by_regime", "get_accuracy_rolling", "get_shadow_comparison",
    "get_calendar_data",
    # alerts
    "_ensure_daily_reports_table", "save_daily_report", "get_daily_report",
    "save_alert", "get_recent_alerts", "acknowledge_alert",
    "get_last_alert_time", "get_unread_alert_count", "ack_all_alerts",
    "save_audit_log", "get_audit_history",
    # execution
    "create_execution_order", "update_execution_fill", "get_execution_orders",
    "get_execution_order_by_id", "find_pending_order", "get_today_decision_snapshot",
    "upsert_slippage_daily", "get_slippage_history", "get_slippage_stats",
    "get_execution_order_count",
    # ci
    "save_ci_run", "get_ci_history", "get_ci_latest", "update_ci_status",
    # news
    "save_news_event", "get_news_events",
]
