# -*- coding: utf-8 -*-
"""
AlphaCore 深度审计引擎 V5.0 — "带枪保安" 架构
五维审计: 数据质量 · 策略健康 · 风控合规 · 因子衰减 · 系统状态
+ Enforcer 执行器集成 + 静音/降级模式
V5.0: 消灭硬编码，所有阈值从 config.py AUDIT_CONFIG 读取
"""
import os
import json
import time
import glob
import re
import random
import traceback
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── 日志初始化 (带安全兜底) ──
try:
    from services.logger import get_logger
    logger = get_logger("ac.audit")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("ac.audit")

# ── 路径常量 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # engines/
PROJECT_ROOT = os.path.dirname(BASE_DIR)                    # quant_dashboard/
DATA_LAKE = os.path.join(PROJECT_ROOT, "data_lake")
DAILY_DIR = os.path.join(DATA_LAKE, "daily_prices")
FINA_DIR  = os.path.join(DATA_LAKE, "financials")

OPTIMIZATION_FILES = {
    "均值回归": "mr_optimization_results.json",
    "红利趋势": "dividend_optimization_results.json",
    "行业动量": "optimizer_results.json",
    "ERP择时": "erp_optimization_results.json",
}

WEIGHTS = {
    "data_quality": 0.35,
    "strategy_health": 0.25,
    "risk_control": 0.20,
    "factor_decay": 0.10,
    "system_status": 0.10,
}

# ── V5.0: 从 config.py 加载审计阈值 (消灭硬编码) ──
def _load_audit_cfg():
    try:
        from config import AUDIT_CONFIG
        return dict(AUDIT_CONFIG)
    except ImportError:
        return {
            "stop_loss_stock": -12.0, "stop_loss_etf": -8.0,
            "stop_loss_broad_etf": -6.0, "stop_loss_overseas_etf": -8.0,
            "single_position_limit": 20.0,
            "sector_limit": 40.0, "total_position_cap": 95.0,
            "min_holdings": 5, "daily_stale_warn_days": 3,
            "daily_stale_fail_days": 5, "fina_fresh_days": 90,
            "erp_stale_warn_days": 3, "erp_stale_fail_days": 7,
            "rates_stale_warn_days": 3, "rates_stale_fail_days": 7,
            "strategy_fresh_days": 30, "strategy_stale_days": 60,
        }

# V5.0: 模块加载时立即读取配置 (全局单例)
AUDIT_CFG = _load_audit_cfg()

# V6.5: Tushare 探测结果内存级缓存
_TS_CHECK_CACHE = None


def _today_str():
    return datetime.now().strftime("%Y%m%d")


# V6.6: 交易日历自维护 (替代硬编码假期列表)
# 优先从 data_lake/trading_calendar.json 加载 Tushare trade_cal 缓存
# 缓存未命中时降级到硬编码假期列表 (兜底)
_CN_HOLIDAYS_2026 = {
    (1,1),(1,2),(1,3),           # 元旦
    (1,26),(1,27),(1,28),(1,29),(1,30),(1,31),(2,1),  # 春节
    (4,4),(4,5),(4,6),           # 清明
    (5,1),(5,2),(5,3),(5,4),(5,5),  # 劳动节
    (5,31),(6,1),(6,2),          # 端午
    (9,25),(9,26),(9,27),        # 中秋
    (10,1),(10,2),(10,3),(10,4),(10,5),(10,6),(10,7),  # 国庆
}

_TRADING_CAL_CACHE = None

def _load_trading_calendar():
    """V6.6: 从 data_lake/trading_calendar.json 加载交易日集合。
    缓存格式: ["20260102", "20260103", ...] (仅开市日)
    由 data_manager.py 每日同步时写入。
    """
    global _TRADING_CAL_CACHE
    if _TRADING_CAL_CACHE is not None:
        return _TRADING_CAL_CACHE
    cal_path = os.path.join(DATA_LAKE, "trading_calendar.json")
    if os.path.exists(cal_path):
        try:
            with open(cal_path, "r", encoding="utf-8") as f:
                _TRADING_CAL_CACHE = set(json.load(f))
            return _TRADING_CAL_CACHE
        except Exception:
            pass
    return None  # 降级到硬编码

def _is_trading_day(dt):
    """V6.6: 交易日判定 — 优先用日历缓存, 降级到周末+假期过滤"""
    cal = _load_trading_calendar()
    if cal is not None:
        return dt.strftime("%Y%m%d") in cal
    # 降级: 周末 + 硬编码假期兜底
    if dt.weekday() >= 5:
        return False
    if (dt.month, dt.day) in _CN_HOLIDAYS_2026:
        return False
    return True


def _last_trading_day():
    """获取最近一个交易日 (今天15:00后算今天, 否则算昨天)"""
    now = datetime.now()
    target = now if now.hour >= 15 else now - timedelta(days=1)
    while not _is_trading_day(target):
        target -= timedelta(days=1)
    return target


def _stale_days(date_str):
    """计算距今交易日天数 (排除周末+法定假日, 避免周末误报)"""
    try:
        clean = str(date_str).replace("-", "")[:8]
        dt = datetime.strptime(clean, "%Y%m%d")
        # 计算自然日差
        cal_days = (datetime.now() - dt).days
        if cal_days <= 0:
            return 0
        # 快速路径: 1-2 自然日 → 计算精确交易日
        trading_days = 0
        cursor = dt + timedelta(days=1)
        end = datetime.now()
        # 限制循环上限防止极端值卡死
        max_iter = min(cal_days, 400)
        for _ in range(max_iter):
            if cursor > end:
                break
            if _is_trading_day(cursor):
                trading_days += 1
            cursor += timedelta(days=1)
        return trading_days
    except Exception:
        return 999


def _grade(score):
    if score >= 85:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 55:
        return "C"
    else:
        return "D"


