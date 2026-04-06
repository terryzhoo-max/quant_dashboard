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
import traceback
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── 路径常量 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_LAKE = os.path.join(BASE_DIR, "data_lake")
DAILY_DIR = os.path.join(DATA_LAKE, "daily_prices")
FINA_DIR = os.path.join(DATA_LAKE, "financials")

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
            "stop_loss_stock": -10.0, "stop_loss_etf": -8.0,
            "single_position_limit": 20.0,
            "sector_limit": 40.0, "total_position_cap": 90.0,
            "min_holdings": 5, "daily_stale_warn_days": 3,
            "daily_stale_fail_days": 5, "fina_fresh_days": 90,
            "erp_stale_warn_days": 3, "erp_stale_fail_days": 7,
            "strategy_fresh_days": 30, "strategy_stale_days": 60,
        }

# V5.0: 模块加载时立即读取配置 (全局单例)
AUDIT_CFG = _load_audit_cfg()


def _today_str():
    return datetime.now().strftime("%Y%m%d")


# V5.0: 中国法定假日列表 (每年初更新)
_CN_HOLIDAYS_2026 = {
    (1,1),(1,2),(1,3),           # 元旦
    (1,26),(1,27),(1,28),(1,29),(1,30),(1,31),(2,1),  # 春节
    (4,4),(4,5),(4,6),           # 清明
    (5,1),(5,2),(5,3),(5,4),(5,5),  # 劳动节
    (5,31),(6,1),(6,2),          # 端午
    (9,25),(9,26),(9,27),        # 中秋
    (10,1),(10,2),(10,3),(10,4),(10,5),(10,6),(10,7),  # 国庆
}

def _is_trading_day(dt):
    """V5.0: 排除周末 + 中国法定假日"""
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
    """计算距今天数 (date_str 格式: YYYYMMDD 或 YYYY-MM-DD)"""
    try:
        clean = str(date_str).replace("-", "")[:8]
        dt = datetime.strptime(clean, "%Y%m%d")
        return (datetime.now() - dt).days
    except:
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
        for f in daily_files[:30]:  # 抽样前30只
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
        for f in fina_files[:10]:
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
    erp_files = glob.glob(os.path.join(DATA_LAKE, "erp_*.parquet"))
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
            "detail": f"最旧缓存: {max_age:.1f} 天前",
            "meta": f"共 {len(erp_files)} 个 ERP 数据文件",
            "score": s,
            "explanation": "ERP(股权风险溢价)是股债性价比的核心指标，由全市场PE和10年国债收益率计算。过期数据会导致宏观择时引擎的仓位建议失准，可能在高估值时重仓或低估值时空仓。",
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
        status = "pass" if max_age <= 3 else ("warn" if max_age <= 7 else "fail")
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

    # ── 1.5 数据完整性抽检 ──
    if daily_files:
        sample_file = daily_files[0]
        try:
            df = pd.read_parquet(sample_file)
            total_rows = len(df)
            zero_vol = (df["vol"] == 0).sum() if "vol" in df.columns else 0
            anomaly_pct = zero_vol / max(total_rows, 1) * 100
            s = max(0, 100 - int(anomaly_pct * 10))
            status = "pass" if anomaly_pct < 1 else ("warn" if anomaly_pct < 5 else "fail")
            scores.append(s)
            checks.append({
                "name": "数据完整性 (抽检)",
                "status": status,
                "detail": f"零成交天数: {zero_vol}/{total_rows} ({anomaly_pct:.1f}%)",
                "meta": f"样本: {os.path.basename(sample_file)}",
                "score": s,
                "explanation": "零成交日(停牌/涨跌停封板)会导致均值回归的偏离度计算失真、动量排名被污染。占比过高说明样本池可能包含退市股或长期停牌股，需清理。",
                "threshold": "🟢 <1%: 数据干净 | 🟡 1-5%: 少量噪声可接受 | 🔴 >5%: 需清理样本池",
                "action": "检查 data_lake/daily_prices/ 中的异常标的并清除长期停牌股",
            })
        except:
            scores.append(70)
            checks.append({"name": "数据完整性 (抽检)", "status": "warn", "detail": "抽检异常", "score": 70, "explanation": "数据文件存在但读取失败，可能是文件损坏或格式异常。", "threshold": "🟢 <1% | 🟡 1-5% | 🔴 >5%/读取失败", "action": "删除损坏文件后重新同步"})

    final_score = int(np.mean(scores)) if scores else 0
    return {
        "module": "data_quality",
        "label": "📡 数据质量",
        "score": final_score,
        "grade": _grade(final_score),
        "checks": checks,
    }


