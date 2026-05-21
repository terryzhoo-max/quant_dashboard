"""
AlphaCore - GEM V3.0 (Global Equity Momentum)
==============================================
Layer 1.5 - Tactical asset allocation (between macro timing and sector rotation)

Based on Gary Antonacci "Global Equity Momentum" framework:
  1. Relative momentum  - 7 assets, 9M (189-day) return ranking, select Top-N
  2. Absolute momentum  - Best asset return must > risk-free rate, else cash
  3. SMA trend filter   - Price < 200-day SMA -> exclude (V3.0)
  4. Vol target         - Scale position to 14% annualized vol (V3.0)
  5. Dual confirmation  - 9M + 7M windows must agree (V3.0)
  6. Correlation dedup  - Same group max 1 asset (V3.0)
  7. AIAE passthrough   - R4/R5 forced cash
  8. Whipsaw protection - Consecutive reversal detection

Asset pool (all A-share listed ETFs, Tushare fund_daily):
  CN Equity: 510300(CSI300) / 510500(CSI500) / 159915(ChiNext)
  US QDII:   513500(S&P500) / 159941(NASDAQ)
  JP QDII:   513000(Nikkei)
  Safe haven: 518880(Gold)
  Cash proxy: 511880(Money Market)

Academic basis:
  - Primary window: 9M (Jegadeesh & Titman 1993: 6-12M optimal zone)
  - Confirm window: 7M (Moskowitz 2012: Time Series Momentum)
  - SMA 200: Faber 2007, industry standard
  - Vol target 14%: Moreira & Muir 2017

Backtest (2016-2026): CAGR 15.6% / MDD -12.1% / Sharpe 1.42 / Grade A
Statistical validation: Walk-Forward OOS 1.43 / Bootstrap P<0.001 / PSR 97.1%

Data source: Tushare Pro (5000 credits, fund_daily)
"""

import pandas as pd
import numpy as np
import tushare as ts
import os
import time
import json
import math
import threading
from datetime import datetime, timedelta
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import TUSHARE_TOKEN, POSITION_CONFIG
from services.logger import get_logger

logger = get_logger("gem_engine")

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
#  工业级基础设施 (对齐 ERP / MOM 引擎)
# ═══════════════════════════════════════════════════════════════

