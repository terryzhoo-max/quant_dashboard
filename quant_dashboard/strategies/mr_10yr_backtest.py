"""
AlphaCore · 均值回归 V4.2 策略 10年全样本回测
================================================
目标：严格评估策略 vs 沪深300ETF Buy&Hold（2016-2026）

设计原则（机构级）：
- 消除生存偏差：按 ETF 实际上市日期动态加入标的池
- 消除前视偏差：使用先验 FALLBACK_PARAMS，不使用后期优化参数
- Regime 判断：基于 000300.SH 沪深300指数（非ETF）
- 不计分红再投资
- 单边交易费率 0.10%（ETF 佣金）
- T+1 模拟（信号 shift(1)）

Author: AlphaCore 10yr Audit | 2026-05
"""

import pandas as pd
import numpy as np
import os, json, sys, time, warnings
warnings.filterwarnings('ignore')

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

import tushare as ts
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

# ─── 配置 ─────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import TUSHARE_TOKEN

DAILY_PRICE_DIR  = os.path.join(os.path.dirname(__file__), "..", "data_lake", "daily_prices")
RESULT_FILE      = os.path.join(os.path.dirname(__file__), "mr_10yr_results.json")

BENCHMARK_CODE   = "510300.SH"       # 沪深300ETF 作基准（不计分红）
INDEX_CODE       = "000300.SH"       # 沪深300指数 用于 Regime 判断
RISK_FREE_RATE   = 0.025             # 10年平均无风险利率取2.5%
TRANSACTION_COST = 0.0010            # 单边费率
MAX_TOTAL_POS    = 0.85              # 总仓位上限

BT_START = "2016-01-01"
BT_END   = "2026-05-21"
DATA_FETCH_START = "20150101"        # 多取一年用于指标预热

# ─── Regime 自适应参数（先验默认，非优化结果）─────────────────────────────────

REGIME_PARAMS = {
    "BEAR":  {"N_trend": 40, "rsi_period": 14, "rsi_buy": 45, "rsi_sell": 65,
              "bias_buy": -3.0, "stop_loss": 0.05},
    "RANGE": {"N_trend": 90, "rsi_period": 14, "rsi_buy": 40, "rsi_sell": 70,
              "bias_buy": -2.0, "stop_loss": 0.07},
    "BULL":  {"N_trend": 120, "rsi_period": 14, "rsi_buy": 45, "rsi_sell": 75,
              "bias_buy": -1.5, "stop_loss": 0.06},
}

# Regime 仓位上限
REGIME_POS_CAP = {
    "BEAR":  0.65,
    "RANGE": 0.80,
    "BULL":  0.35,
    "CRASH": 0.00,
}

# ─── 标的池（含上市日期，用于消除生存偏差）─────────────────────────────────────