# ═══════════════════════════════════════════════════════
#  模块 2: 策略健康审计
# ═══════════════════════════════════════════════════════
def audit_strategy_health():
    checks = []
    scores = []

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
        fp = os.path.join(BASE_DIR, filename)
        if os.path.exists(fp):
            mtime = os.path.getmtime(fp)
            age_days = (time.time() - mtime) / 86400
            mod_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

            # 读取文件大小验证非空
            fsize = os.path.getsize(fp)
            if fsize < 50:
                scores.append(20)
                strategy_exp = STRATEGY_EXPLANATIONS.get(name, {})
                checks.append({
                    "name": f"{name} 参数文件",
                    "status": "fail",
                    "detail": f"文件异常 ({fsize} bytes)",
                    "score": 20,
                    "explanation": f"{name}参数文件损坏或为空，策略引擎将使用默认参数运行，实盘表现可能严重偏离回测结果。",
                    "threshold": "🟢 ≤30天: 参数有效 | 🟡 31-60天: 建议重新优化 | 🔴 >60天/损坏: 必须修复",
                    "action": strategy_exp.get("action", "重新执行参数优化器"),
                })
                continue

            if age_days <= 30:
                s = 100
                status = "pass"
            elif age_days <= 60:
                s = 70
                status = "warn"
            else:
                s = max(20, 100 - int(age_days))
                status = "fail"
            scores.append(s)
            strategy_exp = STRATEGY_EXPLANATIONS.get(name, {})
            checks.append({
                "name": f"{name}",
                "status": status,
                "detail": f"最后优化: {mod_date} ({int(age_days)}天前)",
                "meta": f"文件: {filename} ({fsize/1024:.1f}KB)",
                "score": s,
                "explanation": strategy_exp.get("explanation", f"{name}策略的核心参数文件，定期优化可确保策略与当前市场环境匹配。"),
                "threshold": "🟢 ≤30天: 参数新鲜 | 🟡 31-60天: 建议重优化 | 🔴 >60天: 策略可能失效",
                "action": strategy_exp.get("action", "执行对应策略的参数优化器"),
            })
        else:
            scores.append(0)
            strategy_exp = STRATEGY_EXPLANATIONS.get(name, {})
            checks.append({
                "name": f"{name}",
                "status": "fail",
                "detail": "参数文件不存在",
                "meta": f"期望: {filename}",
                "score": 0,
                "explanation": f"{name}参数文件缺失，该策略引擎无法运行。需先执行参数优化生成配置文件。",
                "threshold": "🟢 ≤30天 | 🟡 31-60天 | 🔴 文件缺失",
                "action": strategy_exp.get("action", "执行对应策略的参数优化器"),
            })

    # ── Regime 参数文件检查 ──
    regime_fp = os.path.join(BASE_DIR, "mr_per_regime_params.json")
    if os.path.exists(regime_fp):
        try:
            with open(regime_fp, "r", encoding="utf-8") as f:
                params = json.load(f)
            regime_count = len(params) if isinstance(params, (list, dict)) else 0
            s = 100 if regime_count >= 3 else 60
            scores.append(s)
            checks.append({
                "name": "Regime 三态参数",
                "status": "pass" if regime_count >= 3 else "warn",
                "detail": f"已配置 {regime_count} 套状态参数",
                "score": s,
                "explanation": "市场存在牛市/熊市/震荡三种状态(Regime)，每种状态的最优参数差异巨大。例如震荡市的均值回归初始偏离阈值应更低、牛市应更宽松。缺少任一状态的参数会导致在该状态下策略表现退化。",
                "threshold": "🟢 ≥3套: 全状态覆盖 | 🟡 1-2套: 部分状态缺失 | 🔴 0套: 必须配置",
                "action": "执行 python mr_per_regime_optimizer.py 生成三态参数",
            })
        except:
            scores.append(40)
            checks.append({"name": "Regime 三态参数", "status": "fail", "detail": "解析失败", "score": 40, "explanation": "Regime 参数文件损坏，均值回归引擎将退化为单状态模式。", "threshold": "🟢 ≥3套 | 🟡 1-2套 | 🔴 损坏", "action": "删除损坏文件后执行 python mr_per_regime_optimizer.py"})
    else:
        scores.append(30)
        checks.append({"name": "Regime 三态参数", "status": "fail", "detail": "文件不存在", "score": 30, "explanation": "无 Regime 参数意味着均值回归策略无法自适应市场状态切换，在牛熊转换时可能产生大量错误信号。", "threshold": "🟢 ≥3套 | 🟡 1-2套 | 🔴 文件缺失", "action": "执行 python mr_per_regime_optimizer.py 生成三态参数"})

    final_score = int(np.mean(scores)) if scores else 0
    return {
        "module": "strategy_health",
        "label": "⚙️ 策略健康",
        "score": final_score,
        "grade": _grade(final_score),
        "checks": checks,
    }


