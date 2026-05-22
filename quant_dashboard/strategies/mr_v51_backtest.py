"""
AlphaCore · 均值回归 V5.1 · 迭代改进
============================================================
V5.0 诊断结论：
  - 底仓层累计 +16.89%，但仍跑输 B&H 36%（Regime择时损耗）
  - 增强层 11 年中 9 年负贡献，累计 -4.84%（信号质量差）

V5.1 改进方向（3条）：

  改进 1: 提高底仓比例 — 减少 Regime 择时的损耗
    BULL: 55% → 70%   (更接近满仓)
    RANGE: 35% → 50%
    BEAR: 15% → 25%   (提高，因为 BEAR→BULL 转折容易踏空)
    CRASH: 0% → 0%

  改进 2: 压缩增强层 + 严格信号过滤
    - 增强层上限全部减半（防止负信号拖累）
    - 增加双重确认：RSI 触发 + BIAS 同时满足（取交集而非并集）
    - 入场分数门槛：RSI < rsi_buy AND bias < bias_buy（同时满足）

  改进 3: 非对称止损/止盈
    - 止盈更积极：盈利 > 5% 启动追踪止盈（从最高点回落 2.5% 离场）
    - 止损更宽松：初始止损从 5-7% 放宽到 8-10%（减少鞭打）

Author: V5.1 iteration | 2026-05
"""

import pandas as pd
import numpy as np
import os, json, sys, time, warnings
warnings.filterwarnings('ignore')
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import TUSHARE_TOKEN

DAILY_PRICE_DIR = os.path.join(os.path.dirname(__file__), "..", "data_lake", "daily_prices")
RESULT_FILE = os.path.join(os.path.dirname(__file__), "mr_v51_results.json")

BENCHMARK_CODE = "510300.SH"
INDEX_CODE     = "000300.SH"
BASE_ETF       = "510300.SH"
RISK_FREE_RATE = 0.025
TRANSACTION_COST = 0.0010
BT_START = "2016-01-01"
BT_END   = "2026-05-21"

# ═══════════════════════════════════════════════════════════
#  V5.1 参数
# ═══════════════════════════════════════════════════════════

# 底仓 — 更高比例，减少择时损耗
BASE_ALLOC = {"BULL": 0.70, "RANGE": 0.50, "BEAR": 0.25, "CRASH": 0.00}

# 增强层 — 压缩至更小范围
ENHANCE_CAP = {"BULL": 0.15, "RANGE": 0.30, "BEAR": 0.35, "CRASH": 0.00}

# MR 参数 — 更严格的入场条件 + 更宽的止损
REGIME_PARAMS = {
    "BEAR":  {"N_trend": 40,  "rsi_period": 14, "rsi_buy": 35, "rsi_sell": 65,
              "bias_buy": -4.0, "stop_loss": 0.10, "trailing_start": 0.06, "trailing_drop": 0.03},
    "RANGE": {"N_trend": 90,  "rsi_period": 14, "rsi_buy": 35, "rsi_sell": 70,
              "bias_buy": -3.0, "stop_loss": 0.09, "trailing_start": 0.05, "trailing_drop": 0.025},
    "BULL":  {"N_trend": 120, "rsi_period": 14, "rsi_buy": 35, "rsi_sell": 75,
              "bias_buy": -2.5, "stop_loss": 0.08, "trailing_start": 0.05, "trailing_drop": 0.025},
}

MIN_HOLD_DAYS = 5

