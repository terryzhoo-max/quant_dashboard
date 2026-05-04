"""
AlphaCore · 均值回归策略 带市场状态切换的增强回测 V3.1
========================================================
核心升级：Regime Overlay（市场状态切换层）
- BULL 市（CSI300 > MA120）：持有宽基权重 60%，超跌均值仓位上限 25%
- RANGE 震荡（MA60 < CSI300 < MA120）：均值回归全激活，上限 75%
- BEAR 市（CSI300 < MA60）：均值回归全激活，但仅操作防御型标的，上限 65%

验证：基于最优参数 {N_trend=90, rsi14, rsi_buy=35, rsi_sell=70}
"""

import pandas as pd
import numpy as np
import os, json, sys, time, warnings
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

DAILY_PRICE_DIR = "data_lake/daily_prices"
BENCHMARK_CODE  = "510300.SH"
RISK_FREE_RATE  = 0.02
TRANSACTION_COST = 0.0010
RESULT_FILE = "mr_optimization_results.json"

FULL_START = "2022-01-01"
FULL_END   = "2026-03-27"

# 35只ETF
MR_POOL = [
    {"code": "510500.SH", "name": "中证500ETF",      "max_pos": 15, "defensive": False},
    {"code": "512100.SH", "name": "中证1000ETF",     "max_pos": 15, "defensive": False},
    {"code": "510300.SH", "name": "沪深300ETF",      "max_pos": 15, "defensive": True},
    {"code": "159915.SZ", "name": "创业板ETF",        "max_pos": 10, "defensive": False},
    {"code": "159949.SZ", "name": "创业板50ETF",      "max_pos": 10, "defensive": False},
    {"code": "588000.SH", "name": "科创50ETF",        "max_pos": 10, "defensive": False},
    {"code": "159781.SZ", "name": "科创创业ETF",      "max_pos": 8,  "defensive": False},
    {"code": "512480.SH", "name": "半导体ETF",        "max_pos": 8,  "defensive": False},
    {"code": "588200.SH", "name": "科创芯片ETF",      "max_pos": 7,  "defensive": False},
    {"code": "159995.SZ", "name": "芯片ETF",          "max_pos": 7,  "defensive": False},
    {"code": "159516.SZ", "name": "半导体设备ETF",    "max_pos": 6,  "defensive": False},
    {"code": "588220.SH", "name": "科创100ETF",       "max_pos": 8,  "defensive": False},
    {"code": "515000.SH", "name": "科技ETF",          "max_pos": 6,  "defensive": False},
    {"code": "515070.SH", "name": "人工智能AIETF",    "max_pos": 6,  "defensive": False},
    {"code": "159819.SZ", "name": "人工智能ETF",      "max_pos": 6,  "defensive": False},
    {"code": "515880.SH", "name": "通信ETF",          "max_pos": 6,  "defensive": False},
    {"code": "562500.SH", "name": "机器人ETF",        "max_pos": 5,  "defensive": False},
    {"code": "512400.SH", "name": "有色金属ETF",      "max_pos": 6,  "defensive": False},
    {"code": "516160.SH", "name": "新能源ETF",        "max_pos": 7,  "defensive": False},
    {"code": "515790.SH", "name": "光伏ETF",          "max_pos": 7,  "defensive": False},
    {"code": "562550.SH", "name": "绿电ETF",          "max_pos": 5,  "defensive": False},
    {"code": "159870.SZ", "name": "化工ETF",          "max_pos": 5,  "defensive": False},
    {"code": "512560.SH", "name": "军工ETF",          "max_pos": 7,  "defensive": True},
    {"code": "159218.SZ", "name": "卫星ETF",          "max_pos": 5,  "defensive": False},
    {"code": "159326.SZ", "name": "电网设备ETF",      "max_pos": 5,  "defensive": True},
    {"code": "159869.SZ", "name": "游戏ETF",          "max_pos": 5,  "defensive": False},
    {"code": "159851.SZ", "name": "金融科技ETF",      "max_pos": 5,  "defensive": False},
    {"code": "159941.SZ", "name": "纳指ETF",          "max_pos": 8,  "defensive": True},
    {"code": "513500.SH", "name": "标普500ETF",       "max_pos": 8,  "defensive": True},
    {"code": "515100.SH", "name": "红利低波100ETF",   "max_pos": 5,  "defensive": True},
    {"code": "159545.SZ", "name": "恒生红利低波ETF",  "max_pos": 5,  "defensive": True},
    {"code": "513130.SH", "name": "恒生科技ETF",      "max_pos": 5,  "defensive": False},
    {"code": "513970.SH", "name": "恒生消费ETF",      "max_pos": 5,  "defensive": False},
    {"code": "513090.SH", "name": "香港证券ETF",      "max_pos": 5,  "defensive": False},
    {"code": "513120.SH", "name": "港股创新药ETF",    "max_pos": 5,  "defensive": False},
]