# ═══════════════════════════════════════════════════════
#  模块 1: 数据质量审计
# ═══════════════════════════════════════════════════════
def audit_data_quality():
    """
    检查: 日线新鲜度, 财务数据时效, ERP缓存, FRED利率, 缺失率, 异常值
    返回: {score, checks: [...], summary}
    """
    checks = []
    scores = []

    # ── 1.1 日线数据新鲜度 ──
    daily_files = glob.glob(os.path.join(DAILY_DIR, "*.parquet"))
    if daily_files:
        latest_dates = []
        stale_count = 0
        # V7.0: 蒙特卡洛随机抽样，消除排序带来的幸存者偏差
        sampled_daily = random.sample(daily_files, min(len(daily_files), 30))
        for f in sampled_daily:
            try:
                df = pd.read_parquet(f, columns=["trade_date"])
                if not df.empty:
                    max_d = str(df["trade_date"].max())
                    latest_dates.append(max_d)
                    if _stale_days(max_d) > AUDIT_CFG.get("daily_stale_warn_days", 3):
                        stale_count += 1
            except:
                stale_count += 1

        if latest_dates:
            newest = max(latest_dates)
            days = _stale_days(newest)
            s = max(0, 100 - days * 15)  # 每过期1天扣15分
            scores.append(s)
            _warn_d = AUDIT_CFG.get("daily_stale_warn_days", 3)
            _fail_d = AUDIT_CFG.get("daily_stale_fail_days", 5)
            status = "pass" if days <= 1 else ("warn" if days <= _warn_d else "fail")
            checks.append({
                "name": "日线数据新鲜度",
                "status": status,
                "detail": f"最新: {newest[:4]}-{newest[4:6]}-{newest[6:8]} ({days}天前)",
                "meta": f"共 {len(daily_files)} 个标的, {stale_count} 个过期",
                "score": s,
                "explanation": "日线行情是所有策略信号的基础输入。过期数据意味着均值回归的偏离度、动量排名、红利趋势判断全部基于陈旧信息，产生的买卖信号不可信。",
                "threshold": "🟢 ≤1天: 信号实时可靠 | 🟡 2-3天: 可能错过关键转折 | 🔴 >3天: 策略输出不可用",
                "action": "执行 python data_manager.py 或等待每日 15:35 自动同步",
            })
        else:
            scores.append(0)
            checks.append({"name": "日线数据新鲜度", "status": "fail", "detail": "无有效数据", "score": 0, "explanation": "日线行情是所有策略信号的基础输入。无数据则所有策略引擎无法运行。", "threshold": "🟢 ≤1天 | 🟡 2-3天 | 🔴 >3天/无数据", "action": "执行 python data_manager.py 拉取日线数据"})
    else:
        scores.append(0)
        checks.append({"name": "日线数据新鲜度", "status": "fail", "detail": "目录为空", "score": 0, "explanation": "日线行情是所有策略信号的基础输入。数据目录为空意味着系统从未初始化。", "threshold": "🟢 ≤1天 | 🟡 2-3天 | 🔴 >3天/空目录", "action": "首次部署需执行 python data_manager.py 初始化数据湖"})

    # ── 1.2 财务数据时效 ──
    fina_files = glob.glob(os.path.join(FINA_DIR, "*.parquet"))
    if fina_files:
        fina_latest = []
        # V7.0: 蒙特卡洛随机抽样，消除排序带来的幸存者偏差
        sampled_fina = random.sample(fina_files, min(len(fina_files), 10))
        for f in sampled_fina:
            try:
                df = pd.read_parquet(f)
                if not df.empty and "ann_date" in df.columns:
                    fina_latest.append(str(df["ann_date"].max()))
            except:
                pass
        if fina_latest:
            newest_fina = max(fina_latest)
            days_fina = _stale_days(newest_fina)
            _fina_fresh = AUDIT_CFG.get("fina_fresh_days", 90)
            # 财务数据季度更新, N天内算正常
            s = 100 if days_fina <= _fina_fresh else max(0, 100 - (days_fina - _fina_fresh))
            status = "pass" if days_fina <= _fina_fresh else ("warn" if days_fina <= _fina_fresh * 2 else "fail")
            scores.append(s)
            checks.append({
                "name": "财务指标时效",
                "status": status,
                "detail": f"最新公告: {newest_fina[:4]}-{newest_fina[4:6]}-{newest_fina[6:8]} ({days_fina}天前)",
                "meta": f"共 {len(fina_files)} 只股票财务数据",
                "score": s,
                "explanation": "ROE、EPS、净利润率等基本面因子来源于季报。财报每季度更新一次(1/4/7/10月)，90天内均属正常周期。超期意味着在用上个季度的财务画像选股。",
                "threshold": "🟢 ≤90天: 当季有效 | 🟡 91-180天: 跨季度，精度下降 | 🔴 >180天: 基本面因子失真",
                "action": "执行 python sync_dividend_data.py 或等待季报窗口后自动同步",
            })
        else:
            scores.append(50)
            checks.append({"name": "财务指标时效", "status": "warn", "detail": "无有效财务数据", "score": 50, "explanation": "基本面因子依赖季报数据，无有效数据将导致红利策略和因子分析无法正常运行。", "threshold": "🟢 ≤90天 | 🟡 91-180天 | 🔴 >180天/无数据", "action": "执行 python sync_dividend_data.py 拉取财务数据"})
    else:
        scores.append(30)
        checks.append({"name": "财务指标时效", "status": "warn", "detail": "财务目录为空", "score": 30, "explanation": "基本面因子依赖季报数据，目录为空意味着红利策略和因子分析模块无法运行。", "threshold": "🟢 ≤90天 | 🟡 91-180天 | 🔴 空目录", "action": "首次部署需执行 python data_manager.py 初始化财务数据"})

    # ── 1.3 ERP 缓存新鲜度 ──
    # V7.2: 只检查核心高频 ERP 文件 (PE/Yield/Rates)
    # 排除低频历史数据 (M1/history/score) 避免月度数据误报
    _ERP_SKIP_PATTERNS = ("_history", "_score", "_m1_", "_current_pe")
    all_erp_files = glob.glob(os.path.join(DATA_LAKE, "erp_*.parquet"))
    erp_files = [f for f in all_erp_files
                 if not any(p in os.path.basename(f) for p in _ERP_SKIP_PATTERNS)]
    # 如果过滤后无文件则回退到全量
    if not erp_files:
        erp_files = all_erp_files
    if erp_files:
        erp_ages = []
        for f in erp_files:
            mtime = os.path.getmtime(f)
            age_days = (time.time() - mtime) / 86400
            erp_ages.append(age_days)
        max_age = max(erp_ages)
        s = max(0, 100 - int(max_age) * 10)
        _erp_warn = AUDIT_CFG.get("erp_stale_warn_days", 3)
        _erp_fail = AUDIT_CFG.get("erp_stale_fail_days", 7)
        status = "pass" if max_age <= _erp_warn else ("warn" if max_age <= _erp_fail else "fail")
        scores.append(s)
        checks.append({
            "name": "ERP 缓存新鲜度",
            "status": status,
            "detail": f"最旧核心缓存: {max_age:.1f} 天前",
            "meta": f"共 {len(erp_files)} 个核心 ERP 文件 (排除 {len(all_erp_files) - len(erp_files)} 个低频历史)",
            "score": s,
            "explanation": "ERP(股权风险溢价)是股债性价比的核心指标，由全市场PE和10年国债收益率计算。过期数据会导致宏观择时引擎的仓位建议失准。仅检查核心高频文件 (PE-TTM/Yield/Rates)，M1等月度数据不纳入新鲜度判定。",
            "threshold": "🟢 ≤3天: 择时信号可靠 | 🟡 4-7天: 信号参考性下降 | 🔴 >7天: 择时建议不可用",
            "action": "重启服务器触发 ERP 预热，或等待每日 15:35 自动刷新",
        })
    else:
        scores.append(0)
        checks.append({"name": "ERP 缓存新鲜度", "status": "fail", "detail": "无 ERP 数据", "score": 0, "explanation": "无 ERP 数据将导致宏观择时引擎无法计算股债性价比，仓位建议缺失核心锚点。", "threshold": "🟢 ≤3天 | 🟡 4-7天 | 🔴 无数据", "action": "重启服务器或手动执行 erp_timing_engine.py 生成缓存"})

    # ── 1.4 FRED 利率数据 ──
    rates_files = glob.glob(os.path.join(DATA_LAKE, "rates_*.parquet"))
    if rates_files:
        rates_ages = []
        for f in rates_files:
            mtime = os.path.getmtime(f)
            age_days = (time.time() - mtime) / 86400
            rates_ages.append(age_days)
        max_age = max(rates_ages)
        s = max(0, 100 - int(max_age) * 8)
        # P1修复: FRED 阈值从 AUDIT_CFG 读取 (消除硬编码 3/7 天)
        _rates_warn = AUDIT_CFG.get("rates_stale_warn_days", 3)
        _rates_fail = AUDIT_CFG.get("rates_stale_fail_days", 7)
        status = "pass" if max_age <= _rates_warn else ("warn" if max_age <= _rates_fail else "fail")
        scores.append(s)
        checks.append({
            "name": "FRED 利率数据",
            "status": status,
            "detail": f"最旧: {max_age:.1f} 天前",
            "meta": f"共 {len(rates_files)} 个利率序列",
            "score": s,
            "explanation": "美联储FRED数据库提供美债收益率曲线(2Y/10Y/30Y)，是全球资产定价的锚。利率变化直接影响ERP计算、海外策略择时和跨市场配置权重。",
            "threshold": "🟢 ≤3天: 利率曲线实时 | 🟡 4-7天: 可能错过利率拐点 | 🔴 >7天: 海外策略失去参照",
            "action": "等待每日 18:30 自动刷新(北京时间)，或手动执行利率数据同步",
        })
    else:
        scores.append(0)
        checks.append({"name": "FRED 利率数据", "status": "fail", "detail": "无利率数据", "score": 0, "explanation": "无美债利率数据将导致ERP计算缺失利率端，海外策略模块完全瘫痪。", "threshold": "🟢 ≤3天 | 🟡 4-7天 | 🔴 无数据", "action": "检查网络连通性后执行利率数据同步脚本"})

    # ── 1.5 数据完整性与异常值抽检 ──
    if daily_files:
        # V7.0: 随机抽样 5 只股票进行多样本联合质量抽检，防止单股偏误与脏数据漏网
        sample_size = min(len(daily_files), 5)
        sampled_files = random.sample(daily_files, sample_size)
        total_rows_all = 0
        total_bad_rows = 0
        zero_vol_all = 0
        bad_price_all = 0
        read_success = 0
        sample_names = []
        
        for f in sampled_files:
            try:
                df = pd.read_parquet(f)
                if df.empty:
                    continue
                read_success += 1
                sample_names.append(os.path.basename(f))
                
                rows = len(df)
                total_rows_all += rows
                
                # 初始化本文件异常行掩码
                bad_mask = pd.Series(False, index=df.index)
                
                # 1. 零成交行数
                if "vol" in df.columns:
                    vol_mask = (df["vol"] == 0)
                    zero_vol_all += vol_mask.sum()
                    bad_mask |= vol_mask
                
                # 2. 负价格/零价格
                price_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
                for col in price_cols:
                    p_mask = (df[col] <= 0)
                    bad_price_all += p_mask.sum()
                    bad_mask |= p_mask
                
                # 3. 未除权价格跳空巨震 (单日涨跌幅绝对值 > 31%, 且成交量 > 0)
                if "close" in df.columns:
                    close_prev = df["close"].shift(1)
                    jump_mask = (df["close"] / close_prev - 1).abs() > 0.31
                    if "vol" in df.columns:
                        jump_mask &= (df["vol"] > 0)
                    bad_price_all += jump_mask.sum()
                    bad_mask |= jump_mask
                
                total_bad_rows += bad_mask.sum()
            except Exception:
                pass
                
        if read_success > 0:
            total_rows_all = max(total_rows_all, 1)
            anomaly_pct = total_bad_rows / total_rows_all * 100
            s = max(0, 100 - int(anomaly_pct * 10))
            status = "pass" if anomaly_pct < 1 else ("warn" if anomaly_pct < 5 else "fail")
            scores.append(s)
            checks.append({
                "name": "数据完整性与异常值",
                "status": status,
                "detail": f"异常占比: {total_bad_rows}/{total_rows_all} ({anomaly_pct:.1f}%) [零成交:{zero_vol_all}行, 价格异常:{bad_price_all}行]",
                "meta": f"联合抽检 {read_success} 只样本: {', '.join(sample_names[:3])}",
                "score": s,
                "explanation": "零成交日(停牌)、非正价格(脏数据)或未除权跳空巨幅异动(单日变动>31%)会严重带偏量化因子的统计分布。使用多样本联合抽查，可以全面覆盖脏数据盲区。",
                "threshold": "🟢 <1%: 数据完整干净 | 🟡 1-5%: 少量偏误 | 🔴 >5%: 存在严重脏数据",
                "action": "执行数据清洗脚本, 剔除退市/长期停牌股，并重新拉取未复权异常数据",
            })
        else:
            scores.append(0)
            checks.append({
                "name": "数据完整性与异常值",
                "status": "fail",
                "detail": "多样本抽检全部失败",
                "score": 0,
                "explanation": "随机选择 of 5 只股票 Parquet 文件均无法正确读取，这提示底层数据湖格式可能发生大面积损坏。",
                "threshold": "🟢 <1% | 🟡 1-5% | 🔴 全部损坏",
                "action": "检查 Parquet 库依赖或清空 data_lake/ 重新同步"
            })

    # ── V22.0: 新增数据完整性检查 ──
    # 资产参数矩阵
    param_path = os.path.join(PROJECT_ROOT, "mr_asset_class_params.json")
    if os.path.exists(param_path):
        try:
            with open(param_path, 'r', encoding='utf-8') as f:
                acp = json.load(f)
            classes = [k for k in acp if not k.startswith("_")]
            scores.append(100 if len(classes) >= 3 else 80)
            checks.append({
                "name": "V22.0 资产参数矩阵",
                "status": "pass" if len(classes) >= 3 else "warn",
                "detail": f"{len(classes)} 类资产参数就绪 ({', '.join(classes[:4])})",
                "score": 100 if len(classes) >= 3 else 80,
                "explanation": "资产类别差异化参数矩阵是信号评分系统的核心。缺失时引擎回退到旧版通用参数，信号无法按波动率自适应调整。",
                "threshold": "🟢 ≥3类就绪 | 🔴 缺失",
                "action": "检查 mr_asset_class_params.json 文件完整性",
            })
        except Exception:
            scores.append(40)
            checks.append({"name": "V22.0 资产参数矩阵", "status": "fail", "detail": "JSON 解析失败", "score": 40, "explanation": "参数文件格式损坏。", "action": "从 git 恢复 mr_asset_class_params.json"})
    else:
        scores.append(30)
        checks.append({"name": "V22.0 资产参数矩阵", "status": "fail", "detail": "文件不存在", "score": 30, "explanation": "V22.0 核心配置文件缺失, 引擎将使用旧版通用参数。", "action": "运行 python 重新生成参数文件"})

    # 市场事件日志健康
    event_log = os.path.join(DATA_LAKE, "market_events.json")
    if os.path.exists(event_log):
        try:
            size = os.path.getsize(event_log)
            events_ok = size < 5 * 1024 * 1024  # < 5MB
            scores.append(100 if events_ok else 70)
            checks.append({
                "name": "V22.0 事件日志健康",
                "status": "pass" if events_ok else "warn",
                "detail": f"{size/1024:.0f}KB" + (" (正常)" if events_ok else " (偏大, 建议清理)"),
                "score": 100 if events_ok else 70,
                "explanation": "市场事件日志记录 VIX 跳变、Regime 切换等突变。过大说明事件记录频率异常或清理机制失效。",
                "threshold": "🟢 <5MB | 🟡 5-10MB | 🔴 >10MB",
                "action": "删除 data_lake/market_events.json 重置日志" if not events_ok else None,
            })
        except Exception:
            pass

    final_score = int(np.mean(scores)) if scores else 0
    return {
        "module": "data_quality",
        "label": "📡 数据质量",
        "score": final_score,
        "grade": _grade(final_score),
        "checks": checks,
    }