MR_POOL = [
    # 宽基 — 2016年就存在的
    {"code": "510300.SH", "name": "沪深300ETF",     "max_pos": 15, "defensive": True,  "list_date": "20120528"},
    {"code": "510500.SH", "name": "中证500ETF",     "max_pos": 15, "defensive": False, "list_date": "20130226"},
    {"code": "159915.SZ", "name": "创业板ETF",       "max_pos": 10, "defensive": False, "list_date": "20111213"},
    # 2017-2018 上市
    {"code": "512560.SH", "name": "军工ETF",         "max_pos": 7,  "defensive": True,  "list_date": "20160811"},
    {"code": "513500.SH", "name": "标普500ETF",      "max_pos": 8,  "defensive": True,  "list_date": "20151218"},
    {"code": "512400.SH", "name": "有色金属ETF",     "max_pos": 6,  "defensive": False, "list_date": "20190628"},
    # 2019 上市
    {"code": "159949.SZ", "name": "创业板50ETF",     "max_pos": 10, "defensive": False, "list_date": "20191212"},
    {"code": "512480.SH", "name": "半导体ETF",       "max_pos": 8,  "defensive": False, "list_date": "20190522"},
    {"code": "515000.SH", "name": "科技ETF",         "max_pos": 6,  "defensive": False, "list_date": "20190927"},
    {"code": "159995.SZ", "name": "芯片ETF",         "max_pos": 7,  "defensive": False, "list_date": "20191216"},
    {"code": "512100.SH", "name": "中证1000ETF",    "max_pos": 15, "defensive": False, "list_date": "20191115"},
    # 2020 上市
    {"code": "515880.SH", "name": "通信ETF",         "max_pos": 6,  "defensive": False, "list_date": "20200218"},
    {"code": "515790.SH", "name": "光伏ETF",         "max_pos": 7,  "defensive": False, "list_date": "20200918"},
    {"code": "515070.SH", "name": "人工智能AIETF",   "max_pos": 6,  "defensive": False, "list_date": "20200720"},
    {"code": "588000.SH", "name": "科创50ETF",       "max_pos": 10, "defensive": False, "list_date": "20201116"},
    {"code": "513130.SH", "name": "恒生科技ETF",     "max_pos": 5,  "defensive": False, "list_date": "20210525"},
    {"code": "515100.SH", "name": "红利低波100ETF",  "max_pos": 5,  "defensive": True,  "list_date": "20191220"},
    # 2021 上市
    {"code": "159941.SZ", "name": "纳指ETF",         "max_pos": 8,  "defensive": True,  "list_date": "20170328"},
    {"code": "159819.SZ", "name": "人工智能ETF",     "max_pos": 6,  "defensive": False, "list_date": "20210108"},
    {"code": "516160.SH", "name": "新能源ETF",       "max_pos": 7,  "defensive": False, "list_date": "20210406"},
    {"code": "159870.SZ", "name": "化工ETF",         "max_pos": 5,  "defensive": False, "list_date": "20210113"},
    {"code": "588200.SH", "name": "科创芯片ETF",     "max_pos": 7,  "defensive": False, "list_date": "20210616"},
    {"code": "513090.SH", "name": "香港证券ETF",     "max_pos": 5,  "defensive": False, "list_date": "20210922"},
    {"code": "159781.SZ", "name": "科创创业ETF",     "max_pos": 8,  "defensive": False, "list_date": "20211108"},
    {"code": "513120.SH", "name": "港股创新药ETF",   "max_pos": 5,  "defensive": False, "list_date": "20210811"},
    {"code": "513970.SH", "name": "恒生消费ETF",     "max_pos": 5,  "defensive": False, "list_date": "20210309"},
    {"code": "159869.SZ", "name": "游戏ETF",         "max_pos": 5,  "defensive": False, "list_date": "20210113"},
    {"code": "159851.SZ", "name": "金融科技ETF",     "max_pos": 5,  "defensive": False, "list_date": "20210113"},
    # 2022+ 上市
    {"code": "588220.SH", "name": "科创100ETF",      "max_pos": 8,  "defensive": False, "list_date": "20221122"},
    {"code": "562500.SH", "name": "机器人ETF",       "max_pos": 5,  "defensive": False, "list_date": "20220623"},
    {"code": "562550.SH", "name": "绿电ETF",         "max_pos": 5,  "defensive": False, "list_date": "20220829"},
    {"code": "159516.SZ", "name": "半导体设备ETF",   "max_pos": 6,  "defensive": False, "list_date": "20220701"},
    {"code": "159218.SZ", "name": "卫星ETF",         "max_pos": 5,  "defensive": False, "list_date": "20220627"},
    {"code": "159326.SZ", "name": "电网设备ETF",     "max_pos": 5,  "defensive": True,  "list_date": "20220704"},
    {"code": "159545.SZ", "name": "恒生红利低波ETF", "max_pos": 5,  "defensive": True,  "list_date": "20220726"},
]


# ═══════════════════════════════════════════════════════════════════════════════
#  数据下载 — 从 Tushare 拉取全量历史数据
# ═══════════════════════════════════════════════════════════════════════════════

