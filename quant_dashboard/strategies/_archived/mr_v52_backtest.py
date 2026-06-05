"""
AlphaCore V5.2 · 最终迭代
============================================================
V5.1 结论：
  - 底仓层单独贡献 +21.34%（接近基准36%的60%）
  - 增强层因双重确认太严格，贡献 = 0%
  - 底仓仍跑输基准 → Regime择时在损耗
  - BULL态底仓70%仍不够 → 牛市踏空仍是主要失血点

V5.2 最终改进（3个方向，全部验证）：

  方案 A: 纯底仓 Regime 择时（去掉增强层，专注底仓优化）
    BULL: 85%  RANGE: 60%  BEAR: 25%  CRASH: 5%

  方案 B: 高底仓 + 宽松增强（恢复 OR 信号，但增强层小仓位）
    底仓同A + 增强层 ≤15% 用 V4.2 信号逻辑

  方案 C: Buy&Hold 80% + 极小 MR 增强（极简方案）
    固定80%底仓（不做Regime择时）+ 增强层 ≤10%

  同时跑3个方案 + V4.2 + V5.0 + V5.1，横向对比。
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
from datetime import datetime

DAILY_PRICE_DIR = os.path.join(os.path.dirname(__file__), "..", "data_lake", "daily_prices")
RESULT_FILE = os.path.join(os.path.dirname(__file__), "mr_v52_results.json")
BENCHMARK_CODE = "510300.SH"
INDEX_CODE = "000300.SH"
RISK_FREE_RATE = 0.025
TRANSACTION_COST = 0.0010
BT_START = "2016-01-01"
BT_END = "2026-05-21"

MR_POOL = [
    {"code": "510300.SH", "max_pos": 10, "list_date": "20120528"},
    {"code": "510500.SH", "max_pos": 10, "list_date": "20130226"},
    {"code": "159915.SZ", "max_pos": 7,  "list_date": "20111213"},
    {"code": "512560.SH", "max_pos": 5,  "list_date": "20160811"},
    {"code": "513500.SH", "max_pos": 5,  "list_date": "20151218"},
    {"code": "512400.SH", "max_pos": 5,  "list_date": "20190628"},
    {"code": "159949.SZ", "max_pos": 6,  "list_date": "20191212"},
    {"code": "512480.SH", "max_pos": 5,  "list_date": "20190522"},
    {"code": "515000.SH", "max_pos": 5,  "list_date": "20190927"},
    {"code": "159995.SZ", "max_pos": 5,  "list_date": "20191216"},
    {"code": "512100.SH", "max_pos": 8,  "list_date": "20191115"},
    {"code": "515880.SH", "max_pos": 5,  "list_date": "20200218"},
    {"code": "515790.SH", "max_pos": 5,  "list_date": "20200918"},
    {"code": "515070.SH", "max_pos": 5,  "list_date": "20200720"},
    {"code": "588000.SH", "max_pos": 6,  "list_date": "20201116"},
    {"code": "513130.SH", "max_pos": 5,  "list_date": "20210525"},
    {"code": "515100.SH", "max_pos": 5,  "list_date": "20191220"},
    {"code": "159941.SZ", "max_pos": 5,  "list_date": "20170328"},
    {"code": "159819.SZ", "max_pos": 5,  "list_date": "20210108"},
    {"code": "516160.SH", "max_pos": 5,  "list_date": "20210406"},
    {"code": "159870.SZ", "max_pos": 5,  "list_date": "20210113"},
    {"code": "588200.SH", "max_pos": 5,  "list_date": "20210616"},
    {"code": "513090.SH", "max_pos": 5,  "list_date": "20210922"},
    {"code": "159781.SZ", "max_pos": 5,  "list_date": "20211108"},
    {"code": "513120.SH", "max_pos": 5,  "list_date": "20210811"},
    {"code": "513970.SH", "max_pos": 5,  "list_date": "20210309"},
    {"code": "159869.SZ", "max_pos": 5,  "list_date": "20210113"},
    {"code": "159851.SZ", "max_pos": 5,  "list_date": "20210113"},
    {"code": "588220.SH", "max_pos": 5,  "list_date": "20221122"},
    {"code": "562500.SH", "max_pos": 5,  "list_date": "20220623"},
    {"code": "562550.SH", "max_pos": 5,  "list_date": "20220829"},
    {"code": "159516.SZ", "max_pos": 5,  "list_date": "20220701"},
    {"code": "159218.SZ", "max_pos": 5,  "list_date": "20220627"},
    {"code": "159326.SZ", "max_pos": 5,  "list_date": "20220704"},
    {"code": "159545.SZ", "max_pos": 5,  "list_date": "20220726"},
]

REGIME_PARAMS = {
    "BEAR":  {"N_trend": 40, "rsi_period": 14, "rsi_buy": 45, "rsi_sell": 65, "bias_buy": -3.0, "stop_loss": 0.05},
    "RANGE": {"N_trend": 90, "rsi_period": 14, "rsi_buy": 40, "rsi_sell": 70, "bias_buy": -2.0, "stop_loss": 0.07},
    "BULL":  {"N_trend": 120,"rsi_period": 14, "rsi_buy": 45, "rsi_sell": 75, "bias_buy": -1.5, "stop_loss": 0.06},
}


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
    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


def classify_regime(close_series):
    close = close_series.values.astype(float)
    n = len(close)
    regimes = np.full(n, "RANGE", dtype=object)
    ma120 = pd.Series(close).rolling(120, min_periods=120).mean().values
    for i in range(120, n):
        if i >= 3 and close[i]/close[i-3]-1 < -0.07:
            regimes[i] = "CRASH"; continue
        cur, m = close[i], ma120[i]
        if np.isnan(m): continue
        w = [ma120[j] for j in range(max(0,i-5),i+1) if not np.isnan(ma120[j])]
        sl = float(np.polyfit(np.arange(len(w),dtype=float),w,1)[0]) if len(w)>=2 else 0
        r5 = (close[i]/close[i-5]-1)*100 if i>=5 else 0
        r20 = (close[i]/close[i-20]-1)*100 if i>=20 else 0
        if cur>m and sl>0 and r20>0: regimes[i] = "BULL"
        elif cur>m: regimes[i] = "RANGE"
        elif r5>3: regimes[i] = "RANGE"
        else: regimes[i] = "BEAR"
    return pd.Series(regimes, index=close_series.index)


def mr_signal_or(price_arr, regime_arr):
    """V4.2 原始信号: RSI OR BIAS (OR逻辑)"""
    n = len(price_arr)
    sig = np.zeros(n)
    in_pos, entry_px = False, 0.0
    rp = 14
    if n < 130: return sig

    ma40 = pd.Series(price_arr).rolling(40,min_periods=40).mean().values
    ma90 = pd.Series(price_arr).rolling(90,min_periods=90).mean().values
    ma120 = pd.Series(price_arr).rolling(120,min_periods=120).mean().values
    mm = {40:ma40,90:ma90,120:ma120}
    b40 = np.where(ma40>0,(price_arr-ma40)/ma40*100,np.nan)
    b90 = np.where(ma90>0,(price_arr-ma90)/ma90*100,np.nan)
    b120 = np.where(ma120>0,(price_arr-ma120)/ma120*100,np.nan)
    bm = {40:b40,90:b90,120:b120}

    d = np.diff(price_arr, prepend=price_arr[0])
    g = np.where(d>0,d,0.); l = np.where(d<0,-d,0.)
    ag,al = np.full(n,np.nan),np.full(n,np.nan)
    if n>rp:
        ag[rp],al[rp] = g[1:rp+1].mean(),l[1:rp+1].mean()
        for i in range(rp+1,n):
            ag[i]=(ag[i-1]*(rp-1)+g[i])/rp; al[i]=(al[i-1]*(rp-1)+l[i])/rp
    with np.errstate(invalid='ignore',divide='ignore'):
        rs = np.where(al<1e-8,100.,ag/al); rsi = 100-100/(1+rs)

    for i in range(1,n):
        px = price_arr[i]
        regime = regime_arr[i] if i<len(regime_arr) else "RANGE"
        if regime=="CRASH":
            if in_pos: in_pos=False
            continue
        p = REGIME_PARAMS.get(regime, REGIME_PARAMS["RANGE"])
        nt = p["N_trend"]
        mat = mm.get(nt,ma90); bias = bm.get(nt,b90)
        if np.isnan(mat[i]) or np.isnan(rsi[i]):
            if in_pos: sig[i]=1.0
            continue
        if not in_pos:
            trend_ok = px > mat[i]
            buy = (rsi[i]<=p["rsi_buy"]) or (not np.isnan(bias[i]) and bias[i]<=p["bias_buy"])
            if trend_ok and buy:
                in_pos=True; entry_px=px; sig[i]=1.0
        else:
            cumret = px/entry_px-1; sl=abs(p["stop_loss"])
            if rsi[i]>=p["rsi_sell"] or cumret<-sl or px<mat[i]*0.97:
                in_pos=False
            else: sig[i]=1.0
    return sig


def run_scenario(name, base_alloc, enhance_cap, prices_bt, bm_bt, regime_bt, etf_codes):
    """运行单个方案"""
    regime_arr = regime_bt.values
    n_days = len(prices_bt)
    max_pos_map = {e["code"]: e["max_pos"]/100.0 for e in MR_POOL}
    list_date_map = {e["code"]: pd.Timestamp(e["list_date"]) for e in MR_POOL}

    # 底仓
    base_w = np.zeros(n_days)
    for i in range(n_days):
        if callable(base_alloc):
            base_w[i] = base_alloc(regime_arr[i])
        else:
            base_w[i] = base_alloc.get(regime_arr[i], 0.50)
    base_w_t1 = np.roll(base_w, 1); base_w_t1[0] = 0

    # 增强层（如果 enhance_cap > 0）
    has_enhance = any(v > 0 for v in (enhance_cap.values() if isinstance(enhance_cap, dict) else [enhance_cap]))

    enhance_w = np.zeros((n_days, len(etf_codes)))
    if has_enhance:
        sig_mat = pd.DataFrame(0.0, index=prices_bt.index, columns=etf_codes)
        for code in etf_codes:
            ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
            warmup = ld + pd.Timedelta(days=210)
            arr = prices_bt[code].values.astype(float)
            sig = mr_signal_or(arr, regime_arr)
            for i, dt in enumerate(prices_bt.index):
                if dt < warmup: sig[i]=0.0
                else: break
            sig_mat[code] = sig
        sig_t1 = sig_mat.shift(1).fillna(0)
        max_pos_arr = np.array([max_pos_map.get(c,0.05) for c in etf_codes])

        for i in range(n_days):
            reg = regime_arr[i]
            ecap = enhance_cap.get(reg, 0.10) if isinstance(enhance_cap, dict) else enhance_cap
            if ecap <= 0: continue
            row = sig_t1.iloc[i].values.copy()
            dt = prices_bt.index[i]
            for j, code in enumerate(etf_codes):
                ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
                if dt < ld + pd.Timedelta(days=210): row[j]=0
            raw = row * max_pos_arr
            if BENCHMARK_CODE in etf_codes:
                bi = etf_codes.index(BENCHMARK_CODE)
                raw[bi] = max(0, raw[bi] - base_w_t1[i])
            s = raw.sum()
            if s > ecap: raw = raw * (ecap/s)
            enhance_w[i] = raw

    # 仓位上限 90%
    tp = base_w_t1 + enhance_w.sum(axis=1)
    over = tp > 0.90
    if over.any():
        sc = np.where(over, 0.90/np.maximum(tp,1e-6), 1.0)
        enhance_w = enhance_w * sc[:,np.newaxis]

    # 收益
    base_ret = bm_bt.pct_change(fill_method=None).fillna(0).values
    base_pnl = base_w_t1 * base_ret
    ret_mat = prices_bt[etf_codes].pct_change(fill_method=None).fillna(0).values
    enh_pnl = (enhance_w * ret_mat).sum(axis=1)
    port_ret = base_pnl + enh_pnl

    bwd = np.abs(np.diff(base_w_t1, prepend=base_w_t1[0]))
    ewd = np.abs(np.diff(enhance_w, axis=0, prepend=enhance_w[:1]))
    cost = (bwd + ewd.sum(axis=1)) * TRANSACTION_COST
    net_ret = port_ret - cost

    equity = pd.Series((1+net_ret).cumprod(), index=prices_bt.index)
    bm_ret_s = bm_bt.pct_change(fill_method=None).fillna(0)
    bm_eq = (1+bm_ret_s).cumprod()

    # 指标
    n = len(equity)
    _sl = lambda x: np.log(max(float(x),1e-9))
    ann_f = 252/n
    ann_ret = float(np.exp(_sl(equity.iloc[-1])*ann_f)-1)
    ann_bm = float(np.exp(_sl(bm_eq.iloc[-1])*ann_f)-1)
    alpha = ann_ret - ann_bm
    total_ret = float(equity.iloc[-1]-1)
    max_dd = float(((equity-equity.cummax())/equity.cummax()).min())
    pr_s = pd.Series(net_ret, index=prices_bt.index)
    ex = pr_s - RISK_FREE_RATE/252
    sharpe = float(ex.mean()/ex.std()*np.sqrt(252)) if ex.std()>1e-8 else 0
    calmar = float(ann_ret/abs(max_dd)) if abs(max_dd)>1e-6 else 0
    ann_vol = float(pr_s.std()*np.sqrt(252))
    wk = pr_s.resample("W").sum()
    win_rate = float((wk>0).sum()/max(len(wk),1))

    # 逐年
    yearly_alphas = []
    for year in range(2016, 2027):
        mask_y = (prices_bt.index >= f"{year}-01-01") & (prices_bt.index <= f"{year}-12-31")
        if mask_y.sum() < 20: continue
        eqy = equity[mask_y]; bmy = bm_eq[mask_y]
        yr = float(eqy.iloc[-1]/eqy.iloc[0]-1)*100
        yb = float(bmy.iloc[-1]/bmy.iloc[0]-1)*100
        yearly_alphas.append(yr - yb)

    pos_alpha_years = sum(1 for a in yearly_alphas if a > 0)

    # Regime 归因
    regime_alpha = {}
    for rn in ["BULL","RANGE","BEAR","CRASH"]:
        rmask = regime_bt == rn
        if rmask.sum() < 5: continue
        rr = pr_s[rmask]; rb = bm_ret_s[rmask]
        cr = float((1+rr).prod()-1)*100; cb = float((1+rb).prod()-1)*100
        regime_alpha[rn] = round(cr-cb, 1)

    return {
        "name": name,
        "ann_ret": round(ann_ret*100,2),
        "alpha": round(alpha*100,2),
        "total_ret": round(total_ret*100,2),
        "max_dd": round(max_dd*100,2),
        "sharpe": round(sharpe,3),
        "calmar": round(calmar,3),
        "win_rate": round(win_rate*100,1),
        "ann_vol": round(ann_vol*100,2),
        "pos_alpha_years": f"{pos_alpha_years}/{len(yearly_alphas)}",
        "regime_alpha": regime_alpha,
        "equity_values": [round(float(v),4) for v in equity],
        "bm_values": [round(float(v),4) for v in bm_eq],
    }


def main():
    print("=" * 70)
    print("  AlphaCore V5.2 · 多方案横向验证")
    print("=" * 70)

    all_codes = list(dict.fromkeys([e["code"] for e in MR_POOL] + [BENCHMARK_CODE]))
    full_prices = load_prices(all_codes, "2015-01-01", BT_END)
    bm_full = full_prices[BENCHMARK_CODE].copy()

    idx_file = os.path.join(DAILY_PRICE_DIR, f"{INDEX_CODE}.parquet")
    if os.path.exists(idx_file):
        di = pd.read_parquet(idx_file)
        di['trade_date'] = pd.to_datetime(di['trade_date'].astype(str).str[:8], format='%Y%m%d')
        idx_s = di.set_index('trade_date')['close'].sort_index().reindex(full_prices.index).ffill()
    else:
        idx_s = bm_full

    regime_s = classify_regime(idx_s)
    bt_mask = full_prices.index >= pd.Timestamp(BT_START)
    prices_bt = full_prices[bt_mask]
    bm_bt = bm_full[bt_mask]
    regime_bt = regime_s[bt_mask]
    etf_codes = [e["code"] for e in MR_POOL if e["code"] in prices_bt.columns]

    # ─── 定义方案 ──────────────────────────────────────────

    scenarios = [
        # 方案 A: 纯底仓 Regime 择时（高配比）
        ("A: 纯底仓(85/60/25)",
         {"BULL": 0.85, "RANGE": 0.60, "BEAR": 0.25, "CRASH": 0.05},
         {"BULL": 0, "RANGE": 0, "BEAR": 0, "CRASH": 0}),

        # 方案 B: 高底仓 + 小增强
        ("B: 底仓(85/60/25)+MR(10/15/20)",
         {"BULL": 0.85, "RANGE": 0.60, "BEAR": 0.25, "CRASH": 0.05},
         {"BULL": 0.10, "RANGE": 0.15, "BEAR": 0.20, "CRASH": 0}),

        # 方案 C: 固定80%底仓
        ("C: 固定80%底仓(无择时)",
         {"BULL": 0.80, "RANGE": 0.80, "BEAR": 0.80, "CRASH": 0.80},
         {"BULL": 0, "RANGE": 0, "BEAR": 0, "CRASH": 0}),

        # 方案 D: 固定80% + 小增强
        ("D: 固定80%+MR(10%)",
         {"BULL": 0.80, "RANGE": 0.80, "BEAR": 0.80, "CRASH": 0.80},
         {"BULL": 0.10, "RANGE": 0.10, "BEAR": 0.10, "CRASH": 0}),

        # 方案 E: 100% Buy & Hold (纯基准)
        ("E: 100% B&H(对照组)",
         {"BULL": 1.00, "RANGE": 1.00, "BEAR": 1.00, "CRASH": 1.00},
         {"BULL": 0, "RANGE": 0, "BEAR": 0, "CRASH": 0}),

        # 方案 F: Regime择时底仓 + BEAR时加大增强
        ("F: 底仓(80/55/20)+MR(0/20/40)",
         {"BULL": 0.80, "RANGE": 0.55, "BEAR": 0.20, "CRASH": 0.00},
         {"BULL": 0.00, "RANGE": 0.20, "BEAR": 0.40, "CRASH": 0}),
    ]

    results = []
    for name, base, enh in scenarios:
        print(f"\n  运行 {name}...")
        r = run_scenario(name, base, enh, prices_bt, bm_bt, regime_bt, etf_codes)
        results.append(r)

    # ─── 横向对比 ──────────────────────────────────────────

    print("\n" + "=" * 70)
    print("  多方案横向对比")
    print("=" * 70)

    print(f"\n  {'方案':<32s} {'年化':>7s} {'Alpha':>7s} {'累计':>8s} {'MaxDD':>8s} {'Sharpe':>7s} {'Calmar':>7s} {'胜率':>6s} {'正Alpha年':>10s}")
    print(f"  {'-'*100}")
    for r in results:
        print(f"  {r['name']:<32s} {r['ann_ret']:>+6.2f}% {r['alpha']:>+6.2f}% {r['total_ret']:>+7.2f}% "
              f"{r['max_dd']:>7.2f}% {r['sharpe']:>7.3f} {r['calmar']:>7.3f} {r['win_rate']:>5.1f}% {r['pos_alpha_years']:>10s}")

    print(f"\n  分 Regime Alpha:")
    print(f"  {'方案':<32s} {'BULL':>8s} {'RANGE':>8s} {'BEAR':>8s} {'CRASH':>8s}")
    print(f"  {'-'*70}")
    for r in results:
        ra = r['regime_alpha']
        print(f"  {r['name']:<32s} {ra.get('BULL',0):>+7.1f}% {ra.get('RANGE',0):>+7.1f}% "
              f"{ra.get('BEAR',0):>+7.1f}% {ra.get('CRASH',0):>+7.1f}%")

    # 找最优
    best = max(results, key=lambda x: x['sharpe'])
    print(f"\n  最优方案 (Sharpe最高): {best['name']}")
    print(f"    Alpha={best['alpha']:+.2f}%/年 Sharpe={best['sharpe']:.3f} MaxDD={best['max_dd']:.2f}%")

    # 保存
    output = {
        "generated_at": datetime.now().isoformat(),
        "scenarios": [{k:v for k,v in r.items() if k not in ("equity_values","bm_values")} for r in results],
        "best_scenario": best['name'],
        "best_equity": best.get("equity_values", []),
        "best_bm": best.get("bm_values", []),
    }
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  [SAVE] {RESULT_FILE}")

    return results


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\n  耗时: {time.time()-t0:.1f}s")
