"""
AlphaCore SQLite 持久化层 — 连接管理 & DDL
==========================================
统一管理数据库连接、建表、迁移逻辑。
"""

import sqlite3
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from services.logger import get_logger

logger = get_logger("ac.db")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_lake")
DB_PATH = os.path.join(DB_DIR, "alphacore.db")

_local = threading.local()
_all_conns = []  # P0-1: 全局追踪所有线程本地连接, 用于 shutdown 时安全关闭
_conn_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """线程本地连接 (每线程独立, 避免 SQLite 跨线程锁)"""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(DB_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
        with _conn_lock:
            _all_conns.append(conn)
    return _local.conn


def _close_all_conns():
    """P0-1: atexit 钩子 — 安全关闭所有 SQLite 连接, 防止 WAL/SHM 泄漏"""
    with _conn_lock:
        for c in _all_conns:
            try:
                c.close()
            except Exception:
                pass
        _all_conns.clear()
    # 注: 不在 atexit 中 log, 因为解释器退出时 logging handlers 可能已清理


import atexit
atexit.register(_close_all_conns)


def init_db():
    """建表 (幂等, 启动时调用)"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            amount INTEGER,
            price REAL,
            total REAL,
            success BOOLEAN,
            message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_trades_code ON trades(ts_code);

        CREATE TABLE IF NOT EXISTS aiae_monthly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL UNIQUE,
            aiae_v1 REAL,
            regime INTEGER,
            recorded_at TEXT,
            updated_at TEXT,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS erp_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            score REAL,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            total_asset REAL,
            cash REAL,
            market_value REAL,
            total_pnl REAL,
            position_count INTEGER,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS decision_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            aiae_regime INTEGER,
            aiae_v1 REAL,
            erp_score REAL,
            erp_val REAL,
            vix_val REAL,
            mr_regime TEXT,
            hub_composite REAL,
            jcs_score REAL,
            jcs_level TEXT,
            suggested_position REAL,
            conflict_count INTEGER,
            degraded_modules TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS signal_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT,
            value REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            acknowledged INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_alert_rule_time ON signal_alerts(rule_id, created_at);

        -- V22.0: 审计历史持久化
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_time TEXT NOT NULL,
            trust_score REAL NOT NULL,
            trust_grade TEXT NOT NULL,
            total_checks INTEGER,
            pass_count INTEGER,
            warn_count INTEGER,
            fail_count INTEGER,
            elapsed_seconds REAL,
            data_quality_score REAL,
            strategy_health_score REAL,
            risk_control_score REAL,
            factor_decay_score REAL,
            system_status_score REAL,
            summary_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(audit_time);

        -- V26.0: OMS 执行指令表 (滑点归因追踪)
        CREATE TABLE IF NOT EXISTS execution_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL UNIQUE,
            order_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            side TEXT NOT NULL,
            -- 决策层快照
            decision_time TEXT,
            decision_price REAL,
            decision_regime INTEGER,
            decision_jcs REAL,
            target_amount INTEGER,
            target_position_pct REAL,
            -- 执行层
            arrival_price REAL,
            arrival_time TEXT,
            exec_price REAL,
            exec_amount INTEGER,
            exec_time TEXT,
            exec_source TEXT DEFAULT 'manual',
            -- 两层归因 (精确层 + 估算层)
            total_slippage_bps REAL,
            total_slippage_cny REAL,
            overnight_gap_bps REAL,
            intraday_drift_bps REAL,
            benchmark_close REAL,
            -- 多日建仓 parent/child
            parent_order_id TEXT,
            fill_seq INTEGER DEFAULT 1,
            -- 交易成本
            commission REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            -- 港股 FX
            currency TEXT DEFAULT 'CNY',
            fx_rate REAL DEFAULT 1.0,
            fx_slippage_bps REAL DEFAULT 0,
            -- 状态
            status TEXT DEFAULT 'pending',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_exec_order_date ON execution_orders(order_date);
        CREATE INDEX IF NOT EXISTS idx_exec_order_code ON execution_orders(ts_code);
        CREATE INDEX IF NOT EXISTS idx_exec_order_parent ON execution_orders(parent_order_id);

        -- V26.0: 滑点日度汇总表
        CREATE TABLE IF NOT EXISTS slippage_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            order_count INTEGER DEFAULT 0,
            total_turnover REAL DEFAULT 0,
            avg_slippage_bps REAL DEFAULT 0,
            total_slippage_cny REAL DEFAULT 0,
            overnight_gap_pct REAL DEFAULT 0,
            intraday_drift_pct REAL DEFAULT 0,
            worst_order_id TEXT,
            worst_slippage_bps REAL,
            eqs_score REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_slippage_date ON slippage_daily(date);

        -- P1-3: 策略 CI/CD 管道运行记录
        CREATE TABLE IF NOT EXISTS ci_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            strategy TEXT NOT NULL,
            regime TEXT,
            status TEXT NOT NULL,
            old_params TEXT,
            new_params TEXT,
            old_metrics TEXT,
            new_metrics TEXT,
            quality_gate TEXT,
            diff_summary TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_ci_strategy ON ci_runs(strategy);
        CREATE INDEX IF NOT EXISTS idx_ci_status ON ci_runs(status);

        -- P2-C: NLP 情报层事件表
        CREATE TABLE IF NOT EXISTS news_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            impact_score REAL DEFAULT 0,
            summary TEXT,
            affected_assets TEXT,
            scenario_id TEXT,
            source TEXT,
            raw_text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_news_category ON news_events(category);
        CREATE INDEX IF NOT EXISTS idx_news_created ON news_events(created_at);
    """)
    conn.commit()
    logger.info("SQLite 数据库初始化完成 · %s", DB_PATH)