# ═══════════════════════════════════════════════════════
#  模块 2: 策略健康审计 V6.0 — 科学决策版
#  升级点:
#    1. 从 AUDIT_CFG 读取 strategy_fresh_days / strategy_stale_days (消灭硬编码)
#    2. 线性衰减评分 (替代 100/70 两档阶梯)
#    3. 策略加权平均 (按交易占比分配权重, 替代等权)
#    4. 优先从 JSON 内部 generated_at/run_time 提取真实优化时间 (不依赖 mtime)
#    5. 提取样本外质量指标 (combined_score / composite_score) 展示
#    6. Regime 三态深度校验 (检查 BULL/RANGE/BEAR 完整性 + 关键参数字段)
# ═══════════════════════════════════════════════════════
def _extract_optimize_meta(fp, name):
    """
    从优化结果 JSON 提取元数据 (优化时间 + 质量分数)。
    每种策略文件结构不同, 统一适配。
    返回: (optimized_at_str|None, quality_score|None, is_corrupted|Bool)
    """
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        opt_at = None
        quality = None
        if isinstance(data, dict):
            # 均值回归: {"generated_at": "...", "combined_score": 0.49}
            opt_at = data.get("generated_at") or data.get("run_time")
            # ERP择时: {"meta": {"timestamp": "..."}}
            if not opt_at and isinstance(data.get("meta"), dict):
                opt_at = data["meta"].get("timestamp")
            quality = data.get("combined_score") or data.get("composite_score")
        elif isinstance(data, list) and len(data) > 0:
            # 红利趋势: list, 取首条 final_score
            quality = data[0].get("final_score") if isinstance(data[0], dict) else None
        return opt_at, quality, False
    except Exception as e:
        logger.error("Audit: 解析参数文件 %s 失败 (可能文件已损坏): %s", fp, e)
        return None, None, True


def _optimized_age_days(opt_at_str, mtime_fallback):
    """
    优先用 JSON 内 optimized_at 计算天数, mtime 兜底。
    返回: (age_days, date_display_str, source_label)
    """
    if opt_at_str:
        try:
            # 支持 ISO 格式: "2026-04-21T23:53:07.839750"
            clean = opt_at_str.replace("T", " ").split(".")[0]
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
            age = (datetime.now() - dt).total_seconds() / 86400
            return max(0, age), dt.strftime("%Y-%m-%d"), "JSON元数据"
        except Exception:
            pass
    # mtime 兜底
    age = (time.time() - mtime_fallback) / 86400
    return max(0, age), datetime.fromtimestamp(mtime_fallback).strftime("%Y-%m-%d"), "文件修改时间"


def audit_strategy_health():
    checks = []
    check_scores = []   # (score, weight, name) 三元组
    check_weights = []

    # V6.1 生产级差异化时效阈值 (生存期 TTL)
    # 高频/波动敏感策略收紧周期，宏观/低频策略放宽周期，彻底杜绝警报疲劳
    STRATEGY_TTLS = {
        "均值回归": {
            "fresh": AUDIT_CFG.get("strategy_fresh_days_mr", 14),
            "stale": AUDIT_CFG.get("strategy_stale_days_mr", 30)
        },
        "行业动量": {
            "fresh": AUDIT_CFG.get("strategy_fresh_days_mom", 60),
            "stale": AUDIT_CFG.get("strategy_stale_days_mom", 90)
        },
        "红利趋势": {
            "fresh": AUDIT_CFG.get("strategy_fresh_days_div", 90),
            "stale": AUDIT_CFG.get("strategy_stale_days_div", 180)
        },
        "ERP择时": {
            "fresh": AUDIT_CFG.get("strategy_fresh_days_erp", 180),
            "stale": AUDIT_CFG.get("strategy_stale_days_erp", 360)
        }
    }

    _fresh_default = AUDIT_CFG.get("strategy_fresh_days", 30)
    _stale_default = AUDIT_CFG.get("strategy_stale_days", 60)

    # V6.2 各策略参数的质量分参考基准 (用于将 Quality 因子融入时效衰减)
    # 若 quality_score 高于基准，表示参数稳健，折算 age 变小，衰减减慢；反之加速衰减。
    STRATEGY_QUALITY_BENCHMARKS = {
        "均值回归": 0.50,
        "行业动量": 0.50,
        "红利趋势": 0.50,
        "ERP择时":  0.50,
    }

    # V6.0: 策略权重 — 按实际交易占比 + 风险贡献分配
    # 均值回归: 主力策略, 贡献 60%+ 交易信号 → 最高权重
    # 行业动量: 中频轮动, 与 MR 互补 → 中等
    # 红利趋势/ERP择时: 低频辅助 → 较低
    STRATEGY_WEIGHTS = {
        "均值回归":      0.35,
        "红利趋势":      0.15,
        "行业动量":      0.20,
        "ERP择时":       0.15,
        "_regime":        0.15,    # Regime 三态参数 (均值回归基础设施)
    }

    # 策略参数解释映射
    STRATEGY_EXPLANATIONS = {
        "均值回归": {
            "explanation": "均值回归参数包括偏离度阈值、持有天数、ATR波动率乘数等。过期参数无法反映当前市场波动率环境，导致均值回归策略在升波跌市中过早接盘或在低波市中信号过少。",
            "action": "执行 python mr_auto_optimize.py 重新优化参数",
        },
        "红利趋势": {
            "explanation": "红利趋势参数包括股息率阈值、趋势确认周期、位置管理乘数等。股息率对标基准需跟踪利率环境变化，利率上行期应提高股息率门槛。",
            "action": "执行红利策略参数优化器重新校准",
        },
        "行业动量": {
            "explanation": "动量轮动参数包括动量窗口(20/60日)、换仓频率、拥挤度过滤阈等。动量周期存在显著的时变性，需至少每季度校准一次，否则可能追高在动量更换的拐点。",
            "action": "执行 python run_optimizer.py 重新搜索最优参数",
        },
        "ERP择时": {
            "explanation": "ERP择时参数包括 ERP Z-Score 阈值、仓位调节曲线、滴答速度等。宏观择时模型需与经济周期同步，参数过期可能导致在流动性危机时仍维持高仓位。",
            "action": "执行 python erp_backtest_optimizer.py 重新优化宏观参数",
        },
    }

    for name, filename in OPTIMIZATION_FILES.items():
        fp = os.path.join(PROJECT_ROOT, filename)
        w = STRATEGY_WEIGHTS.get(name, 0.15)
        
        # 获取该策略的差异化 TTL
        ttl = STRATEGY_TTLS.get(name, {"fresh": _fresh_default, "stale": _stale_default})
        s_fresh = ttl["fresh"]
        s_stale = ttl["stale"]

        if os.path.exists(fp):
            mtime = os.path.getmtime(fp)

            # 读取文件大小验证非空
            fsize = os.path.getsize(fp)
            if fsize < 50:
                check_scores.append(20)
                check_weights.append(w)
                strategy_exp = STRATEGY_EXPLANATIONS.get(name, {})
                checks.append({
                    "name": f"{name} 参数文件",
                    "status": "fail",
                    "detail": f"文件异常 ({fsize} bytes)",
                    "score": 20,
                    "explanation": f"{name}参数文件损坏或为空，策略引擎将使用默认参数运行，实盘表现可能严重偏离回测结果。",
                    "threshold": f"🟢 ≤{s_fresh}天: 参数有效 | 🟡 {s_fresh+1}-{s_stale}天: 建议重优化 | 🔴 >{s_stale}天/损坏: 必须修复",
                    "action": strategy_exp.get("action", "重新执行参数优化器"),
                })
                continue

            # V6.3: 优先从 JSON 内部提取真实优化时间与损坏标记
            opt_at_str, quality_score, is_corrupted = _extract_optimize_meta(fp, name)

            # 机构级风控加固：如果参数文件存在但 JSON 解析异常，直接 20分 FAIL 熔断，禁止降级
            if is_corrupted:
                check_scores.append(20)
                check_weights.append(w)
                strategy_exp = STRATEGY_EXPLANATIONS.get(name, {})
                checks.append({
                    "name": f"{name}",
                    "status": "fail",
                    "detail": "参数文件已损坏 (JSON解析失败)",
                    "meta": f"文件: {filename} · 权重: {int(w*100)}%",
                    "score": 20,
                    "explanation": f"{name}参数文件格式破损，策略加载将直接崩溃，触发风控一票否决机制。",
                    "threshold": "🟢 解析成功 | 🔴 语法损坏",
                    "action": strategy_exp.get("action", "重新执行参数优化器"),
                })
                continue

            age_days, date_display, time_source = _optimized_age_days(opt_at_str, mtime)

            # V6.2 质量-时效二维折算 (Quality-Adjusted Age Decay)
            # 基准折算：quality_mult = benchmark / quality_score
            # 限幅在 [0.6, 1.8] 区间，防止异常数据造成时间失真
            quality_mult = 1.0
            if quality_score is not None and quality_score > 0:
                benchmark = STRATEGY_QUALITY_BENCHMARKS.get(name, 0.50)
                quality_mult = min(1.8, max(0.6, benchmark / quality_score))
            
            adjusted_age = age_days * quality_mult

            # V6.2: 线性衰减评分基于折算天数 (adjusted_age)
            #   [0, s_fresh] → 100
            #   (s_fresh, s_stale] → 100 → 60 线性衰减
            #   (s_stale, ∞) → 60 → 20 缓衰减 (每天 -0.5)
            if adjusted_age <= s_fresh:
                s = 100
                status = "pass"
            elif adjusted_age <= s_stale:
                decay_ratio = (adjusted_age - s_fresh) / (s_stale - s_fresh)
                s = int(100 - decay_ratio * 40)   # 100 → 60
                status = "warn"
            else:
                s = max(20, int(60 - (adjusted_age - s_stale) * 0.5))
                status = "fail"

            # V6.1 生产级安全加固：mtime 降级防瞒报惩罚
            if time_source == "文件修改时间":
                s = min(s, 80)
                if status == "pass":
                    status = "warn"

            check_scores.append(s)
            check_weights.append(w)
            strategy_exp = STRATEGY_EXPLANATIONS.get(name, {})

            # 构建增强 meta: 质量分数 + 时间来源 (包含瞒报风控警告与折算系数)
            meta_parts = [f"文件: {filename} ({fsize/1024:.1f}KB)"]
            if quality_score is not None:
                meta_parts.append(f"质量分: {quality_score:.3f}")
            if time_source == "文件修改时间":
                meta_parts.append("时间源: mtime(未解析到生成时间,强制封顶80分)")
            else:
                meta_parts.append(f"时间源: {time_source}")
                if quality_score is not None:
                    meta_parts.append(f"折算系数: {quality_mult:.2f}x")
            meta_parts.append(f"权重: {int(w*100)}%")

            # 增强 detail 显示真实天数与折算有效天数
            detail_str = f"最后优化: {date_display} ({int(age_days)}天前)"
            if abs(quality_mult - 1.0) > 0.02 and time_source != "文件修改时间":
                detail_str += f" · 有效折算: {int(adjusted_age)}天"

            checks.append({
                "name": f"{name}",
                "status": status,
                "detail": detail_str,
                "meta": " · ".join(meta_parts),
                "score": s,
                "explanation": strategy_exp.get("explanation", f"{name}策略的核心参数文件，定期优化可确保策略与当前市场环境匹配。"),
                "threshold": f"🟢 ≤{s_fresh}天: 参数新鲜 | 🟡 {s_fresh+1}-{s_stale}天: 线性衰减 | 🔴 >{s_stale}天: 策略可能失效",
                "action": strategy_exp.get("action", "执行对应策略的参数优化器"),
            })
        else:
            check_scores.append(0)
            check_weights.append(w)
            strategy_exp = STRATEGY_EXPLANATIONS.get(name, {})
            checks.append({
                "name": f"{name}",
                "status": "fail",
                "detail": "参数文件不存在",
                "meta": f"期望: {filename} · 权重: {int(w*100)}%",
                "score": 0,
                "explanation": f"{name}参数文件缺失，该策略引擎无法运行。需先执行参数优化生成配置文件。",
                "threshold": f"🟢 ≤{s_fresh}天 | 🟡 {s_fresh+1}-{s_stale}天 | 🔴 文件缺失",
                "action": strategy_exp.get("action", "执行对应策略的参数优化器"),
            })

    # ── Regime 参数文件深度校验 V6.0 ──
    # 不仅检查数量, 还验证 BULL/RANGE/BEAR 每套参数的关键字段完整性
    _REQUIRED_REGIMES = ("BULL", "RANGE", "BEAR")
    _REQUIRED_PARAM_KEYS = {"N_trend", "rsi_period", "rsi_buy", "rsi_sell", "bias_buy", "stop_loss"}
    regime_w = STRATEGY_WEIGHTS.get("_regime", 0.15)

    regime_fp = os.path.join(PROJECT_ROOT, "mr_per_regime_params.json")
    if os.path.exists(regime_fp):
        try:
            with open(regime_fp, "r", encoding="utf-8") as f:
                regime_data = json.load(f)

            # 支持两种结构: {"regimes": {"BULL": ...}} 或 {"BULL": ...}
            regimes = regime_data.get("regimes", regime_data) if isinstance(regime_data, dict) else {}

            regime_ok = 0
            regime_issues = []
            regime_details = []
            for rname in _REQUIRED_REGIMES:
                rblock = regimes.get(rname, {})
                # 参数可能在 rblock 直接层或 rblock["params"] 子层
                rparams = rblock.get("params", rblock) if isinstance(rblock, dict) else {}
                if not rparams:
                    regime_issues.append(f"{rname}: 空配置")
                    continue
                missing = _REQUIRED_PARAM_KEYS - set(rparams.keys())
                if missing:
                    regime_issues.append(f"{rname}: 缺少 {', '.join(sorted(missing))}")
                else:
                    regime_ok += 1
                    # 提取质量摘要
                    score_val = rblock.get("combined_score")
                    if score_val is not None:
                        regime_details.append(f"{rname}={score_val:.2f}")

            # 评分: 3套完整=100, 2套=75, 1套=50, 0套=20
            s = {3: 100, 2: 75, 1: 50, 0: 20}.get(regime_ok, 20)

            # 检查时效性 (Regime 文件也有 generated_at)
            regime_gen = regime_data.get("generated_at") if isinstance(regime_data, dict) else None
            regime_age_info = ""
            if regime_gen:
                try:
                    clean = str(regime_gen).replace("T", " ").split(".")[0]
                    dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
                    r_age = (datetime.now() - dt).total_seconds() / 86400
                    regime_age_info = f" · 优化于 {int(r_age)} 天前"
                    # Regime 过期也扣分 (半衰期 90 天, 因为 regime 切换频率低)
                    if r_age > 90:
                        age_penalty = min(30, int((r_age - 90) * 0.3))
                        s = max(20, s - age_penalty)
                except Exception:
                    pass

            detail_str = f"{regime_ok}/3 套参数完整"
            if regime_details:
                detail_str += f" · 质量分: {', '.join(regime_details)}"
            detail_str += regime_age_info
            if regime_issues:
                detail_str += f" · 问题: {'; '.join(regime_issues)}"

            status = "pass" if regime_ok == 3 else ("warn" if regime_ok >= 1 else "fail")
            check_scores.append(s)
            check_weights.append(regime_w)
            checks.append({
                "name": "Regime 三态参数",
                "status": status,
                "detail": detail_str,
                "meta": f"校验字段: {', '.join(sorted(_REQUIRED_PARAM_KEYS))} · 权重: {int(regime_w*100)}%",
                "score": s,
                "explanation": "市场存在牛市/熊市/震荡三种状态(Regime)，每种状态的最优参数差异巨大。V6.0 不仅检查数量，还验证每套参数的 6 个关键字段(N_trend/rsi_period/rsi_buy/rsi_sell/bias_buy/stop_loss)是否完整。",
                "threshold": "🟢 3/3完整: 全状态覆盖 | 🟡 1-2套: 部分缺失 | 🔴 0套/损坏: 策略退化为单状态",
                "action": "执行 python mr_per_regime_optimizer.py 生成三态参数",
            })
        except Exception:
            check_scores.append(40)
            check_weights.append(regime_w)
            checks.append({"name": "Regime 三态参数", "status": "fail", "detail": "JSON 解析失败", "score": 40, "explanation": "Regime 参数文件损坏，均值回归引擎将退化为单状态模式。", "threshold": "🟢 3/3完整 | 🟡 1-2套 | 🔴 损坏", "action": "删除损坏文件后执行 python mr_per_regime_optimizer.py"})
    else:
        check_scores.append(30)
        check_weights.append(regime_w)
        checks.append({"name": "Regime 三态参数", "status": "fail", "detail": "文件不存在", "score": 30, "explanation": "无 Regime 参数意味着均值回归策略无法自适应市场状态切换，在牛熊转换时可能产生大量错误信号。", "threshold": "🟢 3/3完整 | 🟡 1-2套 | 🔴 文件缺失", "action": "执行 python mr_per_regime_optimizer.py 生成三态参数"})

    # V6.0: 加权平均 (替代等权 np.mean)
    if check_scores and check_weights:
        total_w = sum(check_weights)
        final_score = int(sum(s * w for s, w in zip(check_scores, check_weights)) / total_w) if total_w > 0 else 0
    else:
        final_score = 0

    # V6.6: Fail 数量断路器 (Circuit Breaker)
    # 防止加权均值掩盖结构性问题：1个高分策略不应拉高3个fail的模块
    # 机构级风控标准：多数检查失败时，评分必须反映真实风险
    fail_count = sum(1 for c in checks if c.get("status") == "fail")
    circuit_breaker = None
    if fail_count >= 3:
        cap = 50
        if final_score > cap:
            circuit_breaker = {"reason": f"{fail_count}项检查失败", "cap": cap, "original": final_score}
            final_score = cap
    elif fail_count >= 2:
        cap = 65
        if final_score > cap:
            circuit_breaker = {"reason": f"{fail_count}项检查失败", "cap": cap, "original": final_score}
            final_score = cap

    # V6.1 生产级致命指标联锁 (Critical Path Interlocking)
    # 均值回归是高频交易主力策略，Regime 三态是其关键基石。
    # 若这两项中任意一项得分低于 60 (fail 状态)，说明核心决策引擎处于失控边缘。
    # 此时，即使低频辅助策略分数再高，总评分也将一票否决，强制压制在不及格线 (59分) 以下，避免策略裸跑。
    mr_score = next((c["score"] for c in checks if c["name"] == "均值回归"), 100)
    regime_score = next((c["score"] for c in checks if c["name"] == "Regime 三态参数"), 100)
    if mr_score < 60 or regime_score < 60:
        if final_score >= 60:
            if not circuit_breaker:
                circuit_breaker = {"reason": "核心路径联锁", "cap": 59, "original": final_score}
            final_score = 59

    result = {
        "module": "strategy_health",
        "label": "⚙️ 策略健康",
        "score": final_score,
        "grade": _grade(final_score),
        "checks": checks,
    }
    if circuit_breaker:
        result["circuit_breaker"] = circuit_breaker
    return result


