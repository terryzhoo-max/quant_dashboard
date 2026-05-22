"""
AlphaCore · 均值回归 V5.0 · "指数底仓 + MR增强" 双层架构
============================================================
改进逻辑（基于10年回测诊断）：

V4.2 的致命缺陷：
  - BULL 限仓35%+仅防御标的 → 牛市踏空 -347%
  - RANGE 虽然80%上限但实际持仓低 → 震荡市也漏收益 -141%
  - 策略本质是"波动率交易"，不能替代被动持有

V5.0 架构：
  Layer 1 — 被动底仓（Passive Base）
    始终持有沪深300ETF，仓位随 Regime 调节
    BULL: 55%  RANGE: 35%  BEAR: 15%  CRASH: 0%
    → 解决牛市踏空问题

  Layer 2 — MR增强仓（Enhancement）
    在底仓之上，用均值回归信号做战术加仓
    BULL: ≤25%  RANGE: ≤45%  BEAR: ≤50%  CRASH: 0%
    → 保留均值回归在熊市/震荡市的Alpha能力

  Total = Base + Enhancement ≤ 90%

  额外改进：
  - 取消 BULL 态"仅防御标的"限制（底仓已提供指数暴露）
  - 最小持仓期 5天（减少止损鞭打）
  - 分 3 档渐进式建仓（信号→1/3仓，确认→2/3仓，强信号→满仓）

Author: AlphaCore V5.0 | 2026-05
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

DAILY_PRICE_DIR = os.path.join(os.path.dirname(__file__), "..", "data_lake", "daily_prices")
RESULT_FILE_V5 = os.path.join(os.path.dirname(__file__), "mr_v5_results.json")
RESULT_FILE_V4 = os.path.join(os.path.dirname(__file__), "mr_10yr_results.json")

BENCHMARK_CODE = "510300.SH"
INDEX_CODE     = "000300.SH"
BASE_ETF       = "510300.SH"       # 底仓标的
RISK_FREE_RATE = 0.025
TRANSACTION_COST = 0.0010
BT_START = "2016-01-01"
BT_END   = "2026-05-21"

# ═══════════════════════════════════════════════════════════
#  V5.0 双层参数体系
# ═══════════════════════════════════════════════════════════

# Layer 1: 被动底仓配置（先验推导，非优化）
#   BULL  55% — 牛市保持市场暴露，不踏空
#   RANGE 35% — 震荡市中等暴露
#   BEAR  15% — 熊市保留小仓位，避免完全错过反弹
#   CRASH  0% — 崩盘全现金
BASE_ALLOC = {
    "BULL":  0.55,
    "RANGE": 0.35,
    "BEAR":  0.15,
    "CRASH": 0.00,
}

# Layer 2: MR增强仓上限
#   BULL  25% — 轻增强，市场本身在涨
#   RANGE 45% — 主战场
#   BEAR  50% — 均值回归最有效的区间
#   CRASH  0% — 禁入
ENHANCE_CAP = {
    "BULL":  0.25,
    "RANGE": 0.45,
    "BEAR":  0.50,
    "CRASH": 0.00,
}

# MR 信号参数（同 V4.2 先验参数）
REGIME_PARAMS = {
    "BEAR":  {"N_trend": 40, "rsi_period": 14, "rsi_buy": 45, "rsi_sell": 65,
              "bias_buy": -3.0, "stop_loss": 0.05},
    "RANGE": {"N_trend": 90, "rsi_period": 14, "rsi_buy": 40, "rsi_sell": 70,
              "bias_buy": -2.0, "stop_loss": 0.07},
    "BULL":  {"N_trend": 120, "rsi_period": 14, "rsi_buy": 45, "rsi_sell": 75,
              "bias_buy": -1.5, "stop_loss": 0.06},
}

# 最小持仓天数（防鞭打）
MIN_HOLD_DAYS = 5

# ─── 标的池（同 V4.2，含上市日期）──────────────────────────────────────────

MR_POOL = [
    {"code": "510300.SH", "name": "沪深300ETF",     "max_pos": 12, "list_date": "20120528"},
    {"code": "510500.SH", "name": "中证500ETF",     "max_pos": 12, "list_date": "20130226"},
    {"code": "159915.SZ", "name": "创业板ETF",       "max_pos": 8,  "list_date": "20111213"},
    {"code": "512560.SH", "name": "军工ETF",         "max_pos": 6,  "list_date": "20160811"},
    {"code": "513500.SH", "name": "标普500ETF",      "max_pos": 6,  "list_date": "20151218"},
    {"code": "512400.SH", "name": "有色金属ETF",     "max_pos": 5,  "list_date": "20190628"},
    {"code": "159949.SZ", "name": "创业板50ETF",     "max_pos": 8,  "list_date": "20191212"},
    {"code": "512480.SH", "name": "半导体ETF",       "max_pos": 6,  "list_date": "20190522"},
    {"code": "515000.SH", "name": "科技ETF",         "max_pos": 5,  "list_date": "20190927"},
    {"code": "159995.SZ", "name": "芯片ETF",         "max_pos": 5,  "list_date": "20191216"},
    {"code": "512100.SH", "name": "中证1000ETF",    "max_pos": 10, "list_date": "20191115"},
    {"code": "515880.SH", "name": "通信ETF",         "max_pos": 5,  "list_date": "20200218"},
    {"code": "515790.SH", "name": "光伏ETF",         "max_pos": 5,  "list_date": "20200918"},
    {"code": "515070.SH", "name": "人工智能AIETF",   "max_pos": 5,  "list_date": "20200720"},
    {"code": "588000.SH", "name": "科创50ETF",       "max_pos": 8,  "list_date": "20201116"},
    {"code": "513130.SH", "name": "恒生科技ETF",     "max_pos": 5,  "list_date": "20210525"},
    {"code": "515100.SH", "name": "红利低波100ETF",  "max_pos": 5,  "list_date": "20191220"},
    {"code": "159941.SZ", "name": "纳指ETF",         "max_pos": 6,  "list_date": "20170328"},
    {"code": "159819.SZ", "name": "人工智能ETF",     "max_pos": 5,  "list_date": "20210108"},
    {"code": "516160.SH", "name": "新能源ETF",       "max_pos": 5,  "list_date": "20210406"},
    {"code": "159870.SZ", "name": "化工ETF",         "max_pos": 5,  "list_date": "20210113"},
    {"code": "588200.SH", "name": "科创芯片ETF",     "max_pos": 5,  "list_date": "20210616"},
    {"code": "513090.SH", "name": "香港证券ETF",     "max_pos": 5,  "list_date": "20210922"},
    {"code": "159781.SZ", "name": "科创创业ETF",     "max_pos": 6,  "list_date": "20211108"},
    {"code": "513120.SH", "name": "港股创新药ETF",   "max_pos": 5,  "list_date": "20210811"},
    {"code": "513970.SH", "name": "恒生消费ETF",     "max_pos": 5,  "list_date": "20210309"},
    {"code": "159869.SZ", "name": "游戏ETF",         "max_pos": 5,  "list_date": "20210113"},
    {"code": "159851.SZ", "name": "金融科技ETF",     "max_pos": 5,  "list_date": "20210113"},
    {"code": "588220.SH", "name": "科创100ETF",      "max_pos": 6,  "list_date": "20221122"},
    {"code": "562500.SH", "name": "机器人ETF",       "max_pos": 5,  "list_date": "20220623"},
    {"code": "562550.SH", "name": "绿电ETF",         "max_pos": 5,  "list_date": "20220829"},
    {"code": "159516.SZ", "name": "半导体设备ETF",   "max_pos": 5,  "list_date": "20220701"},
    {"code": "159218.SZ", "name": "卫星ETF",         "max_pos": 5,  "list_date": "20220627"},
    {"code": "159326.SZ", "name": "电网设备ETF",     "max_pos": 5,  "list_date": "20220704"},
    {"code": "159545.SZ", "name": "恒生红利低波ETF", "max_pos": 5,  "list_date": "20220726"},
]


# ═══════════════════════════════════════════════════════════
#  数据加载（复用已下载的 parquet）
# ═══════════════════════════════════════════════════════════

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
            col = 'close'
            if col not in df.columns:
                continue
            frames[code] = df.set_index('trade_date')[col].rename(code)
        except Exception as e:
            pass
    if not frames:
        raise FileNotFoundError("无数据")
    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


# ═══════════════════════════════════════════════════════════
#  Regime 识别（与 V4.2 完全一致）
# ═══════════════════════════════════════════════════════════

def classify_regime_series(close_series):
    close = close_series.values.astype(float)
    n = len(close)
    regimes = np.full(n, "RANGE", dtype=object)
    ma120 = pd.Series(close).rolling(120, min_periods=120).mean().values

    for i in range(120, n):
        if i >= 3:
            ret3 = close[i] / close[i-3] - 1
            if ret3 < -0.07:
                regimes[i] = "CRASH"
                continue
        cur = close[i]
        ma120_val = ma120[i]
        if np.isnan(ma120_val):
            continue

        ma120_window = []
        for j in range(max(0, i-5), i+1):
            if not np.isnan(ma120[j]):
                ma120_window.append(ma120[j])
        slope5 = float(np.polyfit(np.arange(len(ma120_window), dtype=float),
                                  ma120_window, 1)[0]) if len(ma120_window) >= 2 else 0.0
        ret5 = (close[i] / close[i-5] - 1) * 100 if i >= 5 else 0.0
        ret20 = (close[i] / close[i-20] - 1) * 100 if i >= 20 else 0.0
        above = cur > ma120_val

        if above and slope5 > 0 and ret20 > 0:
            regimes[i] = "BULL"
        elif above:
            regimes[i] = "RANGE"
        elif not above and ret5 > 3:
            regimes[i] = "RANGE"
        else:
            regimes[i] = "BEAR"

    return pd.Series(regimes, index=close_series.index)


# ═══════════════════════════════════════════════════════════
#  V5.0 增强层信号（带最小持仓期）
# ═══════════════════════════════════════════════════════════

def mr_signal_v5(price_arr, regime_arr):
    """
    V5.0 MR 增强层信号。
    改进点：
    - 最小持仓期 MIN_HOLD_DAYS 天（减少鞭打）
    - 取消 defensive-only 限制
    - 渐进式建仓：入场时权重 0.5，确认后 1.0
    """
    n = len(price_arr)
    sig = np.zeros(n, dtype=float)  # 0 or 0.5 or 1.0
    in_pos = False
    entry_px = 0.0
    entry_day = 0
    confirmed = False

    max_nt = 120
    rp = 14

    if n < max_nt + rp + 5:
        return sig

    # 预计算指标
    ma40  = pd.Series(price_arr).rolling(40, min_periods=40).mean().values
    ma90  = pd.Series(price_arr).rolling(90, min_periods=90).mean().values
    ma120 = pd.Series(price_arr).rolling(120, min_periods=120).mean().values
    ma_map = {40: ma40, 90: ma90, 120: ma120}

    bias40  = np.where(ma40 > 0,  (price_arr - ma40) / ma40 * 100,  np.nan)
    bias90  = np.where(ma90 > 0,  (price_arr - ma90) / ma90 * 100,  np.nan)
    bias120 = np.where(ma120 > 0, (price_arr - ma120) / ma120 * 100, np.nan)
    bias_map = {40: bias40, 90: bias90, 120: bias120}

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

        if regime == "CRASH":
            if in_pos:
                in_pos = False
                confirmed = False
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
                sig[i] = 1.0 if confirmed else 0.5
            continue

        if not in_pos:
            trend_ok = px > ma_t[i]
            buy_trig = (rsi[i] <= rb) or (not np.isnan(bias[i]) and bias[i] <= bb)
            if trend_ok and buy_trig:
                in_pos = True
                entry_px = px
                entry_day = i
                confirmed = False
                sig[i] = 0.5  # 初始半仓进入
        else:
            hold_days = i - entry_day
            cumret = px / entry_px - 1

            # 确认逻辑：持仓 3 天后若盈利，升级为满仓
            if not confirmed and hold_days >= 3 and cumret > 0:
                confirmed = True

            # 止损保护（最小持仓期内不止损，除非亏损 > 2倍止损线）
            if hold_days < MIN_HOLD_DAYS:
                hard_stop = cumret < -(sl * 2)  # 加倍才触发
                if hard_stop:
                    in_pos = False
                    confirmed = False
                    sig[i] = 0.0
                else:
                    sig[i] = 1.0 if confirmed else 0.5
            else:
                # 正常止损/止盈
                sell_trig = (rsi[i] >= rs_sell or
                             cumret < -sl or
                             px < ma_t[i] * 0.97)
                if sell_trig:
                    in_pos = False
                    confirmed = False
                    sig[i] = 0.0
                else:
                    sig[i] = 1.0 if confirmed else 0.5

    return sig


# ═══════════════════════════════════════════════════════════
#  V5.0 组合回测
# ═══════════════════════════════════════════════════════════

def run_v5_backtest():
    print("=" * 70)
    print("  AlphaCore 均值回归 V5.0 · 指数底仓 + MR增强 双层架构")
    print("  10年严格回测 (2016-2026)")
    print("=" * 70)

    # 加载数据
    all_codes = list(dict.fromkeys([e["code"] for e in MR_POOL] + [BENCHMARK_CODE]))
    full_prices = load_prices(all_codes, start="2015-01-01", end=BT_END)
    bm_full = full_prices[BENCHMARK_CODE].copy()

    # Regime
    idx_file = os.path.join(DAILY_PRICE_DIR, f"{INDEX_CODE}.parquet")
    if os.path.exists(idx_file):
        df_idx = pd.read_parquet(idx_file)
        df_idx['trade_date'] = pd.to_datetime(df_idx['trade_date'].astype(str).str[:8], format='%Y%m%d')
        idx_series = df_idx.set_index('trade_date')['close'].sort_index()
        idx_series = idx_series.reindex(full_prices.index).ffill()
    else:
        idx_series = bm_full

    regime_series = classify_regime_series(idx_series)
    bt_mask = full_prices.index >= pd.Timestamp(BT_START)
    prices_bt = full_prices[bt_mask]
    bm_bt = bm_full[bt_mask]
    regime_bt = regime_series[bt_mask]
    regime_bt_arr = regime_bt.values
    n_days = len(prices_bt)

    print(f"\n  回测区间: {prices_bt.index[0].strftime('%Y-%m-%d')} ~ {prices_bt.index[-1].strftime('%Y-%m-%d')}")
    print(f"  总交易日: {n_days}")

    # Regime 分布
    for r in ["BULL", "RANGE", "BEAR", "CRASH"]:
        cnt = (regime_bt == r).sum()
        pct = cnt / len(regime_bt) * 100
        print(f"  {r:6s}: {cnt:4d} 天 ({pct:5.1f}%)")

    etf_codes = [e["code"] for e in MR_POOL if e["code"] in prices_bt.columns]
    max_pos_map = {e["code"]: e["max_pos"] / 100.0 for e in MR_POOL}
    list_date_map = {e["code"]: pd.Timestamp(e["list_date"]) for e in MR_POOL}

    # ─── 生成增强层信号 ──────────────────────────────────────────────

    print(f"\n[COMPUTE] 生成 MR 增强信号...")
    sig_mat = pd.DataFrame(0.0, index=prices_bt.index, columns=etf_codes)

    for code in etf_codes:
        ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
        warmup_date = ld + pd.Timedelta(days=210)
        arr = prices_bt[code].values.astype(float)
        sig = mr_signal_v5(arr, regime_bt_arr)

        for i, dt in enumerate(prices_bt.index):
            if dt < warmup_date:
                sig[i] = 0.0
            else:
                break
        sig_mat[code] = sig

    # T+1
    sig_t1 = sig_mat.shift(1).fillna(0)

    # ─── 双层权重计算 ──────────────────────────────────────────────

    print(f"[COMPUTE] 计算双层权重...")

    # Layer 1: 底仓（直接跟踪基准ETF）
    base_weight = np.zeros(n_days)
    for i in range(n_days):
        reg = regime_bt_arr[i]
        base_weight[i] = BASE_ALLOC.get(reg, 0.35)

    # 底仓也 T+1
    base_weight_t1 = np.roll(base_weight, 1)
    base_weight_t1[0] = 0

    # Layer 2: 增强层
    enhance_w = np.zeros((n_days, len(etf_codes)))
    max_pos_arr = np.array([max_pos_map.get(c, 0.05) for c in etf_codes])

    for i in range(n_days):
        reg = regime_bt_arr[i]
        dt = prices_bt.index[i]
        ecap = ENHANCE_CAP.get(reg, 0.35)

        row_sig = sig_t1.iloc[i].values  # 0, 0.5, or 1.0

        # 生存偏差过滤
        for j, code in enumerate(etf_codes):
            ld = list_date_map.get(code, pd.Timestamp("2020-01-01"))
            warmup = ld + pd.Timedelta(days=210)
            if dt < warmup:
                row_sig[j] = 0.0

        # 加权仓位
        raw = row_sig * max_pos_arr
        s = raw.sum()

        # 扣除底仓已持有的 510300.SH 权重，避免重复
        base_already = base_weight_t1[i]
        if BASE_ETF in etf_codes:
            base_idx = etf_codes.index(BASE_ETF)
            # 底仓已持有基准ETF，增强层不再重复
            raw[base_idx] = max(0, raw[base_idx] - base_already)

        s = raw.sum()
        if s > ecap:
            raw = raw * (ecap / s)
        enhance_w[i] = raw

    # 总仓位 = 底仓 + 增强，上限90%
    total_pos = base_weight_t1 + enhance_w.sum(axis=1)
    over_cap = total_pos > 0.90
    if over_cap.any():
        scale = np.where(over_cap, 0.90 / np.maximum(total_pos, 1e-6), 1.0)
        enhance_w = enhance_w * scale[:, np.newaxis]

    # ─── 收益计算 ──────────────────────────────────────────────

    print(f"[COMPUTE] 计算净值...")

    # 底仓收益
    base_ret = bm_bt.pct_change(fill_method=None).fillna(0).values
    base_pnl = base_weight_t1 * base_ret

    # 增强层收益
    ret_mat = prices_bt[etf_codes].pct_change(fill_method=None).fillna(0).values
    enhance_pnl = (enhance_w * ret_mat).sum(axis=1)

    # 总收益（扣交易成本）
    port_ret = base_pnl + enhance_pnl

    # 换手成本
    base_w_diff = np.abs(np.diff(base_weight_t1, prepend=base_weight_t1[0]))
    enhance_w_diff = np.abs(np.diff(enhance_w, axis=0, prepend=enhance_w[:1]))
    total_turnover = base_w_diff + enhance_w_diff.sum(axis=1)
    cost = total_turnover * TRANSACTION_COST
    net_ret = port_ret - cost

    equity = pd.Series((1 + net_ret).cumprod(), index=prices_bt.index)
    bm_ret_s = bm_bt.pct_change(fill_method=None).fillna(0)
    bm_eq = (1 + bm_ret_s).cumprod()

    # ─── 指标计算 ──────────────────────────────────────────────

    def calc_metrics(eq, bm_e, pr, br):
        n = len(eq)
        _sl = lambda x: np.log(max(float(x), 1e-9))
        ann_f = 252 / n
        ann_ret = float(np.exp(_sl(eq.iloc[-1]) * ann_f) - 1)
        ann_bm = float(np.exp(_sl(bm_e.iloc[-1]) * ann_f) - 1)
        alpha = ann_ret - ann_bm
        total_ret = float(eq.iloc[-1] - 1)
        total_bm = float(bm_e.iloc[-1] - 1)
        roll_max = eq.cummax()
        max_dd = float(((eq - roll_max) / roll_max).min())
        excess = pr - RISK_FREE_RATE / 252
        sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 1e-8 else 0.0
        calmar = float(ann_ret / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0
        active = pr - br
        ir = float(active.mean() / active.std() * np.sqrt(252)) if active.std() > 1e-8 else 0.0
        wk = pr.resample("W").sum()
        win_rate = float((wk > 0).sum() / max(len(wk), 1))
        ann_vol = float(pr.std() * np.sqrt(252))

        # Sortino
        down = pr[pr < 0]
        down_vol = float(down.std() * np.sqrt(252)) if len(down) > 0 and down.std() > 1e-8 else 1
        sortino = float((ann_ret - RISK_FREE_RATE) / down_vol)

        # 持仓天数
        total_pos_arr = base_weight_t1 + enhance_w.sum(axis=1)
        coverage = (total_pos_arr > 0.05).sum() / max(n, 1)

        # 水下时间
        peak = eq.cummax()
        underwater = (eq - peak) / peak
        underwater_pct = (underwater < -0.01).sum() / max(n, 1)

        return {
            "ann_ret": round(ann_ret * 100, 2),
            "ann_bm": round(ann_bm * 100, 2),
            "alpha": round(alpha * 100, 2),
            "total_ret": round(total_ret * 100, 2),
            "total_bm": round(total_bm * 100, 2),
            "max_dd": round(max_dd * 100, 2),
            "sharpe": round(sharpe, 3),
            "calmar": round(calmar, 3),
            "sortino": round(sortino, 3),
            "ir": round(ir, 3),
            "win_rate": round(win_rate * 100, 1),
            "ann_vol": round(ann_vol * 100, 2),
            "coverage": round(coverage * 100, 1),
            "underwater_pct": round(underwater_pct * 100, 1),
        }

    pr_series = pd.Series(net_ret, index=prices_bt.index)
    overall = calc_metrics(equity, bm_eq, pr_series, bm_ret_s)

    # ─── 逐年明细 ──────────────────────────────────────────────

    yearly = {}
    for year in range(2016, 2027):
        y_start, y_end = f"{year}-01-01", f"{year}-12-31"
        mask_y = (prices_bt.index >= y_start) & (prices_bt.index <= y_end)
        if mask_y.sum() < 20:
            continue
        eq_y = equity[mask_y]
        bm_y = bm_eq[mask_y]
        eq_n = eq_y / eq_y.iloc[0]
        bm_n = bm_y / bm_y.iloc[0]
        y_ret = float(eq_n.iloc[-1] - 1) * 100
        y_bm = float(bm_n.iloc[-1] - 1) * 100
        y_dd = float(((eq_n - eq_n.cummax()) / eq_n.cummax()).min()) * 100
        regime_y = regime_bt[mask_y]
        main_r = regime_y.value_counts().index[0]
        year_mid = pd.Timestamp(f"{year}-07-01")
        active_etfs = sum(1 for e in MR_POOL
                          if e["code"] in etf_codes and
                          pd.Timestamp(e["list_date"]) + pd.Timedelta(days=210) < year_mid)

        # 底仓 vs 增强 归因
        mask_idx = np.where(mask_y)[0]
        base_contrib = sum(base_pnl[j] for j in mask_idx) * 100
        enhance_contrib = sum(enhance_pnl[j] for j in mask_idx) * 100

        yearly[str(year)] = {
            "return": round(y_ret, 2), "benchmark": round(y_bm, 2),
            "alpha": round(y_ret - y_bm, 2), "max_dd": round(y_dd, 2),
            "main_regime": main_r, "active_etfs": active_etfs,
            "base_contrib": round(base_contrib, 2),
            "enhance_contrib": round(enhance_contrib, 2),
        }

    # ─── 分 Regime 绩效 ──────────────────────────────────────────────

    regime_perf = {}
    for rn in ["BULL", "RANGE", "BEAR", "CRASH"]:
        r_mask = regime_bt == rn
        if r_mask.sum() < 5:
            continue
        r_ret = pr_series[r_mask]
        r_bm = bm_ret_s[r_mask]
        cum_ret = float((1 + r_ret).prod() - 1) * 100
        cum_bm = float((1 + r_bm).prod() - 1) * 100
        regime_perf[rn] = {
            "days": int(r_mask.sum()),
            "cum_ret": round(cum_ret, 2),
            "cum_bm": round(cum_bm, 2),
            "cum_alpha": round(cum_ret - cum_bm, 2),
        }

    # ─── V4.2 vs V5.0 对比 ──────────────────────────────────────────

    v4_results = {}
    if os.path.exists(RESULT_FILE_V4):
        with open(RESULT_FILE_V4, "r", encoding="utf-8") as f:
            v4_results = json.load(f)

    # ─── 输出 ──────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("  10年回测结果: V4.2 vs V5.0 对比")
    print("=" * 70)

    v4o = v4_results.get("overall", {})
    print(f"\n  {'指标':<20s} {'V4.2':>10s} {'V5.0':>10s} {'改进':>10s}")
    print(f"  {'-'*54}")

    def cmp(key, fmt=".2f", suffix="%", higher_better=True):
        v4 = v4o.get(key, 0)
        v5 = overall.get(key, 0)
        diff = v5 - v4
        if not higher_better:
            better = "✅" if diff < 0 else "❌" if diff > 0 else "━"
        else:
            better = "✅" if diff > 0 else "❌" if diff < 0 else "━"
        print(f"  {key:<20s} {v4:>9{fmt}}{suffix} {v5:>9{fmt}}{suffix} {diff:>+8{fmt}} {better}")

    cmp("ann_ret")
    cmp("alpha")
    cmp("total_ret")
    cmp("max_dd", higher_better=False)
    cmp("sharpe", fmt=".3f", suffix="")
    cmp("calmar", fmt=".3f", suffix="")
    cmp("ir", fmt=".3f", suffix="")
    cmp("win_rate")
    cmp("coverage")

    print(f"  {'sortino':<20s} {'N/A':>10s} {overall['sortino']:>9.3f}")
    print(f"  {'underwater_pct':<20s} {'95.0':>9s}% {overall['underwater_pct']:>9.1f}%")

    print(f"\n  逐年明细:")
    print(f"  {'年份':<6s} {'V5.0':>8s} {'基准':>8s} {'Alpha':>8s} {'MaxDD':>8s} {'底仓贡献':>10s} {'增强贡献':>10s} {'#ETF':>5s}")
    print(f"  {'-'*68}")
    for y, d in sorted(yearly.items()):
        v4y = v4_results.get("yearly", {}).get(y, {})
        print(f"  {y:<6s} {d['return']:>+7.2f}% {d['benchmark']:>+7.2f}% {d['alpha']:>+7.2f}% "
              f"{d['max_dd']:>7.2f}% {d['base_contrib']:>+9.2f}% {d['enhance_contrib']:>+9.2f}% {d['active_etfs']:>5d}")

    print(f"\n  分 Regime 绩效:")
    print(f"  {'Regime':<8s} {'天数':>6s} {'V5.0累计':>10s} {'基准累计':>10s} {'Alpha':>10s}")
    print(f"  {'-'*50}")
    for rn in ["BULL", "RANGE", "BEAR", "CRASH"]:
        if rn in regime_perf:
            d = regime_perf[rn]
            v4r = v4_results.get("regime_perf", {}).get(rn, {})
            v4a = v4r.get("cum_alpha", 0)
            print(f"  {rn:<8s} {d['days']:>6d} {d['cum_ret']:>+9.2f}% {d['cum_bm']:>+9.2f}% "
                  f"{d['cum_alpha']:>+9.2f}% (V4.2:{v4a:+.0f}%)")

    # ─── 评分 ──────────────────────────────────────────────

    print(f"\n{'='*70}")
    if overall["alpha"] > 0:
        print(f"  ✅ V5.0 Alpha = {overall['alpha']:+.2f}%/年 — 跑赢基准")
    else:
        print(f"  ❌ V5.0 Alpha = {overall['alpha']:+.2f}%/年 — 跑输基准")
    print(f"  Sharpe {overall['sharpe']:.3f} | MaxDD {overall['max_dd']:.2f}% | Sortino {overall['sortino']:.3f}")

    # 改进幅度
    if v4o:
        alpha_improve = overall['alpha'] - v4o.get('alpha', 0)
        sharpe_improve = overall['sharpe'] - v4o.get('sharpe', 0)
        print(f"  相比V4.2: Alpha {alpha_improve:+.2f}% | Sharpe {sharpe_improve:+.3f}")
    print(f"{'='*70}")

    # 保存
    result = {
        "generated_at": datetime.now().isoformat(),
        "version": "V5.0",
        "architecture": "指数底仓 + MR增强 双层架构",
        "base_alloc": BASE_ALLOC,
        "enhance_cap": ENHANCE_CAP,
        "overall": overall,
        "yearly": yearly,
        "regime_perf": regime_perf,
        "equity_dates": [d.strftime("%Y-%m-%d") for d in equity.index.tolist()],
        "equity_values": [round(float(v), 4) for v in equity.tolist()],
        "bm_values": [round(float(v), 4) for v in bm_eq.tolist()],
    }

    with open(RESULT_FILE_V5, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  [SAVE] {RESULT_FILE_V5}")

    return result


if __name__ == "__main__":
    t0 = time.time()
    run_v5_backtest()
    elapsed = time.time() - t0
    print(f"\n  耗时: {elapsed:.1f}s")