# ══════════════════════════════════════════════════════════
#  JSON → SQLite 迁移 (启动时一次性调用)
# ══════════════════════════════════════════════════════════

def migrate_from_json() -> dict:
    """从旧 JSON 文件导入数据到 SQLite (幂等, 重复数据跳过)"""
    # 延迟导入避免循环依赖
    from .trades import add_trade, get_trade_count
    from .signal_history import upsert_aiae_monthly, upsert_erp_daily

    result = {"trades": 0, "aiae": 0, "erp": 0, "errors": []}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. 交易历史 (优先 data_lake, 降级旧路径)
    trade_file = os.path.join(root, "data_lake", "trade_history.json")
    if not os.path.exists(trade_file):
        trade_file = os.path.join(root, "trade_history.json")
    if os.path.exists(trade_file):
        try:
            with open(trade_file, "r", encoding="utf-8") as f:
                trades = json.load(f)
            existing_count = get_trade_count()
            if existing_count == 0 and trades:
                conn = _get_conn()
                for t in trades:
                    conn.execute(
                        """INSERT INTO trades (timestamp, action, ts_code, name, amount, price, total, success, message)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (t.get("timestamp"), t.get("action"), t.get("ts_code"),
                         t.get("name"), t.get("amount", 0), t.get("price", 0),
                         t.get("total", 0), t.get("success", True), t.get("message", "")),
                    )
                conn.commit()
                result["trades"] = len(trades)
                logger.info("迁移 trade_history.json → SQLite: %d 条", len(trades))
            elif existing_count > 0:
                logger.info("trades 表已有 %d 条记录, 跳过迁移", existing_count)
        except Exception as e:
            result["errors"].append(f"trade_history: {e}")
            logger.warning("迁移 trade_history 失败: %s", e)

    # 2. AIAE 月度历史
    aiae_file = os.path.join(root, "data_lake", "aiae_monthly_history.json")
    if os.path.exists(aiae_file):
        try:
            with open(aiae_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            for r in records:
                upsert_aiae_monthly(
                    month=r["month"],
                    aiae_v1=r.get("aiae_v1", 0),
                    regime=r.get("regime", 3),
                    recorded_at=r.get("recorded_at"),
                    source=r.get("source"),
                )
            result["aiae"] = len(records)
            logger.info("迁移 aiae_monthly_history.json → SQLite: %d 条", len(records))
        except Exception as e:
            result["errors"].append(f"aiae_monthly: {e}")
            logger.warning("迁移 aiae_monthly 失败: %s", e)

    # 3. ERP 日度历史
    erp_file = os.path.join(root, "data_lake", "erp_daily_history.json")
    if os.path.exists(erp_file):
        try:
            with open(erp_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            history = data.get("score_history", [])
            for entry in history:
                upsert_erp_daily(
                    date=entry["date"],
                    score=entry["score"],
                )
            result["erp"] = len(history)
            logger.info("迁移 erp_daily_history.json → SQLite: %d 条", len(history))
        except Exception as e:
            result["errors"].append(f"erp_daily: {e}")
            logger.warning("迁移 erp_daily 失败: %s", e)

    return result


def migrate_decision_log_v2():
    """V16.0 Phase 2 + V25.3: 安全添加准确率追踪 + 影子模式字段 (幂等)"""
    conn = _get_conn()
    existing = [row[1] for row in conn.execute("PRAGMA table_info(decision_log)").fetchall()]
    added = []
    new_cols = [
        ("market_return_5d", "REAL"),
        ("signal_correct", "INTEGER"),
        # V25.3: 影子模式 + 多资产信号
        ("jcs_v4_score", "REAL"),
        ("jcs_v6_score", "REAL"),
        ("jcs_shadow_delta", "REAL"),
        ("gold_signal", "REAL"),
        ("bond_signal", "REAL"),
        # V26: Signal Conviction Model
        ("jcs_v26_score", "REAL"),
        ("delta_v26", "REAL"),
    ]
    for col, typ in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE decision_log ADD COLUMN {col} {typ}")
            added.append(col)
    if added:
        conn.commit()
        logger.info("decision_log 迁移完成: 新增列 %s", added)