# ═══════════════════════════════════════════════════════
#  V23.0: 四类资产分类 + Regime 差异化止损
#  对齐 mean_reversion_engine._classify_asset 的四层分类法
# ═══════════════════════════════════════════════════════

# 海外 ETF 代码白名单 (与 MR 引擎标的池完全一致)
_OVERSEAS_ETF_CODES = {
    "513500.SH", "513100.SH", "513520.SH", "513530.SH",
    "513130.SH", "513180.SH", "513950.SH", "513120.SH",
    "513090.SH", "159545.SZ", "513970.SH",
}

# 宽基 ETF 代码白名单
_BROAD_ETF_CODES = {
    "510300.SH", "510500.SH", "512100.SH", "159915.SZ", "159949.SZ",
    "588000.SH", "588220.SH", "159781.SZ",
}

def _is_etf(ts_code: str) -> bool:
    """
    判断标的是否为 ETF。
    A股 ETF 代码规则:
      - 上交所: 51xxxx.SH, 56xxxx.SH, 58xxxx.SH, 588xxx.SH
      - 深交所: 159xxx.SZ, 160xxx.SZ, 16xxxx.SZ
    """
    if not ts_code:
        return False
    code = ts_code.split(".")[0]
    etf_prefixes = ("51", "56", "58", "159", "160", "16")
    return code.startswith(etf_prefixes)


def _classify_asset_for_audit(ts_code: str, name: str = "") -> str:
    """
    V23.0 四类资产分类 — 与 mean_reversion_engine._classify_asset 完全对齐:
      - individual_stock: A股个股 (波动最大, 止损最宽)
      - sector_etf:       行业/主题ETF (中等波动)
      - broad_etf:        宽基ETF (低波动, 止损最严)
      - overseas_etf:     海外宽基ETF (含汇率风险)
    """
    if not ts_code:
        return "sector_etf"
    # 优先匹配白名单
    if ts_code in _OVERSEAS_ETF_CODES:
        return "overseas_etf"
    if ts_code in _BROAD_ETF_CODES:
        return "broad_etf"
    # 名称辅助判断
    if name:
        if any(k in name for k in ("标普", "纳指", "日经", "恒生", "港股通", "海外")):
            return "overseas_etf"
        if any(k in name for k in ("沪深300", "中证500", "中证1000", "创业板", "科创50", "科创100")):
            return "broad_etf"
    # 代码规则: 非 ETF 前缀 = 个股
    if not _is_etf(ts_code):
        return "individual_stock"
    return "sector_etf"


# 四类资产默认止损线 (与 mr_asset_class_params.json 同步)
_DEFAULT_SL_BY_CLASS = {
    "individual_stock": -12.0,   # 个股: 波动大, 容忍度最宽
    "sector_etf":       -8.0,    # 行业ETF: 中等
    "broad_etf":        -6.0,    # 宽基ETF: 低波动, 纪律最严
    "overseas_etf":     -8.0,    # 海外ETF: 含汇率风险, 适度宽容
}

_ASSET_CLASS_LABELS = {
    "individual_stock": "个股",
    "sector_etf":       "行业ETF",
    "broad_etf":        "宽基ETF",
    "overseas_etf":     "海外ETF",
}


def _get_stop_loss_line(ts_code: str, name: str = "") -> tuple:
    """
    V23.0: 读取资产类别对应的止损线。
    优先从 mr_asset_class_params.json 读取 (与交易引擎完全一致),
    降级到 _DEFAULT_SL_BY_CLASS 硬编码兜底。
    返回: (stop_loss_pct, asset_class_key, asset_class_label)
    """
    asset_class = _classify_asset_for_audit(ts_code, name)
    label = _ASSET_CLASS_LABELS.get(asset_class, "行业ETF")

    # 尝试从参数矩阵读取 (与 MR 引擎实际执行的止损线完全一致)
    try:
        param_path = os.path.join(PROJECT_ROOT, "mr_asset_class_params.json")
        if os.path.exists(param_path):
            with open(param_path, 'r', encoding='utf-8') as f:
                matrix = json.load(f)
            class_params = matrix.get(asset_class, {})
            # 取所有 Regime 中最宽松的止损线 (审计红线 = 最后防线)
            sl_values = []
            for regime_key in ("BULL", "RANGE", "BEAR"):
                regime_params = class_params.get(regime_key, {})
                sl = regime_params.get("stop_loss")
                if sl is not None:
                    sl_values.append(abs(float(sl)) * 100)  # 0.12 → 12
            if sl_values:
                return -max(sl_values), asset_class, label  # 取最宽松 (最大绝对值)
    except Exception:
        pass

    # 降级: 硬编码兜底
    return _DEFAULT_SL_BY_CLASS.get(asset_class, -8.0), asset_class, label


