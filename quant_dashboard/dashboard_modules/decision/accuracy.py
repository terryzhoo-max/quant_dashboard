"""
AlphaCore · 准确率回填 (Signal Accuracy Backfill)
===================================================
从 decision_engine.py 拆分: T+5 真实市场收益回填逻辑

O1 Refactor: 独立子模块
"""

from datetime import datetime, timedelta
from typing import Optional
from services.logger import get_logger

logger = get_logger("ac.decision.accuracy")


def _get_index_close(trade_date: str, index_code: str = "000300.SH") -> Optional[float]:
    """
    从 Tushare 获取指定日期的指数收盘价。
    支持交易日回溯: 若当日非交易日则查前一交易日。
    返回 None 表示无法获取。
    """
    try:
        import tushare as ts
        pro = ts.pro_api()
        # trade_date 格式: YYYY-MM-DD → YYYYMMDD
        dt_str = trade_date.replace("-", "")
        dt = datetime.strptime(dt_str, "%Y%m%d")
        for offset in range(5):  # 最多回溯5天
            try:
                try_date = (dt - timedelta(days=offset)).strftime("%Y%m%d")
                df = pro.index_daily(ts_code=index_code, trade_date=try_date)
                if df is not None and not df.empty:
                    return float(df.iloc[0]["close"])
            except Exception:
                continue
    except Exception as e:
        logger.warning("获取指数收盘价失败 (%s, %s): %s", trade_date, index_code, e)
    return None


def _get_t5_trade_date(base_date: str) -> Optional[str]:
    """V25.2 A-3: 获取精确 T+5 交易日 (Tushare trade_cal, 降级为 T+7 自然日)"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        dt_str = base_date.replace("-", "")
        # 查询 base_date 后 10 个交易日的日历
        df = pro.trade_cal(
            exchange='SSE', start_date=dt_str,
            end_date=(datetime.strptime(dt_str, "%Y%m%d") + timedelta(days=15)).strftime("%Y%m%d"),
            fields='cal_date,is_open'
        )
        if df is not None and not df.empty:
            open_days = df[df['is_open'] == 1].sort_values('cal_date')
            # 跳过 T 日本身, 取第 5 个交易日
            future = open_days[open_days['cal_date'] > dt_str]
            if len(future) >= 5:
                t5 = future.iloc[4]['cal_date']  # 0-indexed, 第5个
                return f"{t5[:4]}-{t5[4:6]}-{t5[6:]}"
    except Exception as e:
        logger.debug("trade_cal 查询失败 (%s), 降级为 T+7: %s", base_date, e)
    # 降级: T+7 自然日
    dt = datetime.strptime(base_date, "%Y-%m-%d")
    return (dt + timedelta(days=7)).strftime("%Y-%m-%d")


def backfill_signal_accuracy(force_recalc: bool = False):
    """
    V25.2: 使用沪深300真实收盘价计算 T+5 收益率.
    
    Args:
        force_recalc: True 时强制重算已有 signal_correct 的记录 (A-7 一次性修复)
    """
    from services import db as ac_db

    today = datetime.now()
    conn = ac_db._get_conn()
    
    if force_recalc:
        # A-7: 重算所有已回填但使用旧逻辑的记录
        rows = conn.execute(
            "SELECT date, market_return_5d FROM decision_log "
            "WHERE market_return_5d IS NOT NULL "
            "ORDER BY date DESC LIMIT 30"
        ).fetchall()
        recalc_count = 0
        for row in rows:
            log_date, ret = row[0], row[1]
            if ret is not None:
                ac_db.backfill_accuracy(log_date, ret)
                recalc_count += 1
        if recalc_count > 0:
            logger.info("准确率重算完成 (force_recalc): %d 条", recalc_count)
    
    # 常规回填: 查找未回填的记录
    rows = conn.execute(
        "SELECT date FROM decision_log WHERE market_return_5d IS NULL "
        "AND date <= ? ORDER BY date DESC LIMIT 15",
        ((today - timedelta(days=5)).strftime("%Y-%m-%d"),)
    ).fetchall()

    if not rows:
        return

    filled_count = 0
    for row in rows:
        log_date = row[0]  # YYYY-MM-DD
        try:
            # 获取 T 日收盘价
            close_t = _get_index_close(log_date)
            if close_t is None:
                logger.debug("准确率回填跳过 %s: T日收盘价不可用", log_date)
                continue

            # V25.2: 使用 trade_cal 获取精确 T+5 交易日
            t5_date = _get_t5_trade_date(log_date)
            if t5_date is None:
                continue
            close_t5 = _get_index_close(t5_date)
            if close_t5 is None:
                logger.debug("准确率回填跳过 %s: T+5日(%s)收盘价不可用", log_date, t5_date)
                continue

            market_return = round((close_t5 - close_t) / close_t, 4)
            ac_db.backfill_accuracy(log_date, market_return)
            filled_count += 1
            logger.info("准确率回填: %s -> return_5d=%.4f (%.2f->%.2f, T+5=%s)",
                        log_date, market_return, close_t, close_t5, t5_date)
        except Exception as e:
            logger.warning("准确率回填异常 %s: %s", log_date, e)
            continue

    if filled_count > 0:
        logger.info("准确率回填完成: %d/%d 条", filled_count, len(rows))
