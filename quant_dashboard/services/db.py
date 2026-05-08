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


def _get_conn() -> sqlite3.Connection:
    """线程本地连接 (每线程独立, 避免 SQLite 跨线程锁)"""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(DB_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


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
    """)
    conn.commit()
    logger.info("SQLite 数据库初始化完成 · %s", DB_PATH)


# ══════════════════════════════════════════════════════════
#  交易记录 CRUD
# ══════════════════════════════════════════════════════════

def add_trade(trade: dict) -> int:
    """插入一条交易记录, 返回 row id"""
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO trades (timestamp, action, ts_code, name, amount, price, total, success, message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            trade.get("action", "unknown"),
            trade.get("ts_code", ""),
            trade.get("name", ""),
            trade.get("amount", 0),
            trade.get("price", 0.0),
            trade.get("total", 0.0),
            trade.get("success", True),
            trade.get("message", ""),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_trades(limit: int = 30, ts_code: Optional[str] = None) -> List[Dict]:
    """查询交易记录 (最新在前)"""
    conn = _get_conn()
    if ts_code:
        rows = conn.execute(
            "SELECT * FROM trades WHERE ts_code = ? ORDER BY id DESC LIMIT ?",
            (ts_code, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_trade_count() -> int:
    """交易记录总数"""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]


# ══════════════════════════════════════════════════════════
#  AIAE 月度历史
# ══════════════════════════════════════════════════════════

def upsert_aiae_monthly(month: str, aiae_v1: float, regime: int,
                         recorded_at: Optional[str] = None,
                         source: Optional[str] = None):
    """插入或更新月度 AIAE 记录 (按 month UNIQUE 键)"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO aiae_monthly (month, aiae_v1, regime, recorded_at, updated_at, source)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(month) DO UPDATE SET
             aiae_v1 = excluded.aiae_v1,
             regime = excluded.regime,
             updated_at = ?,
             source = COALESCE(excluded.source, aiae_monthly.source)""",
        (month, aiae_v1, regime, recorded_at or now, now, source, now),
    )
    conn.commit()


def get_aiae_history() -> List[Dict]:
    """获取所有 AIAE 月度历史 (按月排序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM aiae_monthly ORDER BY month ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_prev_month_aiae(current_month: str) -> Optional[float]:
    """获取上个月的 AIAE 值 (排除当月)"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT aiae_v1 FROM aiae_monthly WHERE month < ? ORDER BY month DESC LIMIT 1",
        (current_month,),
    ).fetchone()
    return row["aiae_v1"] if row else None


# ══════════════════════════════════════════════════════════
#  ERP 日度历史
# ══════════════════════════════════════════════════════════

def upsert_erp_daily(date: str, score: float):
    """插入或更新 ERP 日度记录"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO erp_daily (date, score, recorded_at)
           VALUES (?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             score = excluded.score,
             recorded_at = excluded.recorded_at""",
        (date, score, now),
    )
    conn.commit()


def get_erp_history(days: int = 30) -> List[Dict]:
    """获取最近 N 天的 ERP 历史"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM erp_daily ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]  # 按日期正序


def get_erp_latest() -> Optional[Dict]:
    """获取最新一条 ERP 记录"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM erp_daily ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════
#  JSON → SQLite 迁移 (启动时一次性调用)
# ══════════════════════════════════════════════════════════

def migrate_from_json() -> dict:
    """从旧 JSON 文件导入数据到 SQLite (幂等, 重复数据跳过)"""
    result = {"trades": 0, "aiae": 0, "erp": 0, "errors": []}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. 交易历史
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


# ══════════════════════════════════════════════════════════
#  组合净值快照 (Batch 11: 每日收盘自动存档)
# ══════════════════════════════════════════════════════════

def save_portfolio_snapshot(date: str, total_asset: float, cash: float,
                            market_value: float, total_pnl: float,
                            position_count: int):
    """保存每日组合快照 (按 date UNIQUE 键, 幂等)"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO portfolio_snapshots (date, total_asset, cash, market_value, total_pnl, position_count, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             total_asset = excluded.total_asset,
             cash = excluded.cash,
             market_value = excluded.market_value,
             total_pnl = excluded.total_pnl,
             position_count = excluded.position_count,
             recorded_at = excluded.recorded_at""",
        (date, total_asset, cash, market_value, total_pnl, position_count, now),
    )
    conn.commit()


def get_portfolio_snapshots(days: int = 90) -> List[Dict]:
    """获取最近 N 天的组合快照 (按日期正序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_portfolio_snapshot_count() -> int:
    """快照总数"""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]


# ══════════════════════════════════════════════════════════
#  决策日志 (V16.0: 科学辅助决策模块)
# ══════════════════════════════════════════════════════════

def upsert_decision_log(data: dict):
    """插入或更新每日决策快照 (按 date UNIQUE 键, 幂等)"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO decision_log
           (date, aiae_regime, aiae_v1, erp_score, erp_val, vix_val, mr_regime,
            hub_composite, jcs_score, jcs_level, suggested_position,
            conflict_count, degraded_modules, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             aiae_regime = excluded.aiae_regime,
             aiae_v1 = excluded.aiae_v1,
             erp_score = excluded.erp_score,
             erp_val = excluded.erp_val,
             vix_val = excluded.vix_val,
             mr_regime = excluded.mr_regime,
             hub_composite = excluded.hub_composite,
             jcs_score = excluded.jcs_score,
             jcs_level = excluded.jcs_level,
             suggested_position = excluded.suggested_position,
             conflict_count = excluded.conflict_count,
             degraded_modules = excluded.degraded_modules,
             recorded_at = excluded.recorded_at""",
        (
            data.get("date"),
            data.get("aiae_regime"),
            data.get("aiae_v1"),
            data.get("erp_score"),
            data.get("erp_val"),
            data.get("vix_val"),
            data.get("mr_regime"),
            data.get("hub_composite"),
            data.get("jcs_score"),
            data.get("jcs_level"),
            data.get("suggested_position"),
            data.get("conflict_count", 0),
            data.get("degraded_modules", ""),
            now,
        ),
    )
    conn.commit()


def get_decision_history(days: int = 30) -> List[Dict]:
    """获取最近 N 天的决策日志 (按日期正序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM decision_log ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def cleanup_old_decisions(keep_days: int = 365):
    """清理超过 keep_days 的旧决策记录"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    deleted = conn.execute(
        "DELETE FROM decision_log WHERE date < ?", (cutoff,)
    ).rowcount
    conn.commit()
    if deleted > 0:
        logger.info("清理旧决策记录: 删除 %d 条 (保留 %d 天)", deleted, keep_days)


def migrate_decision_log_v2():
    """V16.0 Phase 2: 安全添加准确率追踪字段 (幂等)"""
    conn = _get_conn()
    existing = [row[1] for row in conn.execute("PRAGMA table_info(decision_log)").fetchall()]
    added = []
    for col, typ in [("market_return_5d", "REAL"), ("signal_correct", "INTEGER")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE decision_log ADD COLUMN {col} {typ}")
            added.append(col)
    if added:
        conn.commit()
        logger.info("decision_log 迁移完成: 新增列 %s", added)


def backfill_accuracy(date: str, market_return_5d: float):
    """回填 T+5 市场收益率并判断信号正确性"""
    conn = _get_conn()
    row = conn.execute("SELECT suggested_position FROM decision_log WHERE date = ?", (date,)).fetchone()
    if not row:
        return
    pos = row[0] or 55
    # 信号正确: 建议多(pos>=55) 且 市场涨 / 建议空(pos<45) 且 市场跌 / 中性不判断
    if pos >= 55:
        correct = 1 if market_return_5d > 0 else 0
    elif pos < 45:
        correct = 1 if market_return_5d < 0 else 0
    else:
        correct = -1  # 中性区不计入
    conn.execute(
        "UPDATE decision_log SET market_return_5d = ?, signal_correct = ? WHERE date = ?",
        (round(market_return_5d, 4), correct, date),
    )
    conn.commit()


def get_accuracy_stats() -> Dict:
    """计算信号准确率统计"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT signal_correct, COUNT(*) as cnt FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "GROUP BY signal_correct"
    ).fetchall()
    total, correct = 0, 0
    for r in rows:
        total += r[1]
        if r[0] == 1:
            correct = r[1]
    accuracy = round(correct / total * 100, 1) if total > 0 else None
    # 近10次准确率
    recent = conn.execute(
        "SELECT signal_correct FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "ORDER BY date DESC LIMIT 10"
    ).fetchall()
    recent_correct = sum(1 for r in recent if r[0] == 1)
    recent_total = len(recent)
    recent_accuracy = round(recent_correct / recent_total * 100, 1) if recent_total > 0 else None
    return {
        "total_decisions": total,
        "correct_decisions": correct,
        "accuracy_pct": accuracy,
        "recent_10_accuracy": recent_accuracy,
        "recent_10_total": recent_total,
        "has_data": total >= 5,
    }


def get_calendar_data(year: int = None, month: int = None) -> List[Dict]:
    """获取月历数据 (每日 JCS + 仓位 + 矛盾数)"""
    conn = _get_conn()
    if year and month:
        prefix = f"{year:04d}-{month:02d}"
        rows = conn.execute(
            "SELECT date, jcs_score, jcs_level, suggested_position, conflict_count, "
            "aiae_regime, market_return_5d, signal_correct "
            "FROM decision_log WHERE date LIKE ? ORDER BY date",
            (prefix + "%",)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT date, jcs_score, jcs_level, suggested_position, conflict_count, "
            "aiae_regime, market_return_5d, signal_correct "
            "FROM decision_log ORDER BY date DESC LIMIT 62"
        ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
#  V21.0: 日报缓存 (投委会报告持久化)
# ══════════════════════════════════════════════════════════

def _ensure_daily_reports_table():
    """幂等建表: daily_reports (V21.0 日报缓存)"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            markdown TEXT NOT NULL,
            summary_json TEXT,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(date)")
    conn.commit()


def save_daily_report(date: str, markdown: str, summary: dict = None):
    """保存日报 Markdown (按 date UNIQUE 键, 幂等)"""
    import json as _json
    _ensure_daily_reports_table()
    conn = _get_conn()
    now = datetime.now().isoformat()
    summary_str = _json.dumps(summary, ensure_ascii=False) if summary else None
    conn.execute(
        """INSERT INTO daily_reports (date, markdown, summary_json, generated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             markdown = excluded.markdown,
             summary_json = excluded.summary_json,
             generated_at = excluded.generated_at""",
        (date, markdown, summary_str, now),
    )
    conn.commit()


def get_daily_report(date: str) -> Optional[Dict]:
    """获取指定日期的日报"""
    _ensure_daily_reports_table()
    conn = _get_conn()
    row = conn.execute(
        "SELECT date, markdown, summary_json, generated_at FROM daily_reports WHERE date = ?",
        (date,),
    ).fetchone()
    return dict(row) if row else None


# ═══════════════════════════════════════════════════
#  V21.2: 信号预警持久化
# ═══════════════════════════════════════════════════

def save_alert(rule_id: str, severity: str, title: str, detail: str, value: float):
    """写入预警记录"""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO signal_alerts (rule_id, severity, title, detail, value, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rule_id, severity, title, detail, value, datetime.now().isoformat()),
    )
    conn.commit()


def get_recent_alerts(limit: int = 20) -> List[Dict]:
    """获取最近预警列表"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, rule_id, severity, title, detail, value, created_at, acknowledged "
        "FROM signal_alerts ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def acknowledge_alert(alert_id: int):
    """标记预警已读"""
    conn = _get_conn()
    conn.execute("UPDATE signal_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    conn.commit()


def get_last_alert_time(rule_id: str) -> Optional[str]:
    """获取某规则最近一次触发的时间 (用于 cooldown 判断)"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT created_at FROM signal_alerts WHERE rule_id = ? ORDER BY created_at DESC LIMIT 1",
        (rule_id,),
    ).fetchone()
    return row["created_at"] if row else None