MR_POOL = [
    {"code": "510300.SH", "name": "沪深300ETF",     "max_pos": 10, "list_date": "20120528"},
    {"code": "510500.SH", "name": "中证500ETF",     "max_pos": 10, "list_date": "20130226"},
    {"code": "159915.SZ", "name": "创业板ETF",       "max_pos": 7,  "list_date": "20111213"},
    {"code": "512560.SH", "name": "军工ETF",         "max_pos": 5,  "list_date": "20160811"},
    {"code": "513500.SH", "name": "标普500ETF",      "max_pos": 5,  "list_date": "20151218"},
    {"code": "512400.SH", "name": "有色金属ETF",     "max_pos": 5,  "list_date": "20190628"},
    {"code": "159949.SZ", "name": "创业板50ETF",     "max_pos": 6,  "list_date": "20191212"},
    {"code": "512480.SH", "name": "半导体ETF",       "max_pos": 5,  "list_date": "20190522"},
    {"code": "515000.SH", "name": "科技ETF",         "max_pos": 5,  "list_date": "20190927"},
    {"code": "159995.SZ", "name": "芯片ETF",         "max_pos": 5,  "list_date": "20191216"},
    {"code": "512100.SH", "name": "中证1000ETF",    "max_pos": 8,  "list_date": "20191115"},
    {"code": "515880.SH", "name": "通信ETF",         "max_pos": 5,  "list_date": "20200218"},
    {"code": "515790.SH", "name": "光伏ETF",         "max_pos": 5,  "list_date": "20200918"},
    {"code": "515070.SH", "name": "人工智能AIETF",   "max_pos": 5,  "list_date": "20200720"},
    {"code": "588000.SH", "name": "科创50ETF",       "max_pos": 6,  "list_date": "20201116"},
    {"code": "513130.SH", "name": "恒生科技ETF",     "max_pos": 5,  "list_date": "20210525"},
    {"code": "515100.SH", "name": "红利低波100ETF",  "max_pos": 5,  "list_date": "20191220"},
    {"code": "159941.SZ", "name": "纳指ETF",         "max_pos": 5,  "list_date": "20170328"},
    {"code": "159819.SZ", "name": "人工智能ETF",     "max_pos": 5,  "list_date": "20210108"},
    {"code": "516160.SH", "name": "新能源ETF",       "max_pos": 5,  "list_date": "20210406"},
    {"code": "159870.SZ", "name": "化工ETF",         "max_pos": 5,  "list_date": "20210113"},
    {"code": "588200.SH", "name": "科创芯片ETF",     "max_pos": 5,  "list_date": "20210616"},
    {"code": "513090.SH", "name": "香港证券ETF",     "max_pos": 5,  "list_date": "20210922"},
    {"code": "159781.SZ", "name": "科创创业ETF",     "max_pos": 5,  "list_date": "20211108"},
    {"code": "513120.SH", "name": "港股创新药ETF",   "max_pos": 5,  "list_date": "20210811"},
    {"code": "513970.SH", "name": "恒生消费ETF",     "max_pos": 5,  "list_date": "20210309"},
    {"code": "159869.SZ", "name": "游戏ETF",         "max_pos": 5,  "list_date": "20210113"},
    {"code": "159851.SZ", "name": "金融科技ETF",     "max_pos": 5,  "list_date": "20210113"},
    {"code": "588220.SH", "name": "科创100ETF",      "max_pos": 5,  "list_date": "20221122"},
    {"code": "562500.SH", "name": "机器人ETF",       "max_pos": 5,  "list_date": "20220623"},
    {"code": "562550.SH", "name": "绿电ETF",         "max_pos": 5,  "list_date": "20220829"},
    {"code": "159516.SZ", "name": "半导体设备ETF",   "max_pos": 5,  "list_date": "20220701"},
    {"code": "159218.SZ", "name": "卫星ETF",         "max_pos": 5,  "list_date": "20220627"},
    {"code": "159326.SZ", "name": "电网设备ETF",     "max_pos": 5,  "list_date": "20220704"},
    {"code": "159545.SZ", "name": "恒生红利低波ETF", "max_pos": 5,  "list_date": "20220726"},
]


def load_prices(codes, start, end):
    frames = {}
    s_dt, e_dt = pd.to_datetime(start), pd.to_datetime(end)
    for code in codes:
        fp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
        if not os.path.exists(fp): continue
        try:
            df = pd.read_parquet(fp)
            df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str).str[:8], format='%Y%m%d')
            if 'close' not in df.columns: continue
            frames[code] = df.set_index('trade_date')['close'].rename(code)
        except: pass
    if not frames: raise FileNotFoundError("无数据")
    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


def classify_regime_series(close_series):
    close = close_series.values.astype(float)
    n = len(close)
    regimes = np.full(n, "RANGE", dtype=object)
    ma120 = pd.Series(close).rolling(120, min_periods=120).mean().values
    for i in range(120, n):
        if i >= 3 and close[i] / close[i-3] - 1 < -0.07:
            regimes[i] = "CRASH"; continue
        cur, m = close[i], ma120[i]
        if np.isnan(m): continue
        w = [ma120[j] for j in range(max(0,i-5), i+1) if not np.isnan(ma120[j])]
        slope5 = float(np.polyfit(np.arange(len(w), dtype=float), w, 1)[0]) if len(w) >= 2 else 0
        ret5 = (close[i]/close[i-5]-1)*100 if i>=5 else 0
        ret20 = (close[i]/close[i-20]-1)*100 if i>=20 else 0
        if cur > m and slope5 > 0 and ret20 > 0: regimes[i] = "BULL"
        elif cur > m: regimes[i] = "RANGE"
        elif not cur > m and ret5 > 3: regimes[i] = "RANGE"
        else: regimes[i] = "BEAR"
    return pd.Series(regimes, index=close_series.index)