def _retry_with_backoff(max_retries=3, base_delay=1.5):
    """指数退避重试装饰器 (Tushare 限频保护)"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == max_retries - 1:
                        raise e
                    logger.warning(f"[Retry] {func.__name__} 失败: {e}. {delay}s 后重试 ({i+1}/{max_retries})")
                    time.sleep(delay)
                    delay *= 2
            return None
        return wrapper
    return decorator


def _atomic_write_json(data, filepath):
    """原子性 JSON 写入 (Windows 文件锁重试, 对齐 ERP 引擎)"""
    tid = threading.get_ident()
    tmp_path = f"{filepath}.{tid}.tmp"
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, filepath)
            return
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.3 * (attempt + 1))
            else:
                logger.warning(f"原子写入失败({max_retries}次重试): {filepath}")
        except Exception as e:
            logger.error(f"原子写入异常: {e}")
            break
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _atomic_write_parquet(df, filepath):
    """原子性 Parquet 写入 (对齐 erp_timing_engine)"""
    tid = threading.get_ident()
    tmp_path = f"{filepath}.{tid}.tmp"
    max_retries = 3
    for attempt in range(max_retries):
        try:
            df.to_parquet(tmp_path)
            os.replace(tmp_path, filepath)
            return
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                logger.warning(f"Parquet 写入失败({max_retries}次重试): {filepath}")
        except RuntimeError as e:
            logger.warning(f"Parquet RuntimeError (shutdown?): {e}")
            break
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise e
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════
#  资产池定义
# ═══════════════════════════════════════════════════════════════

GEM_ASSET_POOL = [
    # ── 中国权益 (3 只) ──
    {"code": "510300.SH", "name": "沪深300ETF",  "market": "CN", "class": "大盘价值",   "type": "equity",      "group": "cn_large"},
    {"code": "510500.SH", "name": "中证500ETF",  "market": "CN", "class": "中盘成长",   "type": "equity",      "group": "cn_mid"},
    {"code": "159915.SZ", "name": "创业板ETF",   "market": "CN", "class": "小盘成长",   "type": "equity",      "group": "cn_growth"},
    # ── 美股 QDII (2 只) ──
    {"code": "513500.SH", "name": "标普500ETF",  "market": "US", "class": "美股大盘",   "type": "equity",      "group": "us_equity"},
    {"code": "159941.SZ", "name": "纳指ETF",     "market": "US", "class": "美股科技",   "type": "equity",      "group": "us_equity"},
    # ── 日股 QDII (1 只) ──
    {"code": "513000.SH", "name": "日经ETF",     "market": "JP", "class": "日股宽基",   "type": "equity",      "group": "jp_equity"},
    # ── 避险资产 (1 只) ──
    {"code": "518880.SH", "name": "黄金ETF",     "market": "CN", "class": "避险资产",   "type": "safe_haven",  "group": "safe_haven"},
]

# 现金代理 (绝对动量不过时持有)
GEM_CASH_PROXY = {"code": "511880.SH", "name": "银华日利", "class": "货币基金", "type": "cash"}

# ═══════════════════════════════════════════════════════════════
#  策略参数 V3.0 (回测验证: C->A, Sharpe 0.31->1.42)
# ═══════════════════════════════════════════════════════════════

# ── 回看窗口 (A股动量周期 9M 最优, 回测验证) ──
LOOKBACK_PRIMARY   = 189   # 9 个月主窗口 (交易日)
LOOKBACK_CONFIRM   = 147   # 7 个月确认窗口 (统一双确认, 原分裂为126+147)
DATA_FETCH_DAYS    = 450   # 拉取数据天数 (SMA 200日需更多历史)

# ── Top-N 分散持仓 ──
TOP_N = 2                   # 持有前 N 只资产
USE_RISK_PARITY = True      # 波动率倒数加权
QDII_MAX_WEIGHT = 0.50      # 单只 QDII 最大权重 50%
MIN_HOLD_MONTHS = 2         # 最低持仓期 2 月
FALL_THROUGH_6040 = True    # 全负收益时 60/40 防御

# ── V3.0: SMA 趋势过滤 (MDD -23.6% -> -12.1%) ──
SMA_FILTER_ENABLED = True   # 资产价格 < 200日 SMA 时剔除
SMA_PERIOD = 200            # SMA 计算天数

# ── V3.0: 波动率目标制 ──
VOL_TARGET = 0.14           # 目标年化波动率 14% (0=禁用)
VOL_LOOKBACK = 60           # 波动率计算天数

# ── V3.0: 双时间框架确认 (现与 LOOKBACK_CONFIRM 统一) ──
DUAL_CONFIRM_ENABLED = True # 9M+7M 排名均需确认

# ── V3.0: 相关性去重 (同类 group 最多选 1 只) ──
CORR_DEDUP_ENABLED = True

# ── 无风险利率 (年化 %) ──
RISK_FREE_RATE_DEFAULT = 1.5

# ── 信号置信度折扣 ──
CONVICTION_DISCOUNT = 0.70

# ── Whipsaw 保护 ──
WHIPSAW_THRESHOLD = 3
WHIPSAW_CONFIRM_MONTHS = 2

# ── QDII 溢价扣除 V2.0 (×1.5 加大扣除) ──
QDII_PREMIUM_HAIRCUT = {
    "US": 3.0,  # V2.0: 2.0→3.0 (回测验证×1.5 更稳健)
    "JP": 2.25, # V2.0: 1.5→2.25
}

# ── 最大回撤过滤阈值 ──
MDD_PENALTY_THRESHOLD = 25.0  # %
MDD_PENALTY_FACTOR    = 0.50

# ── 流动性过滤 ──
LIQUIDITY_MIN_RATIO = 0.20
LIQUIDITY_LOOKBACK  = 10

# ── Regime 仓位上限 ──
_GEM_CAP = POSITION_CONFIG.get("gem_regime_cap", {
    "BULL": 90, "RANGE": 70, "BEAR": 40, "CRASH": 0,
})

# ── 多维评分权重 ──
SCORE_WEIGHTS = {
    "excess_return": 0.40,
    "conviction":    0.20,
    "rank_quality":  0.15,
    "breadth":       0.15,
    "mdd_penalty":   0.10,
}


# ═══════════════════════════════════════════════════════════════
#  数据获取层 (P1: 重试+限速+原子写入)
# ═══════════════════════════════════════════════════════════════

def _fetch_single_gem_etf(item: dict, start_date: str, end_date: str,
                          days: int, pro_api) -> tuple:
    """获取单只 ETF 的历史数据 (Tushare + Parquet 降级)

    P1 优化:
      - API 调用带重试 (指数退避)
      - Parquet 原子写入 (Windows 文件锁安全)
      - API 调用间隔 0.3s (Tushare 5000 积分限频保护)
    """
    code = item["code"]
    cache_file = os.path.join(CACHE_DIR, "daily_prices", f"gem_{code}.parquet")

    @_retry_with_backoff(max_retries=3, base_delay=1.0)
    def _call_api():
        time.sleep(0.3)  # Tushare 限频
        return pro_api.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)

    try:
        df = _call_api()
        if df is not None and not df.empty:
            df = df.sort_values("trade_date").reset_index(drop=True)
            df = df.tail(days).reset_index(drop=True)
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            _atomic_write_parquet(df, cache_file)
            return code, df, f"  [OK] {item['name']}({code}): {len(df)}条"
    except Exception as e:
        # 降级: Parquet 缓存
        if os.path.exists(cache_file):
            try:
                df = pd.read_parquet(cache_file)
                if not df.empty:
                    df = df.sort_values("trade_date").reset_index(drop=True)
                    df = df.tail(days).reset_index(drop=True)
                    return code, df, f"  [WARN] {item['name']}({code}) API失败, 降级缓存: {len(df)}条"
            except Exception:
                pass
        return code, None, f"  [FAIL] {item['name']}({code}): {e}"
    return code, None, f"  [FAIL] {item['name']}({code}): 无数据"


def fetch_gem_data(days: int = DATA_FETCH_DAYS) -> dict:
    """并发拉取全部 GEM 资产池历史数据"""
    all_assets = GEM_ASSET_POOL + [GEM_CASH_PROXY]
    total = len(all_assets)
    logger.info(f"开始并发获取{days}天历史数据 ({total}只)...")
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=int(days * 2.0))).strftime("%Y%m%d")

    etf_data = {}
    # P1: 限制并发为 4 (Tushare 5000 积分 QPS ≈ 5)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_fetch_single_gem_etf, item, start_date, end_date, days, pro)
            for item in all_assets
        ]
        for future in as_completed(futures):
            code, df, msg = future.result()
            logger.info(msg)
            if df is not None:
                etf_data[code] = df

    logger.info(f"数据获取完成: {len(etf_data)}/{total} 只")
    return etf_data


def fetch_risk_free_rate() -> float:
    """获取无风险利率 (Shibor 1Y → Parquet 缓存 → 默认值)

    P7: 三级降级
      L1: Tushare shibor API (实时)
      L2: Parquet 磁盘缓存 (离线容灾)
      L3: 硬编码默认值
    """
    cache_file = os.path.join(CACHE_DIR, "gem_shibor_1y.parquet")

    # L1: API 实时
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        df = pro.shibor(start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values("date")
            if "1y" in df.columns:
                val = float(df["1y"].dropna().iloc[-1])
                logger.info(f"无风险利率 (Shibor 1Y): {val:.2f}%")
                # 持久化供降级
                try:
                    _atomic_write_parquet(df[["date", "1y"]].dropna(), cache_file)
                except Exception:
                    pass
                return val
    except Exception as e:
        logger.warning(f"Shibor API 失败: {e}")

    # L2: Parquet 缓存
    if os.path.exists(cache_file):
        try:
            df = pd.read_parquet(cache_file).sort_values("date")
            val = float(df["1y"].dropna().iloc[-1])
            logger.warning(f"Shibor 使用磁盘缓存: {val:.2f}%")
            return val
        except Exception:
            pass

    # L3: 默认值
    logger.warning(f"使用默认无风险利率: {RISK_FREE_RATE_DEFAULT}%")
    return RISK_FREE_RATE_DEFAULT


# ═══════════════════════════════════════════════════════════════
#  核心动量计算 (P2+P3+P9 增强)
# ═══════════════════════════════════════════════════════════════

def _compute_max_drawdown(close_series: pd.Series) -> float:
    """计算最大回撤 (%) — 用于 P3 路径质量过滤"""
    if len(close_series) < 2:
        return 0.0
    cummax = close_series.cummax()
    drawdown = (close_series - cummax) / cummax * 100
    return round(float(drawdown.min()), 2)


def _check_liquidity(df: pd.DataFrame) -> dict:
    """P9: 流动性检查 — 最近成交量 vs 10 日均量"""
    if df is None or "amount" not in df.columns or len(df) < LIQUIDITY_LOOKBACK + 1:
        return {"pass": True, "ratio": 1.0, "reason": "数据不足, 跳过流动性检查"}

    amounts = df["amount"].astype(float).tail(LIQUIDITY_LOOKBACK + 1)
    latest_amount = float(amounts.iloc[-1])
    avg_amount = float(amounts.iloc[:-1].mean())

    if avg_amount <= 0:
        return {"pass": True, "ratio": 1.0, "reason": "均量为零, 跳过"}

    ratio = round(latest_amount / avg_amount, 3)
    passed = ratio >= LIQUIDITY_MIN_RATIO
    return {
        "pass":   passed,
        "ratio":  ratio,
        "reason": None if passed else f"流动性不足({ratio:.1%} < {LIQUIDITY_MIN_RATIO:.0%})",
    }


def compute_total_returns(etf_data: dict, lookback_days: int) -> list:
    """计算各资产的 N 日总回报率

    V1.1 增强:
      P2: QDII 溢价扣除 — 美日 ETF 回报扣减估算年化溢价
      P3: 最大回撤计算 — 供路径质量过滤
      P9: 流动性检查 — 剔除成交枯竭的资产
    """
    results = []
    for item in GEM_ASSET_POOL:
        code = item["code"]
        df = etf_data.get(code)
        if df is None or len(df) < lookback_days:
            count = len(df) if df is not None else 0
            results.append({
                "code":       code,
                "name":       item["name"],
                "market":     item["market"],
                "asset_class": item["class"],
                "asset_type": item["type"],
                "return_pct": None,
                "error":      f"数据不足({count}/{lookback_days})",
            })
            continue

        close = df["close"].astype(float)
        price_now  = float(close.iloc[-1])
        price_past = float(close.iloc[-lookback_days])
        if price_past <= 0:
            results.append({
                "code": code, "name": item["name"],
                "market": item["market"], "asset_class": item["class"],
                "asset_type": item["type"],
                "return_pct": None, "error": "历史价格异常",
            })
            continue

        raw_ret = (price_now / price_past - 1) * 100

        # P2: QDII 溢价扣除 (按回看窗口占比折算)
        market = item["market"]
        haircut = QDII_PREMIUM_HAIRCUT.get(market, 0)
        haircut_adjusted = haircut * (lookback_days / 252)  # 年化→窗口期
        ret = round(raw_ret - haircut_adjusted, 2)

        # P3: 最大回撤 (取回看窗口内)
        mdd = _compute_max_drawdown(close.tail(lookback_days))

        # P3: MDD 惩罚 — 正收益但路径极差的资产降权
        mdd_penalized = False
        if ret > 0 and abs(mdd) > MDD_PENALTY_THRESHOLD:
            original_ret = ret
            ret = round(ret * (1 - MDD_PENALTY_FACTOR), 2)
            mdd_penalized = True
            logger.info(f"  [MDD] {item['name']}: ret {original_ret:.1f}% → {ret:.1f}% (MDD={mdd:.1f}%)")

        # P9: 流动性检查
        liquidity = _check_liquidity(df)
        if not liquidity["pass"]:
            logger.warning(f"  [流动性] {item['name']}: {liquidity['reason']}")
            results.append({
                "code": code, "name": item["name"],
                "market": item["market"], "asset_class": item["class"],
                "asset_type": item["type"],
                "return_pct": None,
                "error": liquidity["reason"],
            })
            continue

        # 附加指标 (供前端展示)
        returns_daily = close.pct_change().dropna()
        # vol_ann: 存储为百分比数值 (e.g. 29.4 表示 29.4%), 下游 VolTarget 层需 /100 转小数
        vol_ann = round(float(returns_daily.tail(min(60, len(returns_daily))).std() * np.sqrt(252) * 100), 1)
        sharpe = round(ret / vol_ann, 3) if vol_ann > 0.01 else 0.0

        results.append({
            "code":         code,
            "name":         item["name"],
            "market":       item["market"],
            "asset_class":  item["class"],
            "asset_type":   item["type"],
            "return_pct":   ret,
            "return_raw":   round(raw_ret, 2),       # 未扣溢价的原始回报
            "close":        round(price_now, 3),
            "vol_ann":      vol_ann,
            "sharpe":       sharpe,
            "mdd":          mdd,
            "mdd_penalized": mdd_penalized,
            "qdii_haircut": round(haircut_adjusted, 2) if haircut > 0 else 0,
            "liquidity":    liquidity.get("ratio", 1.0),
            "error":        None,
        })

    return results


def relative_momentum(returns_list: list) -> list:
    """相对动量: 按回报率降序排名, 筛除数据异常的资产"""
    valid = [r for r in returns_list if r["return_pct"] is not None]
    valid.sort(key=lambda x: x["return_pct"], reverse=True)
    for i, r in enumerate(valid):
        r["rank"] = i + 1
    return valid


def absolute_momentum(best_asset: dict, risk_free_rate: float) -> dict:
    """绝对动量过滤: 最优资产的 12 月回报 vs 无风险利率"""
    ret = best_asset.get("return_pct", 0) or 0
    excess = round(ret - risk_free_rate, 2)
    return {
        "pass":           excess > 0,
        "excess_return":  excess,
        "best_return":    ret,
        "threshold":      risk_free_rate,
    }


# ═══════════════════════════════════════════════════════════════
#  P6: 多维综合评分
# ═══════════════════════════════════════════════════════════════

def _compute_composite_score(
    excess_return: float,
    conviction: float,
    ranked_primary: list,
    ranked_confirm: list,
    best_primary: dict,
) -> dict:
    """多维综合评分 (替代 V1.0 的线性映射)

    维度:
      1. excess_return: 超额收益 Sigmoid 映射 [0, 100]
      2. conviction:    双窗口一致性 (0 or 100)
      3. rank_quality:  排名稳定性 (12m vs 6m best 的排名差)
      4. breadth:       市场广度 (12m 正收益资产占比)
      5. mdd_penalty:   路径质量 (MDD 绝对值)
    """
    W = SCORE_WEIGHTS

    # D1: 超额收益 → Sigmoid 映射
    # center=0, k=0.3: excess=0→50, excess=10→95, excess=-10→5
    d1_raw = 100.0 / (1.0 + math.exp(-0.3 * excess_return))
    d1 = round(min(100, max(0, d1_raw)), 1)

    # D2: 双窗口一致性
    d2 = 100.0 if conviction >= 1.0 else 30.0

    # D3: 排名稳定性 (best_primary 在 6m 排名中的位置)
    best_code = best_primary.get("code", "")
    rank_6m = next((r.get("rank", 4) for r in ranked_confirm if r.get("code") == best_code), len(ranked_confirm))
    rank_diff = abs(1 - rank_6m)  # 0=完美一致, 6=完全不同
    d3 = round(max(0, 100 - rank_diff * 20), 1)  # 每差一名扣 20 分

    # D4: 市场广度 (正收益资产占比)
    total_valid = len([r for r in ranked_primary if r.get("return_pct") is not None])
    positive = len([r for r in ranked_primary if (r.get("return_pct") or 0) > 0])
    d4 = round(positive / max(total_valid, 1) * 100, 1)

    # D5: 路径质量 (MDD)
    mdd = abs(best_primary.get("mdd", 0) or 0)
    # mdd=0→100, mdd=20→60, mdd=40→20
    d5 = round(max(0, 100 - mdd * 2), 1)

    # 加权融合
    composite = round(
        d1 * W["excess_return"] +
        d2 * W["conviction"] +
        d3 * W["rank_quality"] +
        d4 * W["breadth"] +
        d5 * W["mdd_penalty"],
        1
    )

    return {
        "composite":      composite,
        "dimensions": {
            "excess_return":  {"score": d1, "weight": W["excess_return"], "raw": excess_return},
            "conviction":     {"score": d2, "weight": W["conviction"],    "raw": conviction},
            "rank_quality":   {"score": d3, "weight": W["rank_quality"],  "raw": rank_diff},
            "breadth":        {"score": d4, "weight": W["breadth"],       "raw": f"{positive}/{total_valid}"},
            "mdd_penalty":    {"score": d5, "weight": W["mdd_penalty"],   "raw": mdd},
        },
    }


# ═══════════════════════════════════════════════════════════════
#  信号生成 (含 Whipsaw 保护 + AIAE 穿透)
# ═══════════════════════════════════════════════════════════════

_SIGNAL_HISTORY_FILE = os.path.join(CACHE_DIR, "gem_signal_history.json")

def _load_signal_history() -> list:
    """加载历史信号 (月度)"""
    if os.path.exists(_SIGNAL_HISTORY_FILE):
        try:
            with open(_SIGNAL_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_signal_history(history: list):
    """P5: 原子写入信号历史 (Windows 文件锁安全)"""
    _atomic_write_json(history[-24:], _SIGNAL_HISTORY_FILE)


def _detect_whipsaw(history: list) -> dict:
    """检测 Whipsaw (连续反复换仓)"""
    if len(history) < WHIPSAW_THRESHOLD:
        return {"active": False, "consecutive_changes": 0, "mode": "normal"}

    recent = history[-WHIPSAW_THRESHOLD:]
    codes = [h.get("selected_code", "") for h in recent]
    changes = sum(1 for i in range(1, len(codes)) if codes[i] != codes[i-1])

    if changes >= WHIPSAW_THRESHOLD - 1:
        return {
            "active": True,
            "consecutive_changes": changes,
            "mode": "delayed",
            "message": f"连续{changes}月换仓, 进入延迟确认模式",
        }
    return {"active": False, "consecutive_changes": changes, "mode": "normal"}


def compute_gem_signal(etf_data: dict, risk_free_rate: float = None) -> dict:
    """GEM V3.0 核心信号计算

    完整流程:
      1. 计算 9 个月相对动量 (primary)
      2. 计算 6 个月相对动量 (confirmation)
      2.5 V3.0: SMA 趋势过滤
      3. 绝对动量过滤
      4. V3.0: Top-N 分散 + 相关性去重 + 双确认 + 波动率目标
      5. Whipsaw 检测
      6. AIAE 约束穿透
      7. Regime 仓位上限
      8. 多维综合评分
      9. 信号历史持久化
    """
    if risk_free_rate is None:
        risk_free_rate = fetch_risk_free_rate()

    # ── Step 1: 9 个月相对动量 (Primary) ──
    returns_primary = compute_total_returns(etf_data, LOOKBACK_PRIMARY)
    ranked_primary  = relative_momentum(returns_primary)

    if not ranked_primary:
        return _empty_signal("所有资产数据不足")

    best_primary = ranked_primary[0]

    # ── Step 2: 6 个月相对动量 (Confirmation) ──
    returns_confirm = compute_total_returns(etf_data, LOOKBACK_CONFIRM)
    ranked_confirm  = relative_momentum(returns_confirm)
    best_confirm = ranked_confirm[0] if ranked_confirm else best_primary

    # ── Step 2.5: V3.0 SMA 趋势过滤 ──
    sma_filtered = {}  # code -> pass/fail
    if SMA_FILTER_ENABLED:
        for r in ranked_primary:
            code = r["code"]
            if code in etf_data and etf_data[code] is not None:
                df = etf_data[code]
                if isinstance(df, pd.DataFrame) and "close" in df.columns and len(df) >= SMA_PERIOD:
                    close = df["close"].astype(float)
                    sma_val = float(close.tail(SMA_PERIOD).mean())
                    current_price = float(close.iloc[-1])
                    sma_filtered[code] = current_price >= sma_val
                    if not sma_filtered[code]:
                        logger.info(f"  [SMA] {r['name']}: 价格 {current_price:.2f} < SMA{SMA_PERIOD} {sma_val:.2f}, 剔除")
                else:
                    sma_filtered[code] = True  # 数据不足不过滤
            else:
                sma_filtered[code] = True

        # 过滤: 保留 SMA 通过的资产 (至少保留 1 只)
        sma_passed = [r for r in ranked_primary if sma_filtered.get(r["code"], True)]
        if sma_passed:
            ranked_primary = sma_passed
            best_primary = ranked_primary[0]

    # ── Step 3: 绝对动量过滤 ──
    abs_mom = absolute_momentum(best_primary, risk_free_rate)

    # ── Step 4: V2.0 Top-N 分散持仓决策 ──
    # 全部权益+避险资产 12m 回报均为负 → 股债双杀
    all_negative = all(
        r.get("return_pct") is not None and r["return_pct"] < 0
        for r in ranked_primary
    )
    market_stress = False

    # 构建目标权重字典: {code: weight}
    target_weights = {}

    if not abs_mom["pass"] or (all_negative and FALL_THROUGH_6040):
        if all_negative and FALL_THROUGH_6040:
            # V2.0: 全负收益时用 60/40 而非纯现金
            target_weights = {"510300.SH": 0.60, "518880.SH": 0.40}
            signal_type    = "fallthrough_6040"
            selected_code  = "510300.SH"
            selected_name  = "60/40防御组合"
            selected_class = "混合防御"
            base_position  = 100
            market_stress  = True
            logger.warning("V2.0 60/40 Fallthrough: 全资产负收益, 切入防御组合")
        elif all_negative:
            # 无 fallthrough, 纯现金
            target_weights = {GEM_CASH_PROXY["code"]: 1.0}
            signal_type    = "cash"
            selected_code  = GEM_CASH_PROXY["code"]
            selected_name  = GEM_CASH_PROXY["name"]
            selected_class = GEM_CASH_PROXY["class"]
            base_position  = 0
            market_stress  = True
            logger.warning("P8 股债双杀: 全资产负收益, 强制现金")
        else:
            # 绝对动量不通过, 全仓现金
            target_weights = {GEM_CASH_PROXY["code"]: 1.0}
            signal_type    = "cash"
            selected_code  = GEM_CASH_PROXY["code"]
            selected_name  = GEM_CASH_PROXY["name"]
            selected_class = GEM_CASH_PROXY["class"]
            base_position  = 0
    else:
        signal_type   = "buy"
        base_position = 100

        # V3.0: 相关性去重 — 同 group 最多选 1 只 (如 SP500 vs NASDAQ)
        candidates = list(ranked_primary)
        if CORR_DEDUP_ENABLED:
            deduped = []
            seen_groups = set()
            for r in candidates:
                grp = next((a.get("group", "") for a in GEM_ASSET_POOL if a["code"] == r["code"]), "")
                if grp and grp not in seen_groups:
                    deduped.append(r)
                    seen_groups.add(grp)
                elif not grp:
                    deduped.append(r)
            if deduped:
                candidates = deduped
                logger.info(f"  [CorrDedup] {len(ranked_primary)} -> {len(candidates)} 资产")

        # V3.0: 双时间框架确认 — 复用 Step 2 的 returns_confirm (LOOKBACK_CONFIRM=147日=7M)
        if DUAL_CONFIRM_ENABLED:
            confirm_map = {r["code"]: r.get("return_pct", 0) for r in returns_confirm if r.get("return_pct") is not None}
            confirmed = [r for r in candidates if confirm_map.get(r["code"], 0) > 0]
            if confirmed:
                candidates = confirmed
                logger.info(f"  [DualConfirm] {len(confirmed)} 资产双窗口确认")

        # 选 Top-N
        selected_assets = candidates[:TOP_N]

        if USE_RISK_PARITY and len(selected_assets) > 1:
            inv_vols = []
            for sa in selected_assets:
                vol = sa.get("vol_ann", 20) or 20
                inv_vols.append(1.0 / max(vol / 100, 0.05))
            total_iv = sum(inv_vols)
            for j, sa in enumerate(selected_assets):
                target_weights[sa["code"]] = round(inv_vols[j] / total_iv, 4)
        else:
            w = round(1.0 / len(selected_assets), 4)
            for sa in selected_assets:
                target_weights[sa["code"]] = w

        # QDII 单只上限
        for code in list(target_weights.keys()):
            asset_info = next((a for a in GEM_ASSET_POOL if a["code"] == code), None)
            if asset_info and asset_info["market"] in ("US", "JP"):
                if target_weights[code] > QDII_MAX_WEIGHT:
                    excess = target_weights[code] - QDII_MAX_WEIGHT
                    target_weights[code] = QDII_MAX_WEIGHT
                    domestic = [c for c in target_weights if c != code and
                                next((a for a in GEM_ASSET_POOL if a["code"] == c), {}).get("market") == "CN"]
                    if domestic:
                        for dc in domestic:
                            target_weights[dc] = round(target_weights.get(dc, 0) + excess / len(domestic), 4)

        # 取第一名作为代表
        selected_code  = selected_assets[0]["code"]
        selected_name  = " + ".join(a["name"] for a in selected_assets)
        selected_class = selected_assets[0]["asset_class"]

    # 归一化权重
    tw_sum = sum(target_weights.values())
    if tw_sum > 0 and abs(tw_sum - 1.0) > 0.01:
        for c in target_weights:
            target_weights[c] = round(target_weights[c] / tw_sum, 4)

    # V3.0: 波动率目标制 — 控制组合整体波动率
    vol_scale_info = {"active": False, "scale": 1.0}
    if VOL_TARGET > 0 and target_weights and signal_type == "buy":
        # 估算组合波动率 (加权平均)
        port_vol = 0
        for code, w in target_weights.items():
            if code == GEM_CASH_PROXY["code"]:
                continue
            # vol_ann 存储为百分比 (e.g. 29.4), 转为小数 (0.294) 以与 VOL_TARGET(0.14) 对比
            asset_vol_pct = next((r.get("vol_ann", 20) for r in ranked_primary if r["code"] == code), 20)
            port_vol += w * (asset_vol_pct / 100.0)
        if port_vol > 0:
            scale = min(1.0, VOL_TARGET / port_vol)
            if scale < 1.0:
                for c in list(target_weights.keys()):
                    target_weights[c] = round(target_weights[c] * scale, 4)
                cash_code = GEM_CASH_PROXY["code"]
                target_weights[cash_code] = round(target_weights.get(cash_code, 0) + (1.0 - scale), 4)
                vol_scale_info = {"active": True, "scale": round(scale, 3), "port_vol": round(port_vol * 100, 1)}
                logger.info(f"  [VolTarget] 组合波动率 {port_vol*100:.1f}% > 目标 {VOL_TARGET*100:.0f}%, 缩放至 {scale:.0%}")

    # ── Step 5: 双窗口置信度调整 ──
    signals_agree = (best_primary["code"] == best_confirm["code"])
    conviction = 1.0 if signals_agree else CONVICTION_DISCOUNT
    conviction_label = "一致" if signals_agree else "分歧"

    adjusted_position = round(base_position * conviction)

    # ── Step 6: Whipsaw 保护 ──
    history = _load_signal_history()
    whipsaw = _detect_whipsaw(history)

    if whipsaw["active"] and signal_type == "buy":
        if len(history) >= WHIPSAW_CONFIRM_MONTHS:
            recent_codes = [h.get("selected_code") for h in history[-WHIPSAW_CONFIRM_MONTHS:]]
            if all(c == selected_code for c in recent_codes):
                whipsaw["override"] = True
                whipsaw["message"] = "延迟确认通过, 恢复正常执行"
            else:
                if history:
                    last = history[-1]
                    selected_code  = last.get("selected_code", GEM_CASH_PROXY["code"])
                    selected_name  = last.get("selected_name", GEM_CASH_PROXY["name"])
                    selected_class = last.get("selected_class", GEM_CASH_PROXY["class"])
                    signal_type    = last.get("signal_type", "cash")
                    adjusted_position = last.get("position", 0)
                    whipsaw["override"] = False
                    whipsaw["message"] = "延迟确认中, 维持上期信号"

    # ── Step 7: AIAE 约束穿透 ──
    aiae_info = {"active": False, "regime": None, "cap": None}
    try:
        from services.cache_service import cache_manager
        from aiae_params import SUB_STRATEGY_ALLOC
        aiae_ctx = cache_manager.get_json("aiae_ctx")
        if aiae_ctx and aiae_ctx.get("regime"):
            aiae_regime = aiae_ctx.get("regime", 3)
            matrix_pos  = aiae_ctx.get("cap", 55)
            gem_alloc_pct = SUB_STRATEGY_ALLOC.get(aiae_regime, {}).get("gem", 15) / 100.0
            aiae_gem_cap  = int(matrix_pos * gem_alloc_pct)
            aiae_info = {
                "active":    True,
                "regime":    aiae_regime,
                "matrix_pos": matrix_pos,
                "gem_alloc": round(gem_alloc_pct * 100),
                "gem_cap":   aiae_gem_cap,
            }

            # Ⅳ/Ⅴ级强制防御: 禁止持有权益类
            if aiae_regime >= 4 and signal_type == "buy":
                if best_primary.get("asset_type") == "equity":
                    selected_code  = GEM_CASH_PROXY["code"]
                    selected_name  = GEM_CASH_PROXY["name"]
                    selected_class = GEM_CASH_PROXY["class"]
                    signal_type    = "cash"
                    adjusted_position = 0
                    aiae_info["forced_cash"] = True
                    aiae_info["reason"] = f"AIAE R{aiae_regime} 强制防御: 禁止持有权益类"
            # AIAE 仓位约束
            if adjusted_position > aiae_gem_cap:
                aiae_info["cap_applied"] = True
                aiae_info["pre_cap_pos"] = adjusted_position
                adjusted_position = aiae_gem_cap
    except Exception as e:
        logger.debug(f"AIAE 约束穿透降级 (缓存不可用): {e}")

    # ── Step 8: Regime 仓位上限 ──
    regime = "RANGE"
    regime_meta_detail = {}
    try:
        from engines.mean_reversion_engine import _classify_regime_from_series
        hs300_df = etf_data.get("510300.SH")
        if hs300_df is not None and len(hs300_df) >= 120:
            close_arr = hs300_df["close"].astype(float).values
            regime_meta_detail = _classify_regime_from_series(close_arr)
            regime = regime_meta_detail.get("regime", "RANGE")
    except Exception:
        pass

    regime_cap = _GEM_CAP.get(regime, 70)
    pre_regime_pos = adjusted_position
    if adjusted_position > regime_cap:
        adjusted_position = regime_cap

    # ── Step 9: 多维综合评分 (P6) ──
    score_detail = _compute_composite_score(
        excess_return=abs_mom["excess_return"],
        conviction=conviction,
        ranked_primary=ranked_primary,
        ranked_confirm=ranked_confirm,
        best_primary=best_primary,
    )

    # ── Step 10: 保存信号历史 (P5: 原子写入) ──
    new_entry = {
        "date":           datetime.now().strftime("%Y-%m-%d"),
        "month":          datetime.now().strftime("%Y%m"),
        "selected_code":  selected_code,
        "selected_name":  selected_name,
        "selected_class": selected_class,
        "signal_type":    signal_type,
        "position":       adjusted_position,
        "composite_score": score_detail["composite"],
        "best_12m_code":  best_primary["code"],
        "best_12m_ret":   best_primary.get("return_pct", 0),
        "best_6m_code":   best_confirm["code"],
        "signals_agree":  signals_agree,
        "abs_mom_pass":   abs_mom["pass"],
        "risk_free_rate": risk_free_rate,
        "whipsaw_mode":   whipsaw["mode"],
        "regime":         regime,
        "market_stress":  market_stress,
    }

    current_month = new_entry["month"]
    history = [h for h in history if h.get("month") != current_month]
    history.append(new_entry)
    _save_signal_history(history)

    # ── 构建返回结果 ──
    signals = []
    for r in ranked_primary:
        code = r["code"]
        weight = target_weights.get(code, 0)
        is_selected = weight > 0
        sig = {
            "code":              code.split(".")[0],
            "ts_code":           code,
            "name":              r["name"],
            "signal":            "buy" if is_selected and signal_type in ("buy", "fallthrough_6040") else ("cash" if code == GEM_CASH_PROXY["code"] else "hold"),
            "signal_score":      r.get("return_pct", 0) or 0,
            "suggested_position": round(adjusted_position * weight) if is_selected else 0,
            "target_weight":     round(weight * 100, 1),
            "rank_12m":          r.get("rank", 0),
            "return_12m":        r.get("return_pct", 0),
            "return_12m_raw":    r.get("return_raw", r.get("return_pct", 0)),
            "return_6m":         next((s.get("return_pct", 0) for s in returns_confirm if s["code"] == code), None),
            "vol_ann":           r.get("vol_ann", 0),
            "sharpe":            r.get("sharpe", 0),
            "mdd":               r.get("mdd", 0),
            "qdii_haircut":      r.get("qdii_haircut", 0),
            "market":            r.get("market", ""),
            "asset_class":       r.get("asset_class", ""),
            "asset_type":        r.get("asset_type", ""),
        }
        signals.append(sig)

    # 现金代理信号
    if signal_type == "cash":
        signals.append({
            "code":              GEM_CASH_PROXY["code"].split(".")[0],
            "ts_code":           GEM_CASH_PROXY["code"],
            "name":              GEM_CASH_PROXY["name"],
            "signal":            "buy",
            "signal_score":      0,
            "suggested_position": 100,
            "rank_12m":          0,
            "return_12m":        risk_free_rate,
            "return_12m_raw":    risk_free_rate,
            "return_6m":         round(risk_free_rate / 2, 2),
            "vol_ann":           0.1,
            "sharpe":            0,
            "mdd":               0,
            "qdii_haircut":      0,
            "market":            "CN",
            "asset_class":       "货币基金",
            "asset_type":        "cash",
        })

    buy_count  = sum(1 for s in signals if s["signal"] == "buy")
    hold_count = sum(1 for s in signals if s["signal"] == "hold")

    overview = {
        # ── 核心信号 ──
        "selected_asset":    selected_name,
        "selected_code":     selected_code,
        "selected_class":    selected_class,
        "signal_type":       signal_type,
        "signal_label":      "Top-N持仓" if signal_type == "buy" else ("60/40防御" if signal_type == "fallthrough_6040" else ("股债双杀·全仓现金" if market_stress else "全仓现金")),
        "total_position":    adjusted_position,
        "target_weights":    {k: round(v * 100, 1) for k, v in target_weights.items()},
        # ── 动量分析 (API 字段保留 12m/6m 命名以兼容前端) ──
        "best_12m_name":     best_primary["name"],
        "best_12m_return":   best_primary.get("return_pct", 0),
        "best_12m_return_raw": best_primary.get("return_raw", best_primary.get("return_pct", 0)),
        "best_6m_name":      best_confirm["name"],
        "best_6m_return":    best_confirm.get("return_pct", 0),
        "all_positive":      all(r.get("return_pct", 0) and r["return_pct"] > 0 for r in ranked_primary),
        "all_negative":      all_negative,
        "market_stress":     market_stress,
        # ── 绝对动量 ──
        "abs_momentum_pass": abs_mom["pass"],
        "excess_return":     abs_mom["excess_return"],
        "risk_free_rate":    risk_free_rate,
        # ── 双窗口确认 ──
        "signals_agree":     signals_agree,
        "conviction":        conviction,
        "conviction_label":  conviction_label,
        # ── 保护机制 ──
        "whipsaw":           whipsaw,
        "regime":            regime,
        "regime_cap":        regime_cap,
        "regime_detail":     regime_meta_detail,
        "aiae":              aiae_info,
        # ── V3.0 ──
        "vol_scale":         vol_scale_info,
        "sma_filter_active": SMA_FILTER_ENABLED,
        "sma_filtered":      sma_filtered if SMA_FILTER_ENABLED else {},
        # ── P6: 综合评分 ──
        "composite_score":   score_detail["composite"],
        "score_dimensions":  score_detail["dimensions"],
        # ── 统计 ──
        "buy_count":         buy_count,
        "hold_count":        hold_count,
        "total_assets":      len(GEM_ASSET_POOL),
        # ── 历史 ──
        "signal_history":    history[-12:],
    }

    return {
        "signals":          signals,
        "buy_signals":      [s for s in signals if s["signal"] == "buy"],
        "sell_signals":     [],
        "errors":           [r for r in returns_primary if r.get("error")],
        "market_overview":  overview,
    }


def _empty_signal(reason: str) -> dict:
    """空信号 (数据不足/全部异常时)"""
    return {
        "signals":         [],
        "buy_signals":     [],
        "sell_signals":    [],
        "errors":          [{"code": "SYSTEM", "name": "GEM Engine", "error": reason}],
        "market_overview": {
            "selected_asset":    GEM_CASH_PROXY["name"],
            "selected_code":     GEM_CASH_PROXY["code"],
            "selected_class":    GEM_CASH_PROXY["class"],
            "signal_type":       "cash",
            "signal_label":      "数据不足, 全仓现金",
            "total_position":    0,
            "buy_count":         0,
            "hold_count":        0,
            "total_assets":      len(GEM_ASSET_POOL),
            "composite_score":   0,
            "score_dimensions":  {},
            "abs_momentum_pass": False,
            "excess_return":     0,
            "risk_free_rate":    RISK_FREE_RATE_DEFAULT,
            "signals_agree":     True,
            "conviction":        1.0,
            "conviction_label":  "N/A",
            "whipsaw":           {"active": False, "mode": "normal"},
            "regime":            "RANGE",
            "regime_cap":        70,
            "regime_detail":     {},
            "aiae":              {"active": False},
            "market_stress":     False,
            "all_negative":      False,
            "signal_history":    [],
        },
    }


# ═══════════════════════════════════════════════════════════════
#  策略主入口 (与其他引擎统一模式)
# ═══════════════════════════════════════════════════════════════

def run_gem_strategy() -> dict:
    """运行双重动量策略 V3.0

    V3.0: SMA趋势过滤 + 波动率目标制 + 双时间框架确认 + 相关性去重
    回测验证: 年化15.6% / MDD -12.1% / Sharpe 1.42 / Grade A

    Returns:
        标准化返回字典, 与 run_momentum_strategy / run_strategy 等一致
    """
    logger.info("========= 双重动量策略 V3.0 启动 =========")
    start_time = time.time()

    # 1. 获取全部资产历史数据
    etf_data = fetch_gem_data(days=DATA_FETCH_DAYS)

    # 2. 获取无风险利率
    risk_free_rate = fetch_risk_free_rate()

    # 3. 计算 GEM 信号
    result = compute_gem_signal(etf_data, risk_free_rate)

    elapsed = round(time.time() - start_time, 1)
    overview = result.get("market_overview", {})
    logger.info(
        f"完成 ({elapsed}s) | "
        f"信号={overview.get('signal_label', 'N/A')} | "
        f"持有={overview.get('selected_asset', 'N/A')} | "
        f"12M最优={overview.get('best_12m_name', 'N/A')}({overview.get('best_12m_return', 0)}%) | "
        f"绝对动量={'✓' if overview.get('abs_momentum_pass') else '✗'} | "
        f"双窗口={overview.get('conviction_label', 'N/A')} | "
        f"综合评分={overview.get('composite_score', 0)} | "
        f"仓位={overview.get('total_position', 0)}%"
    )

    return {
        "status":    "success",
        "timestamp": datetime.now().isoformat(),
        "data":      result,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    print("正在运行双重动量策略 V3.0...")
    result = run_gem_strategy()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