BEST_PARAMS = {
    "N_trend": 90, "rsi_period": 14,
    "rsi_buy": 35, "rsi_sell": 70,
    "bias_buy": -2.0, "stop_loss": 0.08,
}


def load_prices(codes, start, end):
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
            col = 'adj_close' if 'adj_close' in df.columns else 'close'
            frames[code] = df.set_index('trade_date')[col].rename(code)
        except: pass
    if not frames:
        raise FileNotFoundError("无数据")
    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


def signal_state_machine(price_arr, p):
    n, nt, rp = len(price_arr), p["N_trend"], p["rsi_period"]
    if n < nt + rp + 5:
        return np.zeros(n)

    ma_t = np.full(n, np.nan)
    for i in range(nt-1, n):
        ma_t[i] = price_arr[i-nt+1:i+1].mean()

    diff = np.diff(price_arr, prepend=price_arr[0])
    gain, loss = np.where(diff>0,diff,0.), np.where(diff<0,-diff,0.)
    avg_g, avg_l = np.full(n,np.nan), np.full(n,np.nan)
    if n > rp:
        avg_g[rp], avg_l[rp] = gain[1:rp+1].mean(), loss[1:rp+1].mean()
        for i in range(rp+1, n):
            avg_g[i] = (avg_g[i-1]*(rp-1)+gain[i])/rp
            avg_l[i] = (avg_l[i-1]*(rp-1)+loss[i])/rp
    with np.errstate(invalid='ignore', divide='ignore'):
        rsi = 100 - 100/(1 + np.where(avg_l<1e-8, 1e8, avg_g/avg_l))

    with np.errstate(invalid='ignore', divide='ignore'):
        bias = np.where(ma_t>0, (price_arr-ma_t)/ma_t*100, np.nan)

    sig, in_pos, entry_px = np.zeros(n), False, 0.
    for i in range(1, n):
        if np.isnan(ma_t[i]) or np.isnan(rsi[i]):
            continue
        if not in_pos:
            if (price_arr[i] > ma_t[i] and
                (rsi[i] <= p["rsi_buy"] or
                 (not np.isnan(bias[i]) and bias[i] <= p["bias_buy"]))):
                in_pos, entry_px, sig[i] = True, price_arr[i], 1.
        else:
            cumret = price_arr[i]/entry_px - 1
            sl_val = abs(p.get("stop_loss", 0.08))
            if (rsi[i] >= p["rsi_sell"] or
                cumret < -sl_val or
                price_arr[i] < ma_t[i]*0.97):
                in_pos = False
            else:
                sig[i] = 1.
    return sig