# ═══════════════════════════════════════════════════════
#  ETF 识别工具 (V5.1)
# ═══════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════
#  模块 3: 风控审计 V2.1 — 个股/ETF 差异化止损
# ═══════════════════════════════════════════════════════
#  V2.1 升级:
#    1. 止损差异化: 个股 -12% / ETF -8%
#    2. 总仓位上限从 85% 放宽至 90%
#    3. 使用 portfolio_engine 实时估值
#    4. 单票阈值统一为 20% (与 POSITION_LIMIT 一致)
#    5. 行业集中度 + 持仓分散度审计
# ═══════════════════════════════════════════════════════
def _get_live_portfolio():
    """
    尝试从 portfolio_engine 获取实时估值 (含真实价格/盈亏)。
    若引擎不可用，则降级为成本估算 (fallback)。
    返回: (pos_list, cash, total_asset, is_live, risk_metrics)
    """
    # ── 优先: 调用 portfolio_engine 单例 (真实价格) ──
    try:
        from portfolio_engine import get_portfolio_engine
        engine = get_portfolio_engine()
        val = engine.get_valuation()
        pos_list = val.get("positions", [])
        cash = val.get("cash", 0)
        total_asset = val.get("total_asset", 0)

        # 尝试获取风险指标 (行业敞口)
        risk_metrics = None
        try:
            risk_metrics = engine.calculate_risk_metrics()
            if isinstance(risk_metrics, dict) and risk_metrics.get("status") in ("empty", "insufficient_data", "zero_value"):
                risk_metrics = None
        except Exception:
            pass

        return pos_list, cash, total_asset, True, risk_metrics
    except Exception as e:
        print(f"[Audit] portfolio_engine 不可用, 降级为成本估算: {e}")

    # ── 降级: 从 JSON 手动解析 (成本估算) ──
    pf_path = os.path.join(BASE_DIR, "portfolio_store.json")
    if not os.path.exists(pf_path):
        return [], 0, 0, False, None
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
        return pos_list, cash, total_asset, False, None
    except Exception:
        return [], 0, 0, False, None