# ═══════════════════════════════════════════════════════
#  模块 3: 风控审计 V2.1 — 个股/ETF 差异化止损
# ═══════════════════════════════════════════════════════
#  V2.1 升级:
#    1. 止损差异化: 个股 -12% / ETF -8%
#    2. 总仓位上限从 85% 放宽至 95%
#    3. 使用 portfolio_engine 实时估值
#    4. 单票阈值统一为 20% (与 POSITION_LIMIT 一致)
#    5. 行业集中度 + 持仓分散度审计
# ═══════════════════════════════════════════════════════
def _get_live_portfolio():
    """
    尝试从 portfolio_engine 获取实时估值 (含真实价格/盈亏)。
    若引擎不可用，则降级为成本估算 (fallback)。
    返回: (pos_list, cash, total_asset, is_live, risk_metrics, market_value)
    market_value: 券商参考市值 (导入当日) 或 Tushare 重算市值 (隔日)
    """
    # ── 优先: 调用 portfolio_engine 单例 (真实价格) ──
    try:
        from portfolio_engine import get_portfolio_engine
        engine = get_portfolio_engine()
        val = engine.get_valuation()
        pos_list = val.get("positions", [])
        cash = val.get("cash", 0)
        total_asset = val.get("total_asset", 0)
        market_value = val.get("market_value", 0)

        # 尝试获取风险指标 (行业敞口)
        risk_metrics = None
        try:
            risk_metrics = engine.calculate_risk_metrics()
            if isinstance(risk_metrics, dict) and risk_metrics.get("status") in ("empty", "insufficient_data", "zero_value"):
                risk_metrics = None
        except Exception:
            pass

        return pos_list, cash, total_asset, True, risk_metrics, market_value
    except Exception as e:
        print(f"[Audit] portfolio_engine 不可用, 降级为成本估算: {e}")

    # ── 降级: 从 JSON 手动解析 (成本估算) ──
    pf_path = os.path.join(PROJECT_ROOT, "data_lake", "portfolio_store.json")
    if not os.path.exists(pf_path):
        return [], 0, 0, False, None, 0
    try:
        with open(pf_path, "r", encoding="utf-8") as f:
            pf = json.load(f)
        positions_raw = pf.get("positions", {})
        cash = pf.get("cash", 0)
        pos_list = []
        if isinstance(positions_raw, dict):
            for code, info in positions_raw.items():
                amt = info.get("amount", 0)
                cost = info.get("cost", 0)
                mv = amt * cost
                pos_list.append({
                    "ts_code": code,
                    "name": info.get("name", code),
                    "amount": amt,
                    "cost": cost,
                    "price": cost,
                    "market_value": mv,
                    "pnl": 0,
                    "pnl_pct": 0,
                    "weight": 0,
                    "industry": "未知",
                })
        total_mv = sum(p.get("market_value", 0) for p in pos_list)
        total_asset = cash + total_mv
        for p in pos_list:
            p["weight"] = round(p["market_value"] / max(total_asset, 1) * 100, 2)
        return pos_list, cash, total_asset, False, None, total_mv
    except Exception:
        return [], 0, 0, False, None, 0