def get_unread_alert_count() -> int:
    """未读预警数量 (铃铛 badge)"""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM signal_alerts WHERE acknowledged = 0").fetchone()
    return row["c"] if row else 0


# ══════════════════════════════════════════════════════════
#  V22.0: 审计日志持久化
# ══════════════════════════════════════════════════════════

def save_audit_log(report: dict):
    """持久化审计报告到 audit_log 表"""
    conn = _get_conn()
    modules = report.get("modules", {})
    dq = modules.get("data_quality", {}).get("score", 0)
    sh = modules.get("strategy_health", {}).get("score", 0)
    rc = modules.get("risk_control", {}).get("score", 0)
    fd = modules.get("factor_decay", {}).get("score", 0)
    ss = modules.get("system_status", {}).get("score", 0)

    conn.execute(
        """INSERT INTO audit_log
           (audit_time, trust_score, trust_grade, total_checks,
            pass_count, warn_count, fail_count, elapsed_seconds,
            data_quality_score, strategy_health_score, risk_control_score,
            factor_decay_score, system_status_score, summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report.get("audit_time", ""),
            report.get("trust_score", 0),
            report.get("trust_grade", "D"),
            report.get("total_checks", 0),
            report.get("pass_count", 0),
            report.get("warn_count", 0),
            report.get("fail_count", 0),
            report.get("elapsed_seconds", 0),
            dq, sh, rc, fd, ss,
            None,  # summary_json placeholder
        )
    )
    conn.commit()

    # 保留最近 90 天
    conn.execute("DELETE FROM audit_log WHERE created_at < datetime('now', '-90 days')")
    conn.commit()


def get_audit_history(limit: int = 10) -> list:
    """获取最近 N 次审计记录"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT audit_time, trust_score, trust_grade, fail_count, warn_count, "
        "pass_count, elapsed_seconds, total_checks "
        "FROM audit_log ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════
#  V26.0: OMS 滑点归因 — 执行指令 CRUD
# ══════════════════════════════════════════════════════════

def create_execution_order(order: dict) -> str:
    """创建执行指令, 返回 order_id (UUID)"""
    import uuid
    order_id = order.get("order_id") or str(uuid.uuid4())[:12]
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO execution_orders
           (order_id, order_date, ts_code, name, side,
            decision_time, decision_price, decision_regime, decision_jcs,
            target_amount, target_position_pct,
            arrival_price, arrival_time,
            exec_price, exec_amount, exec_time, exec_source,
            parent_order_id, fill_seq,
            commission, tax, currency, fx_rate,
            status, notes, created_at, updated_at)
           VALUES (?,?,?,?,?, ?,?,?,?, ?,?, ?,?, ?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?)
           ON CONFLICT(order_id) DO NOTHING""",
        (
            order_id,
            order.get("order_date", datetime.now().strftime("%Y-%m-%d")),
            order.get("ts_code", ""),
            order.get("name", ""),
            order.get("side", "buy"),
            order.get("decision_time"),
            order.get("decision_price"),
            order.get("decision_regime"),
            order.get("decision_jcs"),
            order.get("target_amount"),
            order.get("target_position_pct"),
            order.get("arrival_price"),
            order.get("arrival_time"),
            order.get("exec_price"),
            order.get("exec_amount"),
            order.get("exec_time"),
            order.get("exec_source", "manual"),
            order.get("parent_order_id"),
            order.get("fill_seq", 1),
            order.get("commission", 0),
            order.get("tax", 0),
            order.get("currency", "CNY"),
            order.get("fx_rate", 1.0),
            order.get("status", "pending"),
            order.get("notes"),
            now, now,
        ),
    )
    conn.commit()
    return order_id


def update_execution_fill(order_id: str, fill_data: dict):
    """更新执行指令的成交信息 + IS 归因结果"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    sets = ["updated_at = ?"]
    vals = [now]
    allowed = [
        "arrival_price", "arrival_time", "exec_price", "exec_amount",
        "exec_time", "exec_source", "status", "notes",
        "total_slippage_bps", "total_slippage_cny",
        "overnight_gap_bps", "intraday_drift_bps", "benchmark_close",
        "commission", "tax", "fx_rate", "fx_slippage_bps",
        "parent_order_id", "fill_seq",
    ]
    for key in allowed:
        if key in fill_data:
            sets.append(f"{key} = ?")
            vals.append(fill_data[key])
    vals.append(order_id)
    conn.execute(
        f"UPDATE execution_orders SET {', '.join(sets)} WHERE order_id = ?",
        vals,
    )
    conn.commit()


def get_execution_orders(days: int = 30, ts_code: Optional[str] = None,
                         status: Optional[str] = None) -> List[Dict]:
    """查询执行指令列表 (最新在前)"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = "SELECT * FROM execution_orders WHERE order_date >= ?"
    params: list = [cutoff]
    if ts_code:
        sql += " AND ts_code = ?"
        params.append(ts_code)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY order_date DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_execution_order_by_id(order_id: str) -> Optional[Dict]:
    """按 order_id 查询单条指令"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM execution_orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    return dict(row) if row else None


def find_pending_order(ts_code: str, side: str, window_days: int = 3) -> Optional[Dict]:
    """查找指定标的的 pending 指令 (时间窗口内, 用于自动匹配)"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT * FROM execution_orders
           WHERE ts_code = ? AND side = ? AND status = 'pending'
             AND order_date >= ?
           ORDER BY order_date DESC LIMIT 1""",
        (ts_code, side, cutoff),
    ).fetchone()
    return dict(row) if row else None