def mr_signal_v51(price_arr, regime_arr):
    """
    V5.1 信号：双重确认 + 非对称止损止盈
    入场: RSI < rsi_buy AND bias < bias_buy（同时满足，取交集）
    止盈: 盈利 > trailing_start 后，从最高点回落 trailing_drop 离场
    止损: 放宽到 8-10%
    """
    n = len(price_arr)
    sig = np.zeros(n, dtype=float)
    in_pos = False
    entry_px = 0.0
    entry_day = 0
    max_px_since_entry = 0.0

    rp = 14
    if n < 130: return sig

    ma40 = pd.Series(price_arr).rolling(40, min_periods=40).mean().values
    ma90 = pd.Series(price_arr).rolling(90, min_periods=90).mean().values
    ma120 = pd.Series(price_arr).rolling(120, min_periods=120).mean().values
    ma_map = {40: ma40, 90: ma90, 120: ma120}

    bias40 = np.where(ma40>0, (price_arr-ma40)/ma40*100, np.nan)
    bias90 = np.where(ma90>0, (price_arr-ma90)/ma90*100, np.nan)
    bias120 = np.where(ma120>0, (price_arr-ma120)/ma120*100, np.nan)
    bias_map = {40: bias40, 90: bias90, 120: bias120}

    diff = np.diff(price_arr, prepend=price_arr[0])
    gain = np.where(diff>0, diff, 0.0)
    loss_a = np.where(diff<0, -diff, 0.0)
    ag, al = np.full(n, np.nan), np.full(n, np.nan)
    if n > rp:
        ag[rp], al[rp] = gain[1:rp+1].mean(), loss_a[1:rp+1].mean()
        for i in range(rp+1, n):
            ag[i] = (ag[i-1]*(rp-1)+gain[i])/rp
            al[i] = (al[i-1]*(rp-1)+loss_a[i])/rp
    with np.errstate(invalid='ignore', divide='ignore'):
        rs = np.where(al < 1e-8, 100.0, ag/al)
        rsi = 100 - 100/(1+rs)

    for i in range(1, n):
        px = price_arr[i]
        regime = regime_arr[i] if i < len(regime_arr) else "RANGE"

        if regime == "CRASH":
            if in_pos: in_pos = False
            continue

        p = REGIME_PARAMS.get(regime, REGIME_PARAMS["RANGE"])
        nt = p["N_trend"]
        ma_t = ma_map.get(nt, ma90)
        bias = bias_map.get(nt, bias90)

        if np.isnan(ma_t[i]) or np.isnan(rsi[i]):
            if in_pos: sig[i] = 1.0
            continue

        if not in_pos:
            trend_ok = px > ma_t[i]
            # V5.1: 双重确认 — RSI AND BIAS 同时满足
            rsi_ok = rsi[i] <= p["rsi_buy"]
            bias_ok = not np.isnan(bias[i]) and bias[i] <= p["bias_buy"]
            if trend_ok and rsi_ok and bias_ok:
                in_pos = True
                entry_px = px
                entry_day = i
                max_px_since_entry = px
                sig[i] = 1.0
        else:
            max_px_since_entry = max(max_px_since_entry, px)
            hold_days = i - entry_day
            cumret = px / entry_px - 1
            sl = abs(p["stop_loss"])
            ts_start = p["trailing_start"]
            ts_drop = p["trailing_drop"]

            # 出场判断
            sell = False

            # 1. 追踪止盈：盈利超过阈值后，从最高点回落
            if cumret > ts_start:
                from_peak = px / max_px_since_entry - 1
                if from_peak < -ts_drop:
                    sell = True

            # 2. RSI 超买
            if rsi[i] >= p["rsi_sell"]:
                sell = True

            # 3. 固定止损（MIN_HOLD_DAYS内加倍宽容）
            if hold_days < MIN_HOLD_DAYS:
                if cumret < -(sl * 2):
                    sell = True
            else:
                if cumret < -sl:
                    sell = True

            # 4. 跌破趋势线
            if px < ma_t[i] * 0.96:
                sell = True

            if sell:
                in_pos = False
                sig[i] = 0.0
            else:
                sig[i] = 1.0

    return sig