def audit_risk_control():
    checks = []
    scores = []

    # ── 获取实时组合数据 ──
    pos_list, cash, total_asset, is_live, risk_metrics, ref_market_value = _get_live_portfolio()
    data_source = "实时估值" if is_live else "成本估算 (降级)"

    if total_asset <= 0 and not pos_list:
        scores.append(80)
        checks.append({
            "name": "投资组合",
            "status": "pass",
            "detail": "组合未初始化或空仓",
            "score": 80,
            "explanation": "组合文件记录当前持仓和现金。未初始化时风控检查无法运行，但不影响其他模块。",
            "threshold": "文件应存在且可解析",
            "action": "在投资组合页面初始化账户",
        })
    elif not pos_list:
        scores.append(100)
        checks.append({
            "name": "持仓集中度",
            "status": "pass",
            "detail": "当前空仓, 无风险敞口",
            "score": 100,
            "explanation": "单只股票占总资产比超过20%意味着个股黑天鹅风险集中。分散持仓是风控第一铁律。",
            "threshold": "🟢 ≤20%: 合规 | 🟡 21-30%: 偏集中 | 🔴 >30%: 个股风险过大",
            "action": "保持单只不超20%，超标时分批减仓至合规线下",
        })
        scores.append(100)
        checks.append({
            "name": "止损合规 (四类差异化)",
            "status": "pass",
            "detail": "无持仓, 无需止损检查",
            "score": 100,
            "explanation": "V23.0 四类差异化止损: 个股-12% / 行业ETF-8% / 宽基ETF-6% / 海外ETF-8%。对齐信号评分系统 mr_asset_class_params.json。",
            "threshold": "🟢 0只违规 | 🟡 1只: 警告 | 🔴 ≥2只: 纪律崩溃",
            "action": "按四类差异化止损标准执行",
        })
    else:
        # ── 检查 1: 单票集中度 (基数=总资产, 阈值从PAUDIT_CFG) ──
        SINGLE_LIMIT = AUDIT_CFG.get("single_position_limit", 20.0)

        max_weight = 0
        max_name = ""
        violations = []
        for p in pos_list:
            w = p.get("weight", 0)
            if w <= 0:
                w = p.get("market_value", 0) / max(total_asset, 1) * 100
            name = p.get("name", p.get("ts_code", "?"))
            if w > max_weight:
                max_weight = w
                max_name = name
            if w > SINGLE_LIMIT:
                violations.append(f"{name} ({w:.1f}%)")

        s = 100 if max_weight <= SINGLE_LIMIT else (70 if max_weight <= 30 else 40)
        scores.append(s)
        checks.append({
            "name": "持仓集中度",
            "status": "pass" if not violations else ("warn" if max_weight <= 30 else "fail"),
            "detail": f"最大单只: {max_name} (占总资产 {max_weight:.1f}%)",
            "meta": f"{'、'.join(violations)} 超过{int(SINGLE_LIMIT)}%上限" if violations else f"全部达标 · {len(pos_list)}只持仓 · [{data_source}]",
            "score": s,
            "explanation": f"单只股票占总资产超过{int(SINGLE_LIMIT)}%意味着个股黑天鹅风险集中。如遇财报雷、停牌、行业突变，可能导致组合单日亏损3-5%以上。本阈值与交易引擎的仓位上限(POSITION_LIMIT={int(SINGLE_LIMIT)}%)保持一致。",
            "threshold": f"🟢 ≤{int(SINGLE_LIMIT)}%: 分散合规 | 🟡 {int(SINGLE_LIMIT)+1}-30%: 偏集中 | 🔴 >30%: 必须立即减仓",
            "action": f"将超标持仓分批卖出，确保单只不超过总资产的{int(SINGLE_LIMIT)}%",
        })

        # ── 检查 2: 止损合规 V23.0 (四类资产 × Regime 差异化止损) ──
        # 对齐信号评分系统: 个股-12% / 行业ETF-8% / 宽基ETF-6% / 海外ETF-8%
        breach_list = []
        worst_loss = 0
        worst_name = ""
        sl_summary = {}  # 汇总每类资产的止损线

        for p in pos_list:
            pnl_pct = p.get("pnl_pct", 0)
            ts_code = p.get("ts_code", "")
            name = p.get("name", ts_code or "?")
            sl_line, asset_class, asset_label = _get_stop_loss_line(ts_code, name)
            sl_summary[asset_label] = sl_line
            if pnl_pct < sl_line:
                breach_list.append(f"{name}[{asset_label}] ({pnl_pct:.1f}% < {sl_line}%)")
            if pnl_pct < worst_loss:
                worst_loss = pnl_pct
                worst_name = name

        breach_count = len(breach_list)
        s = 100 if breach_count == 0 else max(0, 100 - breach_count * 25)
        scores.append(s)

        if breach_count > 0:
            detail = f"⚠️ {breach_count} 只突破止损线: {', '.join(breach_list[:3])}"
        elif worst_loss < 0:
            detail = f"全部在止损线内 · 最大浮亏: {worst_name} ({worst_loss:.1f}%)"
        else:
            detail = "全部盈利或持平"

        # 构建四类止损摘要
        sl_parts = [f"{k}{v}%" for k, v in sorted(sl_summary.items(), key=lambda x: x[1])]
        sl_display = " / ".join(sl_parts) if sl_parts else "个股-12%/行业ETF-8%/宽基ETF-6%/海外ETF-8%"

        checks.append({
            "name": f"止损合规 ({sl_display})",
            "status": "pass" if breach_count == 0 else "fail",
            "detail": detail,
            "meta": f"四类差异化止损 · [{data_source}]" + (f" · 最大浮亏: {worst_loss:.1f}%" if worst_loss < 0 else ""),
            "score": s,
            "explanation": f"V23.0 四类差异化止损 (对齐信号评分系统 mr_asset_class_params.json): 个股波动最大允许-12%; 行业ETF-8%; 宽基ETF波动最小纪律最严-6%; 海外ETF含汇率风险-8%。审计红线取各Regime中最宽松的止损值作为最后防线。",
            "threshold": "🟢 0只违规: 纪律严格 | 🟡 1只: 立即处理 | 🔴 ≥2只: 止损纪律崩溃",
            "action": f"立即卖出突破止损线的持仓" if breach_count > 0 else "继续保持四类差异化止损纪律",
        })

        # ── 检查 3: 行业集中度 (阈值从AUDIT_CFG) ──
        SECTOR_LIMIT = AUDIT_CFG.get("sector_limit", 40.0)
        sector_weights = {}

        if risk_metrics and isinstance(risk_metrics, dict) and "industry_exposure" in risk_metrics:
            for ie in risk_metrics["industry_exposure"]:
                sector_weights[ie["name"]] = ie["value"]
        else:
            for p in pos_list:
                ind = p.get("industry", "未知")
                w = p.get("weight", 0)
                if w <= 0:
                    w = p.get("market_value", 0) / max(total_asset, 1) * 100
                sector_weights[ind] = sector_weights.get(ind, 0) + w

        if sector_weights:
            top_sector = max(sector_weights, key=sector_weights.get)
            top_pct = sector_weights[top_sector]
            sector_violations = {k: v for k, v in sector_weights.items() if v > SECTOR_LIMIT}

            s = 100 if top_pct <= SECTOR_LIMIT else (70 if top_pct <= 60 else 40)
            scores.append(s)
            checks.append({
                "name": "行业集中度",
                "status": "pass" if not sector_violations else ("warn" if top_pct <= 60 else "fail"),
                "detail": f"最大行业: {top_sector} ({top_pct:.1f}%)",
                "meta": f"{'、'.join(f'{k}({v:.0f}%)' for k,v in sector_violations.items())} 超过{int(SECTOR_LIMIT)}%上限" if sector_violations else f"全部达标 · {len(sector_weights)}个行业",
                "score": s,
                "explanation": f"单一行业敞口超过{int(SECTOR_LIMIT)}%意味着行业Beta风险集中。行业性政策打压会导致同行业持仓同步暴跌。分散行业是对冲系统性风险的核心手段。",
                "threshold": f"🟢 ≤{int(SECTOR_LIMIT)}%: 行业分散达标 | 🟡 {int(SECTOR_LIMIT)+1}-60%: 偏集中 | 🔴 >60%: 行业风险过大",
                "action": "增配不同行业标的，降低单一行业敞口至40%以下",
            })

        # ── 检查 4: 持仓分散度 (阈值从AUDIT_CFG) ──
        MIN_HOLDINGS = AUDIT_CFG.get("min_holdings", 5)
        n_holdings = len(pos_list)
        if n_holdings >= MIN_HOLDINGS:
            s = 100
            status = "pass"
        elif n_holdings >= 3:
            s = 70
            status = "warn"
        else:
            s = 40
            status = "fail" if n_holdings < 2 else "warn"

        scores.append(s)
        checks.append({
            "name": "持仓分散度",
            "status": status,
            "detail": f"当前持有 {n_holdings} 只标的",
            "meta": f"建议 ≥{MIN_HOLDINGS} 只以分散非系统性风险",
            "score": s,
            "explanation": f"现代组合理论证明，持有5-15只低相关性标的可消除约80%的非系统性风险。持仓<3只时，任一个股爆雷对组合冲击可达30%以上。",
            "threshold": f"🟢 ≥{MIN_HOLDINGS}只: 充分分散 | 🟡 3-4只: 集中但可接受 | 🔴 <3只: 风险过高",
            "action": f"增加持仓标的至{MIN_HOLDINGS}只以上，优先选择不同行业、不同风格的ETF",
        })

    # ── 检查 5: 总仓位水平 ──
    if total_asset > 0:
        POS_CAP = AUDIT_CFG.get("total_position_cap", 95.0)
        # V28.0: 使用 get_valuation() 返回的权威 market_value (导入当日=券商参考市值)
        # 避免逐笔累加 positions[].market_value 在 broker_market_value=0 时偏高
        def _is_repo(code: str, name: str) -> bool:
            prefix = code.split('.')[0]
            if prefix.startswith('131') or prefix.startswith('204'):
                return True
            return '逆回购' in name or bool(re.search(r'GC\d', name))

        repo_mv = sum(
            p.get("market_value", 0)
            for p in pos_list
            if _is_repo(p.get("ts_code", ""), p.get("name", ""))
        )
        equity_mv = (ref_market_value or 0) - repo_mv
        pos_pct = equity_mv / max(total_asset, 1) * 100
        s = 100 if pos_pct <= POS_CAP else max(40, 100 - int((pos_pct - POS_CAP) * 5))
        scores.append(s)
        checks.append({
            "name": "总仓位水平",
            "status": "pass" if pos_pct <= POS_CAP else ("warn" if pos_pct <= 98 else "fail"),
            "detail": f"当前仓位: {pos_pct:.1f}%",
            "meta": f"上限 {int(POS_CAP)}% (Regime自适应) · [{data_source}]",
            "score": s,
            "explanation": f"总仓位上限{int(POS_CAP)}%是为了防止追保风险，并留足调仓空间。满仓意味着无法逢低吸纳新机会，且遇到系统性下跌时无现金缓冲。仓位计算基于持仓市值/总资产，已排除国债逆回购。",
            "threshold": f"🟢 ≤{int(POS_CAP)}%: 合规 | 🟡 {int(POS_CAP)+1}-98%: 偏重，调仓空间不足 | 🔴 >98%: 必须立即减仓",
            "action": f"卖出部分持仓降低总仓位至{int(POS_CAP)}%以下，优先卖出非核心持仓",
        })

    # ── 检查 6: AIAE 仓位约束对齐 (V6.0) ──
    if total_asset > 0:
        try:
            from services.cache_service import cache_manager
            aiae_ctx = cache_manager.get_json("aiae_ctx")
            if aiae_ctx and aiae_ctx.get("cap"):
                aiae_cap = float(aiae_ctx["cap"])
                # 复用检查5已计算的 pos_pct (持仓市值/总资产, 已排除逆回购)
                aiae_regime = aiae_ctx.get("regime", "?")
                aiae_regime_cn = {1: "极度恐慌", 2: "低配置区", 3: "中性均衡", 4: "偏热区域", 5: "极度过热"}.get(aiae_regime, f"R{aiae_regime}")
                buffer_cap = aiae_cap * 1.10  # 允许 10% 缓冲
                if pos_pct > buffer_cap:
                    s = max(40, 100 - int((pos_pct - aiae_cap) * 3))
                    scores.append(s)
                    checks.append({
                        "name": "AIAE 仓位约束",
                        "status": "warn",
                        "detail": f"当前仓位 {pos_pct:.1f}% 超过 AIAE 建议上限 {aiae_cap:.0f}% (×110%={buffer_cap:.0f}%)",
                        "meta": f"AIAE 档位: {aiae_regime_cn} · 建议上限: {aiae_cap:.0f}%",
                        "score": s,
                        "explanation": f"AIAE 宏观择时系统建议当前总仓位不超过 {aiae_cap:.0f}%。实际仓位超过该建议的110%缓冲线，说明仓位与宏观信号存在偏差。这不是强制阻断，而是提醒您关注宏观配置热度。",
                        "threshold": f"🟢 ≤{aiae_cap:.0f}%: 与AIAE一致 | 🟡 {aiae_cap:.0f}-{buffer_cap:.0f}%: 缓冲区 | 🔴 >{buffer_cap:.0f}%: 偏差过大",
                        "action": f"考虑将总仓位调整至 AIAE 建议的 {aiae_cap:.0f}% 以内",
                    })
                else:
                    scores.append(100)
                    checks.append({
                        "name": "AIAE 仓位约束",
                        "status": "pass",
                        "detail": f"当前仓位 {pos_pct:.1f}% 在 AIAE 建议上限 {aiae_cap:.0f}% 以内",
                        "meta": f"AIAE 档位: {aiae_regime_cn} · 建议上限: {aiae_cap:.0f}%",
                        "score": 100,
                        "explanation": "当前实际仓位与 AIAE 宏观择时建议保持一致，宏观配置纪律良好。",
                        "threshold": f"🟢 ≤{aiae_cap:.0f}%: 与AIAE一致",
                        "action": "继续保持与 AIAE 信号同步的仓位纪律",
                    })
        except Exception:
            pass  # 缓存不可用时静默跳过

    # ── 检查 6: 历史最大回撤 ──
    mr_fp = os.path.join(PROJECT_ROOT, "mr_optimization_results.json")
    if os.path.exists(mr_fp):
        try:
            # 引入对参数文件时效性的校验以处罚过期数据
            mtime = os.path.getmtime(mr_fp)
            opt_at_str, _, _ = _extract_optimize_meta(mr_fp, "均值回归")
            age_days, _, _ = _optimized_age_days(opt_at_str, mtime)
            is_stale = age_days > 30

            with open(mr_fp, "r", encoding="utf-8") as f:
                mr = json.load(f)
            max_dd = mr.get("max_drawdown", mr.get("validation", {}).get("max_drawdown", None))
            if max_dd is not None:
                max_dd = abs(float(max_dd))
                s = 100 if max_dd < 5 else (80 if max_dd < 10 else (60 if max_dd < 20 else 30))
                
                # 机构级时效关联处罚：若回撤数据源参数文件已过期，得分封顶 80 分，且强制不能为 pass
                if is_stale:
                    s = min(s, 80)
                    status = "warn"
                else:
                    status = "pass" if max_dd < 10 else ("warn" if max_dd < 20 else "fail")

                scores.append(s)
                meta_str = "来源: mr_optimization_results.json"
                if is_stale:
                    meta_str += f" (文件过期 {int(age_days)}天，数据时效性存疑封顶80分)"

                checks.append({
                    "name": "历史最大回撤",
                    "status": status,
                    "detail": f"回测最大回撤: -{max_dd:.2f}%",
                    "meta": meta_str,
                    "score": s,
                    "explanation": "最大回撤是策略风险的终极指标。超过20%可能触发客户赎回潮。专业基金通常将回撤控制在<10%。",
                    "threshold": "🟢 <10%: 优秀 | 🟡 10-20%: 可接受但需关注 | 🔴 >20%: 必须重新审视策略",
                    "action": "检查回撤期间的市场环境，考虑添加最大回撤硬约束或优化参数" if not is_stale else "重新执行均值回归参数优化以刷新最大回撤指标",
                })
        except:
            pass

    # ── V22.0: 合规引擎就绪 (独立 try/except, 拓宽异常隔离) ──
    try:
        from engines.compliance_engine import COMPLIANCE_RULES
        rule_count = len(COMPLIANCE_RULES)
        scores.append(100 if rule_count >= 5 else 80)
        checks.append({
            "name": "V22.0 合规引擎",
            "status": "pass",
            "detail": f"{rule_count} 条合规规则就绪 · 含硬阻断+软警告+提示三级",
            "score": 100,
            "explanation": "合规引擎在每次交易决策输出前执行6条规则检查：单票上限20%、板块集中度40%、AIAE过热限制、JCS门槛、VIX紧急刹车、最低分散持仓。硬阻断会禁止违规操作执行。",
            "threshold": "🟢 ≥5规则就绪 | 🔴 引擎阻断",
        })
    except ImportError:
        scores.append(50)
        checks.append({
            "name": "V22.0 合规引擎",
            "status": "warn",
            "detail": "合规引擎未加载, 预交易合规检查不可用",
            "score": 50,
            "explanation": "合规引擎是 V22.0 的核心升级——从展示风控到执行风控。离线时交易决策不受硬阻断保护。",
            "threshold": "🟢 就绪 | 🔴 缺失",
            "action": "检查 engines/compliance_engine.py 文件完整性",
        })
    except Exception as e:
        logger.error("Audit: 加载合规引擎崩溃 (排除ImportError外的其它RuntimeError): %s", e)
        scores.append(40)
        checks.append({
            "name": "V22.0 合规引擎",
            "status": "fail",
            "detail": f"合规引擎损坏 ({type(e).__name__})",
            "score": 40,
            "explanation": "合规引擎文件虽存在，但内部存在语法错误或运行时初始化崩溃，导致合规校验完全瘫痪。",
            "threshold": "🟢 就绪 | 🔴 损坏",
            "action": "立即排查 engines/compliance_engine.py 的语法与逻辑错误",
        })

    final_score = int(np.mean(scores)) if scores else 0

    # ── V6.4 生产级风控致命指标硬红线联锁 (Risk Interlocking) ──
    # 止损合规是资产安全底线，单票集中度是极端非系统性风险防线。
    # 任意一项若处于 FAIL 状态 (得分 < 60)，说明投资组合的合规风控纪律彻底崩溃。
    # 此时，即使其他分散性指标得满分，风控合规总评也必须一票否决，强制压制在不及格线 (59分) 以下。
    sc_score = next((c["score"] for c in checks if "持仓集中度" in c["name"]), 100)
    sl_score = next((c["score"] for c in checks if "止损合规" in c["name"]), 100)
    if sc_score < 60 or sl_score < 60:
        if final_score >= 60:
            final_score = 59

    return {
        "module": "risk_control",
        "label": "🛡️ 风控合规",
        "score": final_score,
        "grade": _grade(final_score),
        "checks": checks,
    }