def download_all_data():
    """下载所有ETF + 基准指数的全量历史数据"""
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    os.makedirs(DAILY_PRICE_DIR, exist_ok=True)

    end_date = datetime.now().strftime("%Y%m%d")

    # 1. 下载沪深300指数（用于 Regime 判断）
    idx_file = os.path.join(DAILY_PRICE_DIR, f"{INDEX_CODE}.parquet")
    print(f"[DATA] 下载沪深300指数 {INDEX_CODE}...")
    try:
        df_idx = pro.index_daily(ts_code=INDEX_CODE, start_date=DATA_FETCH_START, end_date=end_date,
                                 fields="ts_code,trade_date,open,high,low,close,vol")
        if df_idx is not None and len(df_idx) > 0:
            df_idx = df_idx.sort_values("trade_date").reset_index(drop=True)
            df_idx.to_parquet(idx_file, index=False)
            print(f"  ✅ {INDEX_CODE}: {len(df_idx)} 条 ({df_idx.trade_date.min()} ~ {df_idx.trade_date.max()})")
        time.sleep(0.5)
    except Exception as e:
        print(f"  ❌ {INDEX_CODE}: {e}")

    # 2. 下载所有ETF
    all_codes = list(dict.fromkeys([e["code"] for e in MR_POOL] + [BENCHMARK_CODE]))
    total = len(all_codes)

    for i, code in enumerate(all_codes, 1):
        fp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")

        # 检查现有数据是否已够长
        if os.path.exists(fp):
            try:
                existing = pd.read_parquet(fp)
                min_date = str(existing['trade_date'].min())[:8]
                if int(min_date) <= int(DATA_FETCH_START) + 10000:  # 有2016年以前数据
                    print(f"  [{i}/{total}] {code} 已有足够历史数据 ✓ (起始: {min_date})")
                    continue
            except:
                pass

        print(f"  [{i}/{total}] 下载 {code}...")
        try:
            df = pro.fund_daily(ts_code=code, start_date=DATA_FETCH_START, end_date=end_date)
            if df is None or df.empty:
                df = pro.daily(ts_code=code, start_date=DATA_FETCH_START, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
                df.to_parquet(fp, index=False)
                print(f"    ✅ {len(df)} 条 ({df.trade_date.min()} ~ {df.trade_date.max()})")
            else:
                print(f"    ⚠️ 无数据")
            time.sleep(0.5)  # 频率控制
        except Exception as e:
            print(f"    ❌ {e}")
            time.sleep(1.0)

    print(f"\n[DATA] 数据下载完成\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════════════════════════════════════════════

def load_prices(codes: List[str], start: str, end: str) -> pd.DataFrame:
    """加载收盘价矩阵"""
    frames = {}
    s_dt, e_dt = pd.to_datetime(start), pd.to_datetime(end)

    for code in codes:
        fp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
        if not os.path.exists(fp):
            continue
        try:
            df = pd.read_parquet(fp)
            df['trade_date'] = pd.to_datetime(
                df['trade_date'].astype(str).str[:8], format='%Y%m%d')
            col = 'close'  # 不计分红，直接用收盘价
            if col not in df.columns:
                continue
            s = df.set_index('trade_date')[col].rename(code)
            frames[code] = s
        except Exception as e:
            print(f"  [WARN] 加载 {code} 失败: {e}")

    if not frames:
        raise FileNotFoundError("无任何价格数据")

    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


# ═══════════════════════════════════════════════════════════════════════════════
#  Regime 识别（基于沪深300指数）
# ═══════════════════════════════════════════════════════════════════════════════

def classify_regime_series(close_series: pd.Series) -> pd.Series:
    """
    对整段价格序列逐日标注 Regime。
    与实盘 _classify_regime_from_series 保持一致：
    - CRASH: 3日跌幅 > 7%
    - BULL:  close > MA120 AND slope5 > 0 AND ret20 > 0%
    - RANGE: close > MA120（走平）OR（close < MA120 AND ret5 > 3%）
    - BEAR:  close < MA120 AND ret5 <= 3%
    """
    close = close_series.values.astype(float)
    n = len(close)
    regimes = np.full(n, "RANGE", dtype=object)

    ma120 = pd.Series(close).rolling(120, min_periods=120).mean().values

    for i in range(120, n):
        # CRASH 检测
        if i >= 3:
            ret3 = close[i] / close[i-3] - 1
            if ret3 < -0.07:
                regimes[i] = "CRASH"
                continue

        cur = close[i]
        ma120_val = ma120[i]
        if np.isnan(ma120_val):
            continue

        # MA120 5日斜率
        ma120_window = []
        for j in range(max(0, i-5), i+1):
            if not np.isnan(ma120[j]):
                ma120_window.append(ma120[j])
        if len(ma120_window) >= 2:
            slope5 = np.polyfit(np.arange(len(ma120_window), dtype=float), ma120_window, 1)[0]
        else:
            slope5 = 0.0

        ret5 = (close[i] / close[i-5] - 1) * 100 if i >= 5 else 0.0
        ret20 = (close[i] / close[i-20] - 1) * 100 if i >= 20 else 0.0
        above = cur > ma120_val

        if above and slope5 > 0 and ret20 > 0:
            regimes[i] = "BULL"
        elif above:
            regimes[i] = "RANGE"
        elif not above and ret5 > 3:
            regimes[i] = "RANGE"  # 超跌反弹
        else:
            regimes[i] = "BEAR"

    return pd.Series(regimes, index=close_series.index)


# ═══════════════════════════════════════════════════════════════════════════════
#  信号状态机（Regime 自适应参数版）
# ═══════════════════════════════════════════════════════════════════════════════

def signal_state_machine_regime(price_arr: np.ndarray,
                                regime_arr: np.ndarray) -> np.ndarray:
    """
    Regime 自适应信号状态机。
    每天根据当日 Regime 使用对应参数组。
    返回 sig: 0/1 信号序列。
    """
    n = len(price_arr)
    sig = np.zeros(n, dtype=float)
    in_pos = False
    entry_px = 0.0
    current_regime_params = REGIME_PARAMS["RANGE"]

    # 预计算所有可能的指标（用最大 N_trend=120）
    max_nt = 120
    rp = 14  # RSI period 统一14

    if n < max_nt + rp + 5:
        return sig

    # MA 系列
    ma40  = pd.Series(price_arr).rolling(40, min_periods=40).mean().values
    ma90  = pd.Series(price_arr).rolling(90, min_periods=90).mean().values
    ma120 = pd.Series(price_arr).rolling(120, min_periods=120).mean().values
    ma_map = {40: ma40, 90: ma90, 120: ma120}

    # BIAS 系列
    bias40  = np.where(ma40 > 0,  (price_arr - ma40) / ma40 * 100,  np.nan)
    bias90  = np.where(ma90 > 0,  (price_arr - ma90) / ma90 * 100,  np.nan)
    bias120 = np.where(ma120 > 0, (price_arr - ma120) / ma120 * 100, np.nan)
    bias_map = {40: bias40, 90: bias90, 120: bias120}

    # RSI(14)
    diff = np.diff(price_arr, prepend=price_arr[0])
    gain = np.where(diff > 0, diff, 0.0)
    loss_arr = np.where(diff < 0, -diff, 0.0)
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    if n > rp:
        avg_gain[rp] = gain[1:rp+1].mean()
        avg_loss[rp] = loss_arr[1:rp+1].mean()
        for i in range(rp + 1, n):
            avg_gain[i] = (avg_gain[i-1] * (rp - 1) + gain[i]) / rp
            avg_loss[i] = (avg_loss[i-1] * (rp - 1) + loss_arr[i]) / rp
    with np.errstate(invalid='ignore', divide='ignore'):
        rs = np.where(avg_loss < 1e-8, 100.0, avg_gain / avg_loss)
        rsi = 100 - 100 / (1 + rs)

    for i in range(1, n):
        px = price_arr[i]
        regime = regime_arr[i] if i < len(regime_arr) else "RANGE"

        # CRASH 禁入
        if regime == "CRASH":
            if in_pos:
                in_pos = False
                sig[i] = 0.0
            continue

        p = REGIME_PARAMS.get(regime, REGIME_PARAMS["RANGE"])
        nt = p["N_trend"]
        rb = p["rsi_buy"]
        rs_sell = p["rsi_sell"]
        bb = p["bias_buy"]
        sl = abs(p["stop_loss"])

        ma_t = ma_map.get(nt, ma90)
        bias = bias_map.get(nt, bias90)

        if np.isnan(ma_t[i]) or np.isnan(rsi[i]):
            if in_pos:
                sig[i] = 1.0
            continue

        if not in_pos:
            # 入场条件
            trend_ok = px > ma_t[i]
            buy_trig = (rsi[i] <= rb) or (not np.isnan(bias[i]) and bias[i] <= bb)
            if trend_ok and buy_trig:
                in_pos = True
                entry_px = px
                sig[i] = 1.0
        else:
            # 出场条件
            cumret = px / entry_px - 1
            sell_trig = (rsi[i] >= rs_sell or
                         cumret < -sl or
                         px < ma_t[i] * 0.97)
            if sell_trig:
                in_pos = False
                sig[i] = 0.0
            else:
                sig[i] = 1.0

    return sig


# ═══════════════════════════════════════════════════════════════════════════════
#  组合回测
# ═══════════════════════════════════════════════════════════════════════════════

def run_10yr_backtest():
    """执行10年全样本回测"""
    print("=" * 70)
    print("  AlphaCore 均值回归 V4.2 · 10年严格回测")
    print("  参数选择：Regime 自适应先验参数（非优化结果）")
    print("  基准：沪深300ETF Buy&Hold（不计分红）")
    print("=" * 70)

    # Step 1: 确保数据
    print(f"\n[STEP 1] 数据准备...")
    download_all_data()

    # Step 2: 加载数据
    print(f"\n[STEP 2] 加载价格数据 ({BT_START} ~ {BT_END})...")
    all_codes = list(dict.fromkeys([e["code"] for e in MR_POOL] + [BENCHMARK_CODE]))
    full_prices = load_prices(all_codes, start="2015-01-01", end=BT_END)

    if BENCHMARK_CODE not in full_prices.columns:
        raise RuntimeError(f"基准 {BENCHMARK_CODE} 数据缺失")

    bm_full = full_prices[BENCHMARK_CODE].copy()

    # 加载沪深300指数用于 Regime
    print(f"[STEP 2b] 加载沪深300指数用于 Regime 判断...")
    idx_file = os.path.join(DAILY_PRICE_DIR, f"{INDEX_CODE}.parquet")
    if os.path.exists(idx_file):
        df_idx = pd.read_parquet(idx_file)
        df_idx['trade_date'] = pd.to_datetime(df_idx['trade_date'].astype(str).str[:8], format='%Y%m%d')
        idx_series = df_idx.set_index('trade_date')['close'].sort_index()
        idx_series = idx_series.reindex(full_prices.index).ffill()
    else:
        print("  ⚠️ 使用基准ETF价格代替指数（精度略低）")
        idx_series = bm_full

    # Step 3: Regime 识别
    print(f"\n[STEP 3] 全时段 Regime 识别...")
    regime_series = classify_regime_series(idx_series)

    # 统计 Regime 分布
    bt_mask = full_prices.index >= pd.Timestamp(BT_START)
    regime_bt = regime_series[bt_mask]
    for r in ["BULL", "RANGE", "BEAR", "CRASH"]:
        cnt = (regime_bt == r).sum()
        pct = cnt / len(regime_bt) * 100
        print(f"  {r:6s}: {cnt:4d} 天 ({pct:5.1f}%)")

    # Step 4: 回测
    print(f"\n[STEP 4] 执行组合回测...")
    prices_bt = full_prices[bt_mask]
    bm_bt = bm_full[bt_mask]
    regime_bt_arr = regime_bt.values

    n_days = len(prices_bt)
    etf_codes = [e["code"] for e in MR_POOL if e["code"] in prices_bt.columns]
    max_pos_map = {e["code"]: e["max_pos"] / 100.0 for e in MR_POOL}
    list_date_map = {e["code"]: pd.Timestamp(e["list_date"]) for e in MR_POOL}
    defensive_set = {e["code"] for e in MR_POOL if e["defensive"]}

    print(f"  回测区间: {prices_bt.index[0].strftime('%Y-%m-%d')} ~ {prices_bt.index[-1].strftime('%Y-%m-%d')}")
    print(f"  总交易日: {n_days}")
    print(f"  可用ETF:  {len(etf_codes)}")

    # 生成信号矩阵
    sig_mat = pd.DataFrame(0.0, index=prices_bt.index, columns=etf_codes)
    active_count = pd.Series(0, index=prices_bt.index)

    for code in etf_codes:
        # 检查上市日期 — 消除生存偏差
        ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
        # 需要预热期（至少120+14+5=139个交易日 ≈ 7个月）
        warmup_date = ld + pd.Timedelta(days=210)  # 保守估计7个月

        arr = prices_bt[code].values.astype(float)
        sig = signal_state_machine_regime(arr, regime_bt_arr)

        # 上市前 + 预热期内的信号清零
        for i, dt in enumerate(prices_bt.index):
            if dt < warmup_date:
                sig[i] = 0.0
            else:
                break

        sig_mat[code] = sig

    # T+1: 信号延迟一天
    sig_t1 = sig_mat.shift(1).fillna(0)

    # 动态权重（Regime Overlay）
    final_w = np.zeros((n_days, len(etf_codes)))
    max_pos_arr = np.array([max_pos_map.get(c, 0.10) for c in etf_codes])

    for i in range(n_days):
        reg = regime_bt_arr[i]
        row_sig = sig_t1.iloc[i].values
        dt = prices_bt.index[i]

        # Regime Overlay
        if reg == "CRASH":
            continue  # 全空仓
        elif reg == "BULL":
            # 牛市：仅防御标的，上限35%
            mask = np.array([1.0 if c in defensive_set else 0.0 for c in etf_codes])
            eff_sig = row_sig * mask
            total_cap = REGIME_POS_CAP["BULL"]
        elif reg == "BEAR":
            eff_sig = row_sig
            total_cap = REGIME_POS_CAP["BEAR"]
        else:  # RANGE
            eff_sig = row_sig
            total_cap = REGIME_POS_CAP["RANGE"]

        # 生存偏差过滤：上市不足的ETF权重归零
        for j, code in enumerate(etf_codes):
            ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
            warmup = ld + pd.Timedelta(days=210)
            if dt < warmup:
                eff_sig[j] = 0.0

        raw = eff_sig * max_pos_arr
        s = raw.sum()
        if s > 0:
            scale = min(total_cap / s, 1.0)
            final_w[i] = raw * scale

    # 收益计算
    ret_mat = prices_bt[etf_codes].pct_change(fill_method=None).fillna(0).values
    port_ret = (final_w * ret_mat).sum(axis=1)

    # 换手成本
    w_diff = np.abs(np.diff(final_w, axis=0, prepend=final_w[:1]))
    cost = w_diff.sum(axis=1) * TRANSACTION_COST
    net_ret = port_ret - cost

    # 净值曲线
    equity = pd.Series((1 + net_ret).cumprod(), index=prices_bt.index)

    # 基准
    bm_ret = bm_bt.pct_change(fill_method=None).fillna(0)
    bm_eq = (1 + bm_ret).cumprod()

    # Step 5: 指标计算
    print(f"\n[STEP 5] 计算绩效指标...")

    def calc_metrics(eq, bm, pr, br, label=""):
        n = len(eq)
        if n < 20:
            return {"valid": False}

        _sl = lambda x: np.log(max(float(x), 1e-9))
        ann_f = 252 / n

        ann_ret = float(np.exp(_sl(eq.iloc[-1]) * ann_f) - 1)
        ann_bm = float(np.exp(_sl(bm.iloc[-1]) * ann_f) - 1)
        alpha = ann_ret - ann_bm

        total_ret = float(eq.iloc[-1] - 1)
        total_bm = float(bm.iloc[-1] - 1)

        roll_max = eq.cummax()
        max_dd = float(((eq - roll_max) / roll_max).min())

        excess = pr - RISK_FREE_RATE / 252
        sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 1e-8 else 0.0
        calmar = float(ann_ret / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

        active = pr - br
        ir = float(active.mean() / active.std() * np.sqrt(252)) if active.std() > 1e-8 else 0.0

        # 周胜率
        wk = pr.resample("W").sum()
        win_rate = float((wk > 0).sum() / max(len(wk), 1))

        # 持仓覆盖率
        total_pos_days = (final_w.sum(axis=1) > 0.01).sum() if label == "" else 0
        coverage = total_pos_days / max(n, 1)

        # 年化波动率
        ann_vol = float(pr.std() * np.sqrt(252))

        return {
            "ann_ret":    round(ann_ret * 100, 2),
            "ann_bm":     round(ann_bm * 100, 2),
            "alpha":      round(alpha * 100, 2),
            "total_ret":  round(total_ret * 100, 2),
            "total_bm":   round(total_bm * 100, 2),
            "max_dd":     round(max_dd * 100, 2),
            "sharpe":     round(sharpe, 3),
            "calmar":     round(calmar, 3),
            "ir":         round(ir, 3),
            "win_rate":   round(win_rate * 100, 1),
            "ann_vol":    round(ann_vol * 100, 2),
            "coverage":   round(coverage * 100, 1),
            "valid":      True,
        }

    # 全局指标
    overall = calc_metrics(equity, bm_eq,
                           pd.Series(net_ret, index=prices_bt.index),
                           bm_ret)

    # Step 6: 逐年明细
    print(f"\n[STEP 6] 逐年绩效分解...\n")

    yearly = {}
    for year in range(2016, 2027):
        y_start = f"{year}-01-01"
        y_end = f"{year}-12-31"
        mask_y = (prices_bt.index >= y_start) & (prices_bt.index <= y_end)

        if mask_y.sum() < 20:
            continue

        eq_y = equity[mask_y]
        bm_y = bm_eq[mask_y]

        # 标准化到年初=1
        eq_normed = eq_y / eq_y.iloc[0]
        bm_normed = bm_y / bm_y.iloc[0]

        y_ret = float(eq_normed.iloc[-1] - 1) * 100
        y_bm = float(bm_normed.iloc[-1] - 1) * 100
        y_alpha = y_ret - y_bm

        # 年内最大回撤
        y_roll = eq_normed.cummax()
        y_dd = float(((eq_normed - y_roll) / y_roll).min()) * 100

        # 年内主要 Regime
        regime_y = regime_bt[mask_y]
        main_regime = regime_y.value_counts().index[0] if len(regime_y) > 0 else "?"

        # 当年可用ETF数
        year_mid = pd.Timestamp(f"{year}-07-01")
        active_etfs = sum(1 for e in MR_POOL
                          if e["code"] in etf_codes and
                          pd.Timestamp(e["list_date"]) + pd.Timedelta(days=210) < year_mid)

        yearly[str(year)] = {
            "return":      round(y_ret, 2),
            "benchmark":   round(y_bm, 2),
            "alpha":       round(y_alpha, 2),
            "max_dd":      round(y_dd, 2),
            "main_regime": main_regime,
            "active_etfs": active_etfs,
        }

    # Step 7: 分 Regime 绩效
    print(f"[STEP 7] 分 Regime 绩效...\n")

    regime_perf = {}
    for regime_name in ["BULL", "RANGE", "BEAR", "CRASH"]:
        r_mask = regime_bt == regime_name
        if r_mask.sum() < 5:
            continue
        r_ret = pd.Series(net_ret, index=prices_bt.index)[r_mask]
        r_bm = bm_ret[r_mask]

        avg_daily_ret = float(r_ret.mean()) * 100
        avg_daily_bm = float(r_bm.mean()) * 100
        n_days_r = int(r_mask.sum())

        # 累计收益
        cum_ret = float((1 + r_ret).prod() - 1) * 100
        cum_bm = float((1 + r_bm).prod() - 1) * 100

        regime_perf[regime_name] = {
            "days": n_days_r,
            "cum_ret": round(cum_ret, 2),
            "cum_bm": round(cum_bm, 2),
            "cum_alpha": round(cum_ret - cum_bm, 2),
            "avg_daily_ret_bps": round(avg_daily_ret * 100, 1),
            "avg_daily_bm_bps": round(avg_daily_bm * 100, 1),
        }

    # ─── 输出结果 ──────────────────────────────────────────────────────────

    print("=" * 70)
    print("  📊 10年回测结果（2016-01 ~ 2026-05）")
    print("=" * 70)

    print(f"\n  {'指标':<20s} {'策略':>10s} {'基准':>10s} {'差异':>10s}")
    print(f"  {'-'*50}")
    print(f"  {'年化收益率':<17s} {overall['ann_ret']:>9.2f}% {overall['ann_bm']:>9.2f}% {overall['alpha']:>+9.2f}%")
    print(f"  {'累计收益率':<17s} {overall['total_ret']:>9.2f}% {overall['total_bm']:>9.2f}%")
    print(f"  {'最大回撤':<18s} {overall['max_dd']:>9.2f}%")
    print(f"  {'Sharpe Ratio':<20s} {overall['sharpe']:>9.3f}")
    print(f"  {'Calmar Ratio':<20s} {overall['calmar']:>9.3f}")
    print(f"  {'信息比率 IR':<17s} {overall['ir']:>9.3f}")
    print(f"  {'周胜率':<18s} {overall['win_rate']:>9.1f}%")
    print(f"  {'年化波动率':<17s} {overall['ann_vol']:>9.2f}%")
    print(f"  {'持仓覆盖率':<17s} {overall['coverage']:>9.1f}%")

    print(f"\n  {'─'*50}")
    print(f"  逐年明细:")
    print(f"  {'年份':<6s} {'策略':>8s} {'基准':>8s} {'Alpha':>8s} {'MaxDD':>8s} {'Regime':>8s} {'#ETF':>5s}")
    print(f"  {'-'*55}")
    for y, d in sorted(yearly.items()):
        print(f"  {y:<6s} {d['return']:>+7.2f}% {d['benchmark']:>+7.2f}% {d['alpha']:>+7.2f}% {d['max_dd']:>7.2f}% {d['main_regime']:>8s} {d['active_etfs']:>5d}")

    print(f"\n  {'─'*50}")
    print(f"  分 Regime 绩效:")
    print(f"  {'Regime':<8s} {'天数':>6s} {'策略累计':>10s} {'基准累计':>10s} {'Alpha':>10s}")
    print(f"  {'-'*50}")
    for r, d in regime_perf.items():
        print(f"  {r:<8s} {d['days']:>6d} {d['cum_ret']:>+9.2f}% {d['cum_bm']:>+9.2f}% {d['cum_alpha']:>+9.2f}%")

    # 保存 JSON
    result = {
        "generated_at": datetime.now().isoformat(),
        "backtest_period": f"{BT_START} ~ {BT_END}",
        "strategy": "均值回归 V4.2 Regime自适应",
        "params": "FALLBACK_PARAMS (先验，非优化)",
        "benchmark": f"{BENCHMARK_CODE} Buy&Hold (不计分红)",
        "overall": overall,
        "yearly": yearly,
        "regime_perf": regime_perf,
        "regime_params": REGIME_PARAMS,
        "equity_dates": [d.strftime("%Y-%m-%d") for d in equity.index.tolist()],
        "equity_values": [round(float(v), 4) for v in equity.tolist()],
        "bm_values": [round(float(v), 4) for v in bm_eq.tolist()],
    }

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  [SAVE] 结果已保存: {RESULT_FILE}")

    # 结论
    print(f"\n{'='*70}")
    if overall["alpha"] > 0:
        print(f"  ✅ 策略10年 Alpha = {overall['alpha']:+.2f}%/年，跑赢基准")
    else:
        print(f"  ❌ 策略10年 Alpha = {overall['alpha']:+.2f}%/年，跑输基准")
    print(f"  💡 风险调整后: Sharpe {overall['sharpe']:.3f} vs 基准, MaxDD {overall['max_dd']:.2f}%")
    print(f"{'='*70}")

    return result


if __name__ == "__main__":
    t0 = time.time()
    result = run_10yr_backtest()
    elapsed = time.time() - t0
    print(f"\n⏱️ 全程耗时: {elapsed:.1f}s ({elapsed/60:.1f}分钟)")