def audit_risk_control():
    checks = []
    scores = []

    # ── 获取实时组合数据 ──
    pos_list, cash, total_asset, is_live, risk_metrics = _get_live_portfolio()
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
            "name": "止损合规 (个股-12%/ETF-8%)",
            "status": "pass",
            "detail": "无持仓, 无需止损检查",
            "score": 100,
            "explanation": "差异化止损线: 个股-12%, ETF-8%。个股波动大容忍度更高, ETF波动小纪律更严。",
            "threshold": "🟢 0只违规 | 🟡 1只: 警告 | 🔴 ≥2只: 纪律崩溃",
            "action": "按差异化止损标准执行",
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

        # ── 检查 2: 止损合规 V2.1 (个股/ETF 差异化止损) ──
        SL_STOCK = AUDIT_CFG.get("stop_loss_stock", AUDIT_CFG.get("stop_loss_line", -10.0))
        SL_ETF = AUDIT_CFG.get("stop_loss_etf", -8.0)
        breach_list = []
        worst_loss = 0
        worst_name = ""

        for p in pos_list:
            pnl_pct = p.get("pnl_pct", 0)
            ts_code = p.get("ts_code", "")
            name = p.get("name", ts_code or "?")
            is_etf = _is_etf(ts_code)
            sl_line = SL_ETF if is_etf else SL_STOCK
            tag = "ETF" if is_etf else "个股"
            if pnl_pct < sl_line:
                breach_list.append(f"{name}[{tag}] ({pnl_pct:.1f}% < {sl_line}%)")
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

        checks.append({
            "name": f"止损合规 (个股{SL_STOCK}%/ETF{SL_ETF}%)",
            "status": "pass" if breach_count == 0 else "fail",
            "detail": detail,
            "meta": f"个股止损线: {SL_STOCK}% · ETF止损线: {SL_ETF}% · [{data_source}]" + (f" · 最大浮亏: {worst_loss:.1f}%" if worst_loss < 0 else ""),
            "score": s,
            "explanation": f"差异化止损: 个股波动大允许更宽容忍({SL_STOCK}%), ETF组合型产品波动小执行更严格纪律({SL_ETF}%)。统计显示突破止损线后继续下跌至-20%的概率超过60%。及时止损保护组合存活率。",
            "threshold": "🟢 0只违规: 纪律严格 | 🟡 1只: 立即处理 | 🔴 ≥2只: 止损纪律崩溃",
            "action": f"立即卖出突破止损线的持仓 (个股>{abs(SL_STOCK)}% / ETF>{abs(SL_ETF)}%)" if breach_count > 0 else "继续保持差异化止损纪律",
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
        POS_CAP = AUDIT_CFG.get("total_position_cap", 85.0)
        pos_pct = (1 - cash / max(total_asset, 1)) * 100
        s = 100 if pos_pct <= POS_CAP else max(40, 100 - int((pos_pct - POS_CAP) * 5))
        scores.append(s)
        checks.append({
            "name": "总仓位水平",
            "status": "pass" if pos_pct <= POS_CAP else ("warn" if pos_pct <= 95 else "fail"),
            "detail": f"当前仓位: {pos_pct:.1f}%",
            "meta": f"上限 {int(POS_CAP)}% (Regime自适应) · [{data_source}]",
            "score": s,
            "explanation": f"总仓位上限{int(POS_CAP)}%是为了防止追保风险，并留足调仓空间。满仓意味着无法逢低吸纳新机会，且遇到系统性下跌时无现金缓冲。",
            "threshold": f"🟢 ≤{int(POS_CAP)}%: 合规 | 🟡 {int(POS_CAP)+1}-95%: 偏重，调仓空间不足 | 🔴 >95%: 必须立即减仓",
            "action": f"卖出部分持仓降低总仓位至{int(POS_CAP)}%以下，优先卖出非核心持仓",
        })

    # ── 检查 6: 历史最大回撤 ──
    mr_fp = os.path.join(BASE_DIR, "mr_optimization_results.json")
    if os.path.exists(mr_fp):
        try:
            with open(mr_fp, "r", encoding="utf-8") as f:
                mr = json.load(f)
            max_dd = mr.get("max_drawdown", mr.get("validation", {}).get("max_drawdown", None))
            if max_dd is not None:
                max_dd = abs(float(max_dd))
                s = 100 if max_dd < 5 else (80 if max_dd < 10 else (60 if max_dd < 20 else 30))
                scores.append(s)
                checks.append({
                    "name": "历史最大回撤",
                    "status": "pass" if max_dd < 10 else ("warn" if max_dd < 20 else "fail"),
                    "detail": f"回测最大回撤: -{max_dd:.2f}%",
                    "meta": "来源: mr_optimization_results.json",
                    "score": s,
                    "explanation": "最大回撤是策略风险的终极指标。超过20%可能触发客户赎回潮。专业基金通常将回撤控制在<10%。",
                    "threshold": "🟢 <10%: 优秀 | 🟡 10-20%: 可接受但需关注 | 🔴 >20%: 必须重新审视策略",
                    "action": "检查回撤期间的市场环境，考虑添加最大回撤硬约束或优化参数",
                })
        except:
            pass

    final_score = int(np.mean(scores)) if scores else 0
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
        from factor_analyzer import FactorAnalyzer
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

    # V5.0: 因子可用性真实验证 (替代旧版恒满分检查)
    factor_types = {
        "基本面": ["roe", "eps", "netprofit_margin", "bps", "debt_to_assets"],
        "技术面": ["momentum_20d", "volatility_20d", "turnover_rate"],
    }
    total_factors = sum(len(v) for v in factor_types.values())

    # 实际验证: 抽检财务文件是否包含关键列
    fina_columns_ok = False
    fina_sample = glob.glob(os.path.join(FINA_DIR, "*.parquet"))[:1]
    if fina_sample:
        try:
            df_test = pd.read_parquet(fina_sample[0])
            required_cols = {"roe", "eps", "bps"}
            found_cols = required_cols.intersection(set(df_test.columns))
            fina_columns_ok = len(found_cols) >= 2  # 至少2个关键列存在
        except Exception:
            pass

    if fina_columns_ok:
        s = 90  # 有真实数据验证通过，但不给满分(留空间给更深度检测)
        status = "pass"
        detail = f"共 {total_factors} 个因子定义 · 基本面列验证通过"
    elif fina_count >= 10:
        s = 65
        status = "warn"
        detail = f"共 {total_factors} 个因子定义 · 基本面数据列未验证"
    else:
        s = 30
        status = "fail"
        detail = f"因子定义 {total_factors} 个 · 数据不足无法验证"

    scores.append(s)
    checks.append({
        "name": "因子池可用性",
        "status": status,
        "detail": detail,
        "meta": "基本面+技术面双覆盖 · 按需运行深度 IC 衰减审计",
        "score": s,
        "explanation": "多因子选股需要同时覆盖基本面(ROE/EPS/资产负债率)和技术面(动量/波动率/换手率)，且底层数据须包含对应列。仅有因子定义但无数据支撑=虚假覆盖。",
        "threshold": "🟢 因子定义+数据验证通过: 可信 | 🟡 有定义但数据未验证: 需确认 | 🔴 数据不足: 因子分析不可用",
        "action": "执行 python data_manager.py 确保财务数据包含 ROE/EPS/BPS 列",
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
    checks = []
    scores = []

    # ── 5.1 Tushare API 连通性 ──
    try:
        import tushare as ts
        pro = ts.pro_api()
        t0 = time.time()
        cal = pro.trade_cal(exchange='SSE', start_date='20260101', end_date='20260110')
        latency = (time.time() - t0) * 1000
        s = 100 if latency < 2000 else (70 if latency < 5000 else 40)
        scores.append(s)
        checks.append({
            "name": "Tushare API",
            "status": "pass" if latency < 3000 else "warn",
            "detail": f"连通 · 延迟 {latency:.0f}ms",
            "score": s,
            "explanation": "Tushare 是全部A股数据的入口，提供日线、财务、交易日历等。API离线意味着所有数据同步停止，系统将逐渐依赖过期缓存。延迟>3秒可能是网络问题或 API 配额耗尽。",
            "threshold": "🟢 <2秒: 正常 | 🟡 2-5秒: 偏慢 | 🔴 >5秒/连接失败: 系统瘫痪",
            "action": "检查网络连接和 Tushare Token 是否过期",
        })
    except Exception as e:
        scores.append(0)
        checks.append({
            "name": "Tushare API",
            "status": "fail",
            "detail": f"连接失败: {str(e)[:50]}",
            "score": 0,
            "explanation": "Tushare API 无法连接，所有数据同步停止。可能是网络问题、Token 过期或 Tushare 服务器维护。",
            "threshold": "🟢 <2秒 | 🟡 2-5秒 | 🔴 连接失败",
            "action": "检查网络 + config.py 中的 Tushare Token",
        })

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
    echarts_path = os.path.join(BASE_DIR, "echarts.min.js")
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

    return {
        "trust_score": trust_score,
        "trust_grade": _grade(trust_score),
        "total_checks": total_checks,
        "pass_count": total_checks - fail_count - warn_count - muted_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "muted_count": muted_count,
        "modules": modules,
        "weights": WEIGHTS,
        "audit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(elapsed_total, 2),
        # V4.0 新增字段
        "enforcement": enforcement_result,
        "version": "4.0",
    }


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