def run_backtest():
    print("=" * 70)
    print("  AlphaCore V5.1 · 高底仓 + 严筛增强 + 追踪止盈")
    print("=" * 70)

    all_codes = list(dict.fromkeys([e["code"] for e in MR_POOL] + [BENCHMARK_CODE]))
    full_prices = load_prices(all_codes, "2015-01-01", BT_END)
    bm_full = full_prices[BENCHMARK_CODE].copy()

    idx_file = os.path.join(DAILY_PRICE_DIR, f"{INDEX_CODE}.parquet")
    if os.path.exists(idx_file):
        df_idx = pd.read_parquet(idx_file)
        df_idx['trade_date'] = pd.to_datetime(df_idx['trade_date'].astype(str).str[:8], format='%Y%m%d')
        idx_s = df_idx.set_index('trade_date')['close'].sort_index().reindex(full_prices.index).ffill()
    else:
        idx_s = bm_full

    regime_s = classify_regime_series(idx_s)
    bt_mask = full_prices.index >= pd.Timestamp(BT_START)
    prices_bt = full_prices[bt_mask]
    bm_bt = bm_full[bt_mask]
    regime_bt = regime_s[bt_mask]
    regime_arr = regime_bt.values
    n_days = len(prices_bt)

    etf_codes = [e["code"] for e in MR_POOL if e["code"] in prices_bt.columns]
    max_pos_map = {e["code"]: e["max_pos"]/100.0 for e in MR_POOL}
    list_date_map = {e["code"]: pd.Timestamp(e["list_date"]) for e in MR_POOL}

    # 信号
    sig_mat = pd.DataFrame(0.0, index=prices_bt.index, columns=etf_codes)
    for code in etf_codes:
        ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
        warmup_date = ld + pd.Timedelta(days=210)
        arr = prices_bt[code].values.astype(float)
        sig = mr_signal_v51(arr, regime_arr)
        for i, dt in enumerate(prices_bt.index):
            if dt < warmup_date: sig[i] = 0.0
            else: break
        sig_mat[code] = sig

    sig_t1 = sig_mat.shift(1).fillna(0)

    # 底仓
    base_w = np.zeros(n_days)
    for i in range(n_days):
        base_w[i] = BASE_ALLOC.get(regime_arr[i], 0.50)
    base_w_t1 = np.roll(base_w, 1); base_w_t1[0] = 0

    # 增强层
    enhance_w = np.zeros((n_days, len(etf_codes)))
    max_pos_arr = np.array([max_pos_map.get(c, 0.05) for c in etf_codes])

    for i in range(n_days):
        reg = regime_arr[i]
        ecap = ENHANCE_CAP.get(reg, 0.25)
        row_sig = sig_t1.iloc[i].values.copy()
        dt = prices_bt.index[i]
        for j, code in enumerate(etf_codes):
            ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
            if dt < ld + pd.Timedelta(days=210): row_sig[j] = 0.0
        raw = row_sig * max_pos_arr
        if BASE_ETF in etf_codes:
            bi = etf_codes.index(BASE_ETF)
            raw[bi] = max(0, raw[bi] - base_w_t1[i])
        s = raw.sum()
        if s > ecap: raw = raw * (ecap / s)
        enhance_w[i] = raw

    # 仓位上限
    total_pos = base_w_t1 + enhance_w.sum(axis=1)
    over = total_pos > 0.90
    if over.any():
        sc = np.where(over, 0.90/np.maximum(total_pos, 1e-6), 1.0)
        enhance_w = enhance_w * sc[:, np.newaxis]

    # 收益
    base_ret = bm_bt.pct_change(fill_method=None).fillna(0).values
    base_pnl = base_w_t1 * base_ret
    ret_mat = prices_bt[etf_codes].pct_change(fill_method=None).fillna(0).values
    enhance_pnl = (enhance_w * ret_mat).sum(axis=1)
    port_ret = base_pnl + enhance_pnl

    base_wd = np.abs(np.diff(base_w_t1, prepend=base_w_t1[0]))
    enh_wd = np.abs(np.diff(enhance_w, axis=0, prepend=enhance_w[:1]))
    cost = (base_wd + enh_wd.sum(axis=1)) * TRANSACTION_COST
    net_ret = port_ret - cost

    equity = pd.Series((1+net_ret).cumprod(), index=prices_bt.index)
    bm_ret_s = bm_bt.pct_change(fill_method=None).fillna(0)
    bm_eq = (1+bm_ret_s).cumprod()

    pr_s = pd.Series(net_ret, index=prices_bt.index)

    # 指标
    n = len(equity)
    _sl = lambda x: np.log(max(float(x), 1e-9))
    ann_f = 252/n
    ann_ret = float(np.exp(_sl(equity.iloc[-1])*ann_f)-1)
    ann_bm = float(np.exp(_sl(bm_eq.iloc[-1])*ann_f)-1)
    alpha = ann_ret - ann_bm
    total_ret = float(equity.iloc[-1]-1)
    total_bm = float(bm_eq.iloc[-1]-1)
    rm = equity.cummax()
    max_dd = float(((equity-rm)/rm).min())
    ex = pr_s - RISK_FREE_RATE/252
    sharpe = float(ex.mean()/ex.std()*np.sqrt(252)) if ex.std()>1e-8 else 0
    calmar = float(ann_ret/abs(max_dd)) if abs(max_dd)>1e-6 else 0
    act = pr_s - bm_ret_s
    ir = float(act.mean()/act.std()*np.sqrt(252)) if act.std()>1e-8 else 0
    wk = pr_s.resample("W").sum()
    win_rate = float((wk>0).sum()/max(len(wk),1))
    ann_vol = float(pr_s.std()*np.sqrt(252))
    down = pr_s[pr_s<0]
    down_vol = float(down.std()*np.sqrt(252)) if len(down)>0 and down.std()>1e-8 else 1
    sortino = float((ann_ret-RISK_FREE_RATE)/down_vol)
    tp = base_w_t1 + enhance_w.sum(axis=1)
    coverage = (tp>0.05).sum()/max(n,1)
    pk = equity.cummax()
    uw = (equity-pk)/pk
    uw_pct = (uw<-0.01).sum()/max(n,1)

    overall = {
        "ann_ret": round(ann_ret*100,2), "ann_bm": round(ann_bm*100,2),
        "alpha": round(alpha*100,2), "total_ret": round(total_ret*100,2),
        "total_bm": round(total_bm*100,2), "max_dd": round(max_dd*100,2),
        "sharpe": round(sharpe,3), "calmar": round(calmar,3),
        "sortino": round(sortino,3), "ir": round(ir,3),
        "win_rate": round(win_rate*100,1), "ann_vol": round(ann_vol*100,2),
        "coverage": round(coverage*100,1), "underwater_pct": round(uw_pct*100,1),
    }

    # 逐年
    yearly = {}
    for year in range(2016, 2027):
        mask_y = (prices_bt.index >= f"{year}-01-01") & (prices_bt.index <= f"{year}-12-31")
        if mask_y.sum() < 20: continue
        eq_y = equity[mask_y]; bm_y = bm_eq[mask_y]
        eqn = eq_y/eq_y.iloc[0]; bmn = bm_y/bm_y.iloc[0]
        yr = float(eqn.iloc[-1]-1)*100; yb = float(bmn.iloc[-1]-1)*100
        ydd = float(((eqn-eqn.cummax())/eqn.cummax()).min())*100
        ry = regime_bt[mask_y]; mr = ry.value_counts().index[0]
        mi = np.where(mask_y)[0]
        bc = sum(base_pnl[j] for j in mi)*100
        ec = sum(enhance_pnl[j] for j in mi)*100
        yearly[str(year)] = {"return": round(yr,2), "benchmark": round(yb,2),
            "alpha": round(yr-yb,2), "max_dd": round(ydd,2), "main_regime": mr,
            "base_contrib": round(bc,2), "enhance_contrib": round(ec,2)}

    # Regime 绩效
    regime_perf = {}
    for rn in ["BULL","RANGE","BEAR","CRASH"]:
        rmask = regime_bt == rn
        if rmask.sum() < 5: continue
        rr = pr_s[rmask]; rb = bm_ret_s[rmask]
        cr = float((1+rr).prod()-1)*100; cb = float((1+rb).prod()-1)*100
        regime_perf[rn] = {"days": int(rmask.sum()), "cum_ret": round(cr,2),
            "cum_bm": round(cb,2), "cum_alpha": round(cr-cb,2)}

    # 输出
    print(f"\n{'='*70}")
    print(f"  V4.2 vs V5.0 vs V5.1 对比")
    print(f"{'='*70}")

    # 加载 V4 和 V5 结果
    v4, v5 = {}, {}
    for fn, d in [("mr_10yr_results.json", v4), ("mr_v5_results.json", v5)]:
        fp = os.path.join(os.path.dirname(__file__), fn)
        if os.path.exists(fp):
            with open(fp, 'r', encoding='utf-8') as f:
                d.update(json.load(f))

    v4o = v4.get("overall", {})
    v5o = v5.get("overall", {})

    print(f"\n  {'指标':<18s} {'V4.2':>9s} {'V5.0':>9s} {'V5.1':>9s}")
    print(f"  {'-'*48}")
    for k in ["ann_ret","alpha","total_ret","max_dd","sharpe","calmar","ir","win_rate","coverage"]:
        v4v = v4o.get(k, 0)
        v5v = v5o.get(k, 0)
        v51v = overall.get(k, 0)
        suf = "%" if k not in ("sharpe","calmar","ir") else ""
        fmt = ".2f" if k not in ("sharpe","calmar","ir") else ".3f"
        print(f"  {k:<18s} {v4v:>8{fmt}}{suf} {v5v:>8{fmt}}{suf} {v51v:>8{fmt}}{suf}")

    print(f"\n  逐年明细:")
    print(f"  {'年份':<6s} {'V5.1':>8s} {'基准':>8s} {'Alpha':>8s} {'MaxDD':>8s} {'底仓':>8s} {'增强':>8s}")
    print(f"  {'-'*58}")
    for y, d in sorted(yearly.items()):
        print(f"  {y:<6s} {d['return']:>+7.2f}% {d['benchmark']:>+7.2f}% {d['alpha']:>+7.2f}% "
              f"{d['max_dd']:>7.2f}% {d['base_contrib']:>+7.2f}% {d['enhance_contrib']:>+7.2f}%")

    total_base = sum(d['base_contrib'] for d in yearly.values())
    total_enh = sum(d['enhance_contrib'] for d in yearly.values())
    print(f"  {'TOTAL':<6s} {'':<8s} {'':<8s} {'':<8s} {'':<8s} {total_base:>+7.2f}% {total_enh:>+7.2f}%")

    print(f"\n  分 Regime:")
    for rn in ["BULL","RANGE","BEAR","CRASH"]:
        if rn in regime_perf:
            d = regime_perf[rn]
            v4a = v4.get("regime_perf",{}).get(rn,{}).get("cum_alpha",0)
            v5a = v5.get("regime_perf",{}).get(rn,{}).get("cum_alpha",0)
            print(f"  {rn:<7s} {d['days']:>5d}d  V5.1:{d['cum_alpha']:>+8.1f}%  V5.0:{v5a:>+8.1f}%  V4.2:{v4a:>+8.1f}%")

    print(f"\n{'='*70}")
    if overall["alpha"] > 0:
        print(f"  ✅ V5.1 Alpha = {overall['alpha']:+.2f}%/年")
    else:
        print(f"  ❌ V5.1 Alpha = {overall['alpha']:+.2f}%/年")
    print(f"  Sharpe {overall['sharpe']:.3f} | MaxDD {overall['max_dd']:.2f}% | Sortino {overall['sortino']:.3f}")
    if v4o:
        print(f"  vs V4.2: Alpha {overall['alpha']-v4o.get('alpha',0):+.2f} Sharpe {overall['sharpe']-v4o.get('sharpe',0):+.3f}")
    print(f"{'='*70}")

    # 保存
    result = {"generated_at": datetime.now().isoformat(), "version": "V5.1",
              "overall": overall, "yearly": yearly, "regime_perf": regime_perf,
              "equity_dates": [d.strftime("%Y-%m-%d") for d in equity.index],
              "equity_values": [round(float(v),4) for v in equity],
              "bm_values": [round(float(v),4) for v in bm_eq]}
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  [SAVE] {RESULT_FILE}")
    return result


if __name__ == "__main__":
    from datetime import datetime
    t0 = time.time()
    run_backtest()
    print(f"  耗时: {time.time()-t0:.1f}s")