def get_today_decision_snapshot(date: str, ts_code: str = None) -> Optional[Dict]:
    """查询今日是否已有决策快照 (用于去重)"""
    conn = _get_conn()
    if ts_code:
        row = conn.execute(
            """SELECT * FROM execution_orders
               WHERE order_date = ? AND ts_code = ? AND status = 'pending'
               ORDER BY id DESC LIMIT 1""",
            (date, ts_code),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM execution_orders
               WHERE order_date = ? AND status = 'pending'
               ORDER BY id DESC LIMIT 1""",
            (date,),
        ).fetchone()
    return dict(row) if row else None


# ── 滑点日度汇总 ──

def upsert_slippage_daily(date: str, summary: dict):
    """写入/更新日度滑点汇总"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO slippage_daily
           (date, order_count, total_turnover, avg_slippage_bps,
            total_slippage_cny, overnight_gap_pct, intraday_drift_pct,
            worst_order_id, worst_slippage_bps, eqs_score, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
             order_count = excluded.order_count,
             total_turnover = excluded.total_turnover,
             avg_slippage_bps = excluded.avg_slippage_bps,
             total_slippage_cny = excluded.total_slippage_cny,
             overnight_gap_pct = excluded.overnight_gap_pct,
             intraday_drift_pct = excluded.intraday_drift_pct,
             worst_order_id = excluded.worst_order_id,
             worst_slippage_bps = excluded.worst_slippage_bps,
             eqs_score = excluded.eqs_score""",
        (
            date,
            summary.get("order_count", 0),
            summary.get("total_turnover", 0),
            summary.get("avg_slippage_bps", 0),
            summary.get("total_slippage_cny", 0),
            summary.get("overnight_gap_pct", 0),
            summary.get("intraday_drift_pct", 0),
            summary.get("worst_order_id"),
            summary.get("worst_slippage_bps"),
            summary.get("eqs_score"),
            now,
        ),
    )
    conn.commit()


def get_slippage_history(days: int = 30) -> List[Dict]:
    """获取滑点日度历史 (日期正序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM slippage_daily ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_slippage_stats() -> Dict:
    """滑点统计摘要 (供面板总览卡片)"""
    conn = _get_conn()
    # 近30日汇总
    cutoff_30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    r30 = conn.execute(
        """SELECT COUNT(*) as days, SUM(order_count) as orders,
              SUM(total_turnover) as turnover,
              SUM(total_slippage_cny) as total_cost,
              AVG(avg_slippage_bps) as avg_bps
           FROM slippage_daily WHERE date >= ?""",
        (cutoff_30,),
    ).fetchone()
    # 近7日汇总 (用于趋势)
    cutoff_7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    r7 = conn.execute(
        """SELECT AVG(avg_slippage_bps) as avg_bps_7d,
              AVG(eqs_score) as avg_eqs_7d
           FROM slippage_daily WHERE date >= ?""",
        (cutoff_7,),
    ).fetchone()
    # 历史总计
    total = conn.execute(
        "SELECT SUM(total_slippage_cny) as lifetime_cost, COUNT(*) as total_days "
        "FROM slippage_daily"
    ).fetchone()
    return {
        "period_30d": {
            "days": r30["days"] or 0,
            "orders": r30["orders"] or 0,
            "turnover": round(r30["turnover"] or 0, 2),
            "total_cost": round(r30["total_cost"] or 0, 2),
            "avg_bps": round(r30["avg_bps"] or 0, 2),
        },
        "period_7d": {
            "avg_bps": round(r7["avg_bps_7d"] or 0, 2),
            "avg_eqs": round(r7["avg_eqs_7d"] or 0, 1),
        },
        "lifetime": {
            "total_cost": round(total["lifetime_cost"] or 0, 2),
            "total_days": total["total_days"] or 0,
        },
    }


def get_execution_order_count() -> int:
    """执行指令总数"""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0]