def run_regime_backtest():
    """带市场状态切换的全样本回测，输出更新的 JSON"""
    all_codes = list(dict.fromkeys([e["code"] for e in MR_POOL] + [BENCHMARK_CODE]))
    prices    = load_prices(all_codes, "2021-06-01", FULL_END)
    bm_series = prices[BENCHMARK_CODE].copy()

    etf_cols  = [c for c in prices.columns if c != BENCHMARK_CODE]
    etf_mat   = prices[etf_cols]

    # 市场状态识别（MA60/MA120 on CSI300 = 510300.SH）
    bm_vals   = bm_series.values
    n_full    = len(bm_vals)
    ma60      = pd.Series(bm_vals).rolling(60).mean().values
    ma120     = pd.Series(bm_vals).rolling(120).mean().values

    regime = np.full(n_full, 'RANGE', dtype=object)
    for i in range(n_full):
        if np.isnan(ma60[i]) or np.isnan(ma120[i]):
            continue
        if bm_vals[i] > ma120[i]:
            regime[i] = 'BULL'
        elif bm_vals[i] < ma60[i]:
            regime[i] = 'BEAR'

    # 筛选 2022-01-01 以后
    idx_start = prices.index.searchsorted(pd.Timestamp("2022-01-01"))
    prices_bt = prices.iloc[idx_start:]
    bm_bt     = bm_series.iloc[idx_start:]
    regime_bt = regime[idx_start:]
    N         = len(prices_bt)

    # 生成信号矩阵
    p = BEST_PARAMS
    max_pos_map   = {e["code"]: e["max_pos"]/100. for e in MR_POOL}
    defensive_set = {e["code"] for e in MR_POOL if e["defensive"]}
    sig_mat = pd.DataFrame(0., index=prices_bt.index, columns=etf_cols)

    for code in etf_cols:
        arr = prices_bt[code].ffill().bfill().values.astype(float)
        sig = signal_state_machine(arr, p)
        sig_mat[code] = sig

    # Regime Overlay 权重计算
    sig_t1   = sig_mat.shift(1).fillna(0)
    regime_s = pd.Series(regime_bt, index=prices_bt.index)

    final_w = np.zeros((N, len(etf_cols)))
    max_pos_arr = np.array([max_pos_map.get(c, 0.10) for c in etf_cols])

    for i in range(N):
        reg = regime_s.iloc[i]
        row_sig = sig_t1.iloc[i].values

        if reg == 'BULL':
            # 牛市：只允许防御性标的，总上限40%（留空间给指数被动持有）
            mask = np.array([1 if c in defensive_set else 0 for c in etf_cols])
            eff_sig = row_sig * mask
            total_cap = 0.40
        elif reg == 'BEAR':
            # 熊市：全激活，总上限65%，偏重防御
            eff_sig   = row_sig
            total_cap = 0.65
        else:  # RANGE
            # 震荡：全激活，总上限80%
            eff_sig   = row_sig
            total_cap = 0.80

        raw = eff_sig * max_pos_arr
        s   = raw.sum()
        if s > 0:
            scale = min(total_cap / s, 1.0)
            final_w[i] = raw * scale
        # else: all zeros

    # 每日收益
    ret_mat  = prices_bt[etf_cols].pct_change(fill_method=None).fillna(0).values
    port_ret = (final_w * ret_mat).sum(axis=1)
    w_diff   = np.abs(np.diff(final_w, axis=0, prepend=final_w[:1]))
    cost     = w_diff.sum(axis=1) * TRANSACTION_COST
    net_ret  = port_ret - cost

    equity   = pd.Series((1+net_ret).cumprod(), index=prices_bt.index)
    bm_r     = bm_bt.pct_change(fill_method=None).fillna(0)
    bm_eq    = (1+bm_r).cumprod()

    # KPI
    n   = len(equity)
    ann = 252/n
    sl  = lambda x: np.log(max(float(x), 1e-9))
    ann_ret = float(np.exp(sl(equity.iloc[-1]) * ann) - 1)
    ann_bm  = float(np.exp(sl(bm_eq.iloc[-1])  * ann) - 1)
    alpha   = ann_ret - ann_bm
    max_dd  = float(((equity - equity.cummax())/equity.cummax()).min())
    ex      = pd.Series(net_ret) - RISK_FREE_RATE/252
    sharpe  = float(ex.mean()/ex.std()*np.sqrt(252)) if ex.std()>1e-8 else 0.
    calmar  = float(ann_ret/abs(max_dd)) if abs(max_dd)>1e-6 else 0.
    act     = pd.Series(net_ret) - bm_r.values
    ir      = float(act.mean()/act.std()*np.sqrt(252)) if act.std()>1e-6 else 0.
    total_ret = float(equity.iloc[-1]-1)
    total_bm  = float(bm_eq.iloc[-1]-1)

    kpi = {
        "ann_ret":   round(ann_ret*100, 2),
        "ann_bm":    round(ann_bm*100, 2),
        "alpha":     round(alpha*100, 2),
        "total_ret": round(total_ret*100, 2),
        "total_bm":  round(total_bm*100, 2),
        "max_dd":    round(max_dd*100, 2),
        "sharpe":    round(sharpe, 3),
        "calmar":    round(calmar, 3),
        "ir":        round(ir, 3),
    }

    print("=== Regime Overlay 全样本 (2022-2026) 回测结果 ===")
    for k, v in kpi.items():
        print(f"  {k:12s}: {v}")

    # 更新 JSON
    with open(RESULT_FILE, 'r', encoding='utf-8') as f:
        r = json.load(f)

    r["regime_overlay_kpi"]    = kpi
    r["regime_equity_dates"]   = [d.strftime("%Y-%m-%d") for d in equity.index.tolist()]
    r["regime_equity_values"]  = [round(float(v),4) for v in equity.tolist()]
    r["regime_bm_values"]      = [round(float(v),4) for v in bm_eq.tolist()]
    r["regime_labels"]         = list(regime_bt)

    with open(RESULT_FILE, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=2)

    print(f"\n[SAVE] 已写入 Regime 覆盖结果到 {RESULT_FILE}")
    return kpi


if __name__ == "__main__":
    run_regime_backtest()