# ═══════════════════════════════════════════════════════
#  模块 4: 因子衰减审计 (轻量版 — 基于文件元数据)
# ═══════════════════════════════════════════════════════
def audit_factor_decay():
    """
    轻量审计: 检查因子分析相关文件的可用性
    深度审计需要调用 /api/v1/factor-analysis, 由前端按需触发
    """
    checks = []
    scores = []

    # 检查因子分析器是否可导入
    try:
        from engines.factor_analyzer import FactorAnalyzer
        fa = FactorAnalyzer()
        scores.append(100)
        checks.append({
            "name": "因子引擎可用性",
            "status": "pass",
            "detail": "FactorAnalyzer 模块加载正常",
            "score": 100,
            "explanation": "FactorAnalyzer 是多因子体系的核心计算引擎，负责 IC 值计算、因子排名、衰减分析等。无法加载意味着整个因子分析模块睢痪。",
            "threshold": "🟢 可加载: 因子分析可用 | 🔴 导入失败: 因子分析瘫痪",
            "action": "检查 factor_analyzer.py 是否存在且依赖库完整",
        })
    except Exception as e:
        scores.append(0)
        checks.append({
            "name": "因子引擎可用性",
            "status": "fail",
            "detail": f"导入失败: {str(e)[:60]}",
            "score": 0,
            "explanation": "FactorAnalyzer 无法加载，可能是 Python 文件缺失或依赖库未安装。整个因子分析页面将无法使用。",
            "threshold": "🟢 可加载 | 🔴 导入失败",
            "action": "确认 factor_analyzer.py 存在并检查 pip install requirements.txt",
        })

    # 检查因子需要的数据是否存在
    daily_count = len(glob.glob(os.path.join(DAILY_DIR, "*.parquet")))
    fina_count = len(glob.glob(os.path.join(FINA_DIR, "*.parquet")))

    s = 100 if daily_count >= 30 and fina_count >= 10 else (60 if daily_count >= 10 else 20)
    scores.append(s)
    checks.append({
        "name": "因子数据覆盖",
        "status": "pass" if s >= 80 else ("warn" if s >= 50 else "fail"),
        "detail": f"日线: {daily_count}只, 财务: {fina_count}只",
        "meta": "建议: 日线≥30只, 财务≥10只",
        "score": s,
        "explanation": "因子分析需要足够的样本覆盖才能产生统计显著的结果。日线<30只时因子排名不稳定，财务<10只时基本面因子暂光不充分。",
        "threshold": "🟢 日线≥30+财务≥10: 充分覆盖 | 🟡 日线≥10: 勉强可用 | 🔴 <10: 结果不可靠",
        "action": "执行 python data_manager.py 扩大样本池",
    })

    # V8.0: 因子可用性真实验证 (双通道随机抽样 + NaN 穿透校验)
    factor_types = {
        "基本面": ["roe", "eps", "netprofit_margin", "bps", "debt_to_assets"],
        "技术面": ["momentum_20d", "volatility_20d", "turnover_rate"],
    }
    total_factors = sum(len(v) for v in factor_types.values())

    # 1. 基本面财务数据验证
    fina_files = glob.glob(os.path.join(FINA_DIR, "*.parquet"))
    fina_ok_ratio = 0.0
    fina_checks_run = 0
    if fina_files:
        sampled_fina = random.sample(fina_files, min(len(fina_files), 3))
        for f in sampled_fina:
            try:
                df = pd.read_parquet(f)
                required_cols = {"roe", "eps", "bps"}
                found_cols = required_cols.intersection(set(df.columns))
                if len(found_cols) >= 2:
                    non_nan_sum = 0
                    for col in found_cols:
                        total_cnt = len(df)
                        non_nan_sum += df[col].notna().sum() / max(total_cnt, 1)
                    avg_non_nan = non_nan_sum / len(found_cols)
                    fina_ok_ratio += avg_non_nan
                fina_checks_run += 1
            except Exception:
                pass
    fina_score_ratio = fina_ok_ratio / max(fina_checks_run, 1)

    # 2. 技术面日线数据验证
    daily_files = glob.glob(os.path.join(DAILY_DIR, "*.parquet"))
    daily_ok_ratio = 0.0
    daily_checks_run = 0
    if daily_files:
        sampled_daily = random.sample(daily_files, min(len(daily_files), 3))
        for f in sampled_daily:
            try:
                df = pd.read_parquet(f)
                required_cols = {"vol", "close", "pct_chg"}
                found_cols = required_cols.intersection(set(df.columns))
                if len(found_cols) >= 2:
                    non_nan_sum = 0
                    for col in found_cols:
                        total_cnt = len(df)
                        non_nan_sum += df[col].notna().sum() / max(total_cnt, 1)
                    avg_non_nan = non_nan_sum / len(found_cols)
                    daily_ok_ratio += avg_non_nan
                daily_checks_run += 1
            except Exception:
                pass
    daily_score_ratio = daily_ok_ratio / max(daily_checks_run, 1)

    # 3. 计分逻辑
    fina_valid = (fina_score_ratio >= 0.50) if fina_checks_run > 0 else False
    daily_valid = (daily_score_ratio >= 0.90) if daily_checks_run > 0 else False

    if fina_valid and daily_valid:
        s = 95
        status = "pass"
        detail = f"基本面(可用率{fina_score_ratio*100:.0f}%) + 技术面(可用率{daily_score_ratio*100:.0f}%) 验证通过"
    elif fina_count >= 10 and daily_count >= 30:
        s = 60
        status = "warn"
        detail = f"因子定义就绪但数据不达标 [基本面可用率:{fina_score_ratio*100:.0f}%, 技术面可用率:{daily_score_ratio*100:.0f}%]"
    else:
        s = 30
        status = "fail"
        detail = "因子定义就绪 · 样本数据不足，无法完成基本验证"

    scores.append(s)
    checks.append({
        "name": "因子池可用性",
        "status": status,
        "detail": detail,
        "meta": f"随机抽检 {fina_checks_run}只财务 + {daily_checks_run}只日线Parquet",
        "score": s,
        "explanation": "多因子分析需要数据湖中不仅有字段列，还要求列中没有大面积空值(NaN)。基本面财务数据非空率须≥50%，技术面交易日线非空率须≥90%。",
        "threshold": "🟢 基本面≥50%+技术面≥90%: 因子高可用 | 🟡 字段存在但空值过多: 降级警告 | 🔴 字段缺失/文件破损",
        "action": "运行数据同步或重新计算技术面因子，填充 NaN 缺失值",
    })

    final_score = int(np.mean(scores)) if scores else 0
    return {
        "module": "factor_decay",
        "label": "📈 因子衰减",
        "score": final_score,
        "grade": _grade(final_score),
        "checks": checks,
        "deep_audit_available": True,
    }


# ═══════════════════════════════════════════════════════
#  模块 5: 系统状态审计
# ═══════════════════════════════════════════════════════
def audit_system_status():
    global _TS_CHECK_CACHE
    checks = []
    scores = []

    # ── 5.1 Tushare API 连通性 ──
    now_ts = time.time()
    use_cache = False
    if _TS_CHECK_CACHE is not None:
        cache_age = now_ts - _TS_CHECK_CACHE.get("timestamp", 0)
        if cache_age < 120:
            use_cache = True

    if use_cache:
        latency = _TS_CHECK_CACHE["latency"]
        s = _TS_CHECK_CACHE["score"]
        status = _TS_CHECK_CACHE["status"]
        detail = _TS_CHECK_CACHE["detail"]
        if " (缓存读取)" not in detail:
            detail += " (缓存读取)"
        scores.append(s)
        checks.append({
            "name": "Tushare API",
            "status": status,
            "detail": detail,
            "score": s,
            "explanation": _TS_CHECK_CACHE.get("explanation", ""),
            "threshold": _TS_CHECK_CACHE.get("threshold", ""),
            "action": _TS_CHECK_CACHE.get("action", ""),
        })
    else:
        import requests
        original_post = requests.post
        try:
            def timeout_patched_post(url, **kwargs):
                kwargs['timeout'] = 2.5
                if 'api.waditu.com' in url or 'api.tushare.pro' in url:
                    url = 'http://api.tushare.pro'
                    try:
                        from services.tushare_limiter import tushare_limiter
                        tushare_limiter.acquire()
                    except Exception:
                        pass
                return original_post(url, **kwargs)
                
            requests.post = timeout_patched_post
            
            import tushare as ts
            pro = ts.pro_api()
            t0 = time.time()
            cal = pro.trade_cal(exchange='SSE', start_date='20260101', end_date='20260110')
            latency = (time.time() - t0) * 1000
            s = 100 if latency < 2000 else (70 if latency < 5000 else 40)
            status = "pass" if latency < 3000 else "warn"
            detail = f"连通 · 延迟 {latency:.0f}ms"
            explanation = "Tushare 是全部A股数据的入口，提供日线、财务、交易日历等。API离线意味着所有数据同步停止，系统将逐渐依赖过期缓存。延迟>3秒可能是网络问题或 API 配额耗尽。"
            threshold = "🟢 <2秒: 正常 | 🟡 2-5秒: 偏慢 | 🔴 >5秒/连接失败: 系统瘫痪"
            action = "检查网络连接和 Tushare Token 是否过期"
            
            scores.append(s)
            checks.append({
                "name": "Tushare API",
                "status": status,
                "detail": detail,
                "score": s,
                "explanation": explanation,
                "threshold": threshold,
                "action": action,
            })
            
            _TS_CHECK_CACHE = {
                "timestamp": now_ts,
                "latency": latency,
                "score": s,
                "status": status,
                "detail": detail,
                "explanation": explanation,
                "threshold": threshold,
                "action": action,
            }
        except Exception as e:
            s = 0
            status = "fail"
            detail = f"连接失败: {str(e)[:50]}"
            explanation = "Tushare API 无法连接，所有数据同步停止。可能是网络问题、Token 过期或 Tushare 服务器维护。"
            threshold = "🟢 <2秒 | 🟡 2-5秒 | 🔴 连接失败"
            action = "检查网络 + config.py 中的 Tushare Token"
            
            scores.append(s)
            checks.append({
                "name": "Tushare API",
                "status": status,
                "detail": detail,
                "score": s,
                "explanation": explanation,
                "threshold": threshold,
                "action": action,
            })
            
            _TS_CHECK_CACHE = {
                "timestamp": now_ts,
                "latency": 999999.0,
                "score": s,
                "status": status,
                "detail": detail,
                "explanation": explanation,
                "threshold": threshold,
                "action": action,
            }
        finally:
            requests.post = original_post

    # ── 5.2 数据湖统计 ──
    total_files = 0
    total_size = 0
    for root, dirs, files in os.walk(DATA_LAKE):
        for f in files:
            fp = os.path.join(root, f)
            total_files += 1
            total_size += os.path.getsize(fp)

    size_mb = total_size / (1024 * 1024)
    s = 100 if total_files >= 50 else (70 if total_files >= 20 else 40)
    scores.append(s)
    checks.append({
        "name": "数据湖容量",
        "status": "pass" if total_files >= 30 else "warn",
        "detail": f"{total_files} 个文件 · {size_mb:.1f} MB",
        "score": s,
        "explanation": "数据湖存储所有日线、财务、ERP、利率等原始数据。文件数反映数据覆盖面，容量反映历史深度。<20个文件说明初始化不完全。",
        "threshold": "🟢 ≥50个: 充分覆盖 | 🟡 20-49个: 基本可用 | 🔴 <20个: 初始化不完全",
        "action": "执行 python data_manager.py 扩大数据湖覆盖范围",
    })

    # ── 5.3 关键 Python 模块 ──
    required_modules = [
        ("pandas", "pd"),
        ("numpy", "np"),
        ("tushare", "ts"),
    ]
    missing = []
    for mod_name, _ in required_modules:
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(mod_name)

    s = 100 if not missing else max(0, 100 - len(missing) * 30)
    scores.append(s)
    checks.append({
        "name": "依赖库完整性",
        "status": "pass" if not missing else "fail",
        "detail": "全部就绪" if not missing else f"缺失: {', '.join(missing)}",
        "score": s,
        "explanation": "pandas/numpy/tushare 是核心计算引擎的基础依赖。任一缺失都会导致策略引擎、因子分析、数据同步等核心功能无法运行。",
        "threshold": "🟢 全部就绪: 系统正常 | 🔴 有缺失: 必须安装",
        "action": "执行 pip install -r requirements.txt 补全依赖",
    })

    # ── 5.4 ECharts 前端资源 ──
    echarts_path = os.path.join(PROJECT_ROOT, "static", "vendor", "echarts.min.js")
    if os.path.exists(echarts_path):
        esize = os.path.getsize(echarts_path) / 1024
        scores.append(100)
        checks.append({
            "name": "ECharts 引擎",
            "status": "pass",
            "detail": f"就绪 ({esize:.0f} KB)",
            "score": 100,
            "explanation": "ECharts 是前端图表渲染引擎，驱动仪表盘、雷达图、K线等所有可视化。缺失将导致全部图表无法渲染。",
            "threshold": "🟢 文件存在: 可视化正常 | 🔴 缺失: 图表全部睢痪",
            "action": "从 CDN 下载 echarts.min.js 放置于项目根目录",
        })
    else:
        scores.append(30)
        checks.append({"name": "ECharts 引擎", "status": "fail", "detail": "文件不存在", "score": 30, "explanation": "ECharts 文件缺失，全部图表将无法渲染。", "threshold": "🟢 存在 | 🔴 缺失", "action": "从 CDN 下载 echarts.min.js"})

    # ── 5.5 服务器运行检测 ──
    scores.append(100)
    checks.append({
        "name": "服务进程",
        "status": "pass",
        "detail": f"运行中 · 审计时间 {datetime.now().strftime('%H:%M:%S')}",
        "score": 100,
        "explanation": "后端服务进程存活 = API 可达，所有前端页面可正常加载数据。若服务崩溃则整个 Dashboard 无法使用。",
        "threshold": "🟢 运行中: 系统正常 | 🔴 崩溃: 无法访问",
        "action": "运行 python main.py 或双击 启动服务器.bat",
    })

    # ── V22.0: 新模块就绪检查 ──
    v22_modules = [
        ("compliance_engine", "预交易合规引擎"),
        ("drift_monitor", "策略漂移监控"),
    ]
    for mod_name, mod_label in v22_modules:
        try:
            __import__(f"engines.{mod_name}")
            scores.append(100)
            checks.append({
                "name": f"V22.0 {mod_label}",
                "status": "pass",
                "detail": f"模块 {mod_name} 就绪",
                "score": 100,
                "explanation": f"{mod_label}是 V22.0 新增的生产级风控模块。离线不影响核心数据流，但会失去预交易合规检查和策略漂移预警能力。",
                "threshold": "🟢 就绪: 正常 | 🔴 缺失: 失去风控增强",
            })
        except ImportError:
            scores.append(60)
            checks.append({
                "name": f"V22.0 {mod_label}",
                "status": "warn",
                "detail": f"模块 {mod_name} 未加载",
                "score": 60,
                "explanation": f"{mod_label}未正确加载。请检查 engines/{mod_name}.py 文件是否存在。",
                "threshold": "🟢 就绪 | 🔴 缺失",
                "action": f"检查 engines/{mod_name}.py 文件完整性",
            })

    # ── V22.0: 事件日志文件 ── (os already imported at module level)
    event_log = os.path.join(DATA_LAKE, "market_events.json")
    snapshot_file = os.path.join(DATA_LAKE, "event_last_snapshot.json")
    for fpath, fname in [(event_log, "市场事件日志"), (snapshot_file, "事件快照")]:
        if os.path.exists(fpath):
            try:
                size = os.path.getsize(fpath)
                scores.append(100)
                checks.append({
                    "name": f"V22.0 {fname}",
                    "status": "pass",
                    "detail": f"{fname} 就绪 ({size} bytes)",
                    "score": 100,
                    "explanation": f"{fname}是 V22.0 动态事件驱动引擎的持久化文件。",
                    "threshold": "🟢 就绪 | 🔴 缺失",
                })
            except Exception:
                pass

    final_score = int(np.mean(scores)) if scores else 0
    return {
        "module": "system_status",
        "label": "🖥️ 系统状态",
        "score": final_score,
        "grade": _grade(final_score),
        "checks": checks,
    }


# ═══════════════════════════════════════════════════════
#  综合审计入口 V4.0 — 带枪保安架构
# ═══════════════════════════════════════════════════════
def _apply_mute(modules):
    """
    V4.0: 应用静音/降级策略。
    - muted_checks: 被静音的检查项直接标记为 "muted"
    - degraded_mode: 所有 fail → warn (不触发 enforcer)
    """
    try:
        from audit_enforcer import _load_mute_config
        mute_cfg = _load_mute_config()
    except ImportError:
        return modules

    muted_checks = mute_cfg.get("muted_checks", [])
    degraded = mute_cfg.get("degraded_mode", False)

    if not muted_checks and not degraded:
        return modules

    for mod in modules.values():
        for c in mod.get("checks", []):
            # 静音指定检查项
            if c.get("name") in muted_checks:
                c["original_status"] = c["status"]
                c["status"] = "muted"
            # 降级模式: fail → warn
            elif degraded and c.get("status") == "fail":
                c["original_status"] = "fail"
                c["status"] = "warn"
                c["detail"] = f"[降级] {c.get('detail', '')}"

    return modules


def run_full_audit():
    """
    V4.0 五维全量审计 + Enforcer 执行 + 静音/降级
    """
    start = time.time()

    modules = {}
    try:
        modules["data_quality"] = audit_data_quality()
    except Exception as e:
        modules["data_quality"] = {"module": "data_quality", "label": "📡 数据质量", "score": 0, "grade": "D", "checks": [{"name": "执行异常", "status": "fail", "detail": str(e)[:100], "score": 0}]}

    try:
        modules["strategy_health"] = audit_strategy_health()
    except Exception as e:
        modules["strategy_health"] = {"module": "strategy_health", "label": "⚙️ 策略健康", "score": 0, "grade": "D", "checks": [{"name": "执行异常", "status": "fail", "detail": str(e)[:100], "score": 0}]}

    try:
        modules["risk_control"] = audit_risk_control()
    except Exception as e:
        modules["risk_control"] = {"module": "risk_control", "label": "🛡️ 风控合规", "score": 0, "grade": "D", "checks": [{"name": "执行异常", "status": "fail", "detail": str(e)[:100], "score": 0}]}

    try:
        modules["factor_decay"] = audit_factor_decay()
    except Exception as e:
        modules["factor_decay"] = {"module": "factor_decay", "label": "📈 因子衰减", "score": 0, "grade": "D", "checks": [{"name": "执行异常", "status": "fail", "detail": str(e)[:100], "score": 0}]}

    try:
        modules["system_status"] = audit_system_status()
    except Exception as e:
        modules["system_status"] = {"module": "system_status", "label": "🖥️ 系统状态", "score": 0, "grade": "D", "checks": [{"name": "执行异常", "status": "fail", "detail": str(e)[:100], "score": 0}]}

    # V4.0: 应用静音/降级策略
    modules = _apply_mute(modules)

    # 加权计算综合可信度
    trust_score = sum(
        modules[k]["score"] * WEIGHTS[k]
        for k in WEIGHTS
        if k in modules
    )
    trust_score = int(trust_score)

    # 统计问题数 (静音项不计入)
    total_checks = sum(len(m.get("checks", [])) for m in modules.values())
    fail_count = sum(
        1 for m in modules.values()
        for c in m.get("checks", [])
        if c.get("status") == "fail"
    )
    warn_count = sum(
        1 for m in modules.values()
        for c in m.get("checks", [])
        if c.get("status") == "warn"
    )
    muted_count = sum(
        1 for m in modules.values()
        for c in m.get("checks", [])
        if c.get("status") == "muted"
    )

    elapsed_audit = time.time() - start

    # ── V4.0: Enforcer 执行 ──
    enforcement_result = None
    try:
        from audit_enforcer import run_post_audit_enforcement
        report_for_enforcer = {
            "modules": modules,
            "trust_score": trust_score,
        }
        enforcement_result = run_post_audit_enforcement(report_for_enforcer)
    except Exception as e:
        print(f"[Audit V4.0] Enforcer 执行异常: {e}")
        enforcement_result = {
            "enforcer_enabled": False,
            "actions": [],
            "trade_blocked": False,
            "trade_block_reason": "",
            "mute_status": {"degraded_mode": False, "muted_checks": [], "mute_until": None, "is_muted": False},
            "error": str(e)[:100],
        }

    elapsed_total = time.time() - start
    audit_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = {
        "trust_score": trust_score,
        "trust_grade": _grade(trust_score),
        "total_checks": total_checks,
        "pass_count": total_checks - fail_count - warn_count - muted_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "muted_count": muted_count,
        "modules": modules,
        "weights": WEIGHTS,
        "audit_time": audit_time_str,
        "elapsed_seconds": round(elapsed_total, 2),
        "enforcement": enforcement_result,
        "version": "V22.0",
    }

    # V22.0: 服务端持久化 (非阻塞, 异常不影响审计结果)
    try:
        from services.db import save_audit_log
        save_audit_log(report)
    except Exception:
        pass  # 持久化失败不影响审计报告返回

    return report


if __name__ == "__main__":
    report = run_full_audit()
    print(f"\n{'='*50}")
    print(f"  AlphaCore 系统可信度: {report['trust_score']}/100 ({report['trust_grade']}级)")
    print(f"  通过: {report['pass_count']}  警告: {report['warn_count']}  失败: {report['fail_count']}  静音: {report.get('muted_count', 0)}")
    print(f"  耗时: {report['elapsed_seconds']}s")
    enf = report.get('enforcement', {})
    if enf:
        print(f"  执行器: {'启用' if enf.get('enforcer_enabled') else '禁用'} · 动作: {len(enf.get('actions', []))} · 阻断: {'是' if enf.get('trade_blocked') else '否'}")
    print(f"{'='*50}")
    for key, mod in report["modules"].items():
        print(f"\n  {mod['label']}: {mod['score']}/100 ({mod['grade']})")
        for c in mod["checks"]:
            icon = "✅" if c["status"] == "pass" else ("⚠️" if c["status"] == "warn" else ("🔇" if c["status"] == "muted" else "❌"))
            print(f"    {icon} {c['name']}: {c.get('detail', '')}")
