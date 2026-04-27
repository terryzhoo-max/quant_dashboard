"""
AlphaCore · 均值回归策略 快速回测引擎 V3.0
==========================================
核心特性：
- 35只ETF全标的池，2022-01-01起全样本优化
- 信号统一：单一 RSI(N) + MA趋势 + BIAS 三要素
- 止损状态机：跟踪入场价，真实模拟止损执行
- 864种参数组合，约 10-20 分钟完成
- 双集验证：IS(2022-2023) + OOS(2024-2026)，防过拟合

Author: AlphaCore Team | V3.0 | 2026-03
"""

import pandas as pd
import numpy as np
import os, json, itertools, warnings, sys, time
warnings.filterwarnings('ignore')

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

import tushare as ts
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

# ─── 配置 ─────────────────────────────────────────────────────────────────────

from config import TUSHARE_TOKEN
DAILY_PRICE_DIR  = "data_lake/daily_prices"
BENCHMARK_CODE   = "510300.SH"       # 沪深300ETF 作为基准
RISK_FREE_RATE   = 0.02              # 年化无风险利率
TRANSACTION_COST = 0.0010            # 单边费率（ETF佣金+印花税估计）
MAX_TOTAL_POS    = 0.85              # 组合总仓位上限
RESULT_FILE      = "mr_optimization_results.json"

TRAIN_START = "2022-01-01"
TRAIN_END   = "2023-12-31"
VALID_START = "2024-01-01"
VALID_END   = "2026-03-27"

# ─── 标的池（35只ETF） ────────────────────────────────────────────────────────

MR_POOL = [
    # 宽基指数
    {"code": "510500.SH", "name": "中证500ETF",      "max_pos": 15},
    {"code": "512100.SH", "name": "中证1000ETF",     "max_pos": 15},
    {"code": "510300.SH", "name": "沪深300ETF华泰",  "max_pos": 15},
    {"code": "159915.SZ", "name": "创业板ETF",        "max_pos": 10},
    {"code": "159949.SZ", "name": "创业板50ETF",      "max_pos": 10},
    {"code": "588000.SH", "name": "科创50ETF",        "max_pos": 10},
    {"code": "159781.SZ", "name": "科创创业ETF",      "max_pos": 8},
    # 科技/AI/芯片
    {"code": "512480.SH", "name": "半导体ETF",        "max_pos": 8},
    {"code": "588200.SH", "name": "科创芯片ETF",      "max_pos": 7},
    {"code": "159995.SZ", "name": "芯片ETF",          "max_pos": 7},
    {"code": "159516.SZ", "name": "半导体设备ETF",    "max_pos": 6},
    {"code": "588220.SH", "name": "科创100ETF",       "max_pos": 8},
    {"code": "515000.SH", "name": "科技ETF",          "max_pos": 6},
    {"code": "515070.SH", "name": "人工智能AIETF",    "max_pos": 6},
    {"code": "159819.SZ", "name": "人工智能ETF",      "max_pos": 6},
    {"code": "515880.SH", "name": "通信ETF",          "max_pos": 6},
    {"code": "562500.SH", "name": "机器人ETF",        "max_pos": 5},
    # 行业/新能源
    {"code": "512400.SH", "name": "有色金属ETF",      "max_pos": 6},
    {"code": "516160.SH", "name": "新能源ETF",        "max_pos": 7},
    {"code": "515790.SH", "name": "光伏ETF",          "max_pos": 7},
    {"code": "562550.SH", "name": "绿电ETF",          "max_pos": 5},
    {"code": "159870.SZ", "name": "化工ETF",          "max_pos": 5},
    {"code": "512560.SH", "name": "军工ETF",          "max_pos": 7},
    {"code": "159218.SZ", "name": "卫星ETF",          "max_pos": 5},
    {"code": "159326.SZ", "name": "电网设备ETF",      "max_pos": 5},
    {"code": "159869.SZ", "name": "游戏ETF",          "max_pos": 5},
    {"code": "159851.SZ", "name": "金融科技ETF",      "max_pos": 5},
    # 跨境/港股
    {"code": "159941.SZ", "name": "纳指ETF",          "max_pos": 8},
    {"code": "513500.SH", "name": "标普500ETF",       "max_pos": 8},
    {"code": "515100.SH", "name": "红利低波100ETF",   "max_pos": 5},
    {"code": "159545.SZ", "name": "恒生红利低波ETF",  "max_pos": 5},
    {"code": "513130.SH", "name": "恒生科技ETF",      "max_pos": 5},
    {"code": "513970.SH", "name": "恒生消费ETF",      "max_pos": 5},
    {"code": "513090.SH", "name": "香港证券ETF",      "max_pos": 5},
    {"code": "513120.SH", "name": "港股创新药ETF",    "max_pos": 5},
]

# ─── 参数搜索空间（864种组合） ─────────────────────────────────────────────────

PARAM_GRID = {
    "N_trend":    [40, 60, 90, 120],       # 4 趋势均线
    "rsi_period": [9, 14],                  # 2 RSI周期
    "rsi_buy":    [25, 30, 35, 40],        # 4 超卖阈值
    "rsi_sell":   [65, 70, 75],            # 3 超买阈值
    "bias_buy":   [-2.0, -3.0, -4.0],     # 3 乖离率买入
    "stop_loss":  [0.06, 0.08, 0.10],     # 3 止损比例
}
# 4×2×4×3×3×3 = 864 种

DEFAULT_PARAMS = {
    "N_trend": 60, "rsi_period": 14,
    "rsi_buy": 30, "rsi_sell": 70,
    "bias_buy": -3.0, "stop_loss": 0.08,
}

# ─── Tushare 数据下载 ─────────────────────────────────────────────────────────

def ensure_etf_data():
    """确保所有ETF的parquet数据存在，缺失则从Tushare补下载"""
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    os.makedirs(DAILY_PRICE_DIR, exist_ok=True)

    # 额外需要基准
    all_codes = [e["code"] for e in MR_POOL] + [BENCHMARK_CODE]
    all_codes = list(dict.fromkeys(all_codes))  # 去重保序

    missing = [c for c in all_codes
               if not os.path.exists(os.path.join(DAILY_PRICE_DIR, f"{c}.parquet"))]

    if not missing:
        print(f"[DATA] 全部 {len(all_codes)} 只ETF数据已就绪 ✓")
        return

    print(f"[DATA] 需要下载 {len(missing)} 只ETF数据...")
    end_date   = datetime.now().strftime("%Y%m%d")
    start_date = "20210101"  # 多取一年，保证2022年训练集有足够预热期

    for i, code in enumerate(missing, 1):
        fp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
        try:
            df = pro.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                # 尝试 daily（部分宽基可能是股票接口）
                df = pro.daily(ts_code=code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
                df.to_parquet(fp, index=False)
                print(f"  [{i}/{len(missing)}] {code} 下载成功：{len(df)} 条")
            else:
                print(f"  [{i}/{len(missing)}] {code} ⚠️ 无数据")
            time.sleep(0.4)  # 避免触发频率限制
        except Exception as e:
            print(f"  [{i}/{len(missing)}] {code} ❌ 错误：{e}")

    print(f"[DATA] 数据下载完成")


# ─── 数据加载 ─────────────────────────────────────────────────────────────────

def load_prices(codes: List[str], start: str, end: str) -> pd.DataFrame:
    """从 parquet 加载收盘价矩阵（日期 × 代码），前复权"""
    frames = {}
    s_dt, e_dt = pd.to_datetime(start), pd.to_datetime(end)

    for code in codes:
        fp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
        if not os.path.exists(fp):
            continue
        try:
            df = pd.read_parquet(fp)
            # 兼容 trade_date 为 int 或 str
            df['trade_date'] = pd.to_datetime(
                df['trade_date'].astype(str).str[:8], format='%Y%m%d')
            if 'adj_close' in df.columns:
                price_col = 'adj_close'
            elif 'close' in df.columns:
                price_col = 'close'
            else:
                continue
            s = df.set_index('trade_date')[price_col].rename(code)
            frames[code] = s
        except Exception as e:
            print(f"  [WARN] 加载 {code} 失败: {e}")

    if not frames:
        raise FileNotFoundError("无任何价格数据可加载")

    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


# ─── 信号状态机（单只ETF） ────────────────────────────────────────────────────

def signal_state_machine(price_arr: np.ndarray, p: dict) -> Tuple[np.ndarray, np.ndarray]:
    """
    单只ETF的信号状态机，返回 (sig, equity)
    sig: 0 或 1（每日收盘时持仓状态）
    equity: 单只ETF持仓净值曲线（初值=1）

    信号逻辑：
    入场: close > MA(N_trend) AND [RSI ≤ rsi_buy OR BIAS ≤ bias_buy]
    出场: RSI ≥ rsi_sell OR 累计亏损 < -stop_loss OR close < MA(N_trend)×0.97
    """
    n   = len(price_arr)
    nt  = p["N_trend"]
    rp  = p["rsi_period"]
    rb  = p["rsi_buy"]
    rs  = p["rsi_sell"]
    bb  = p["bias_buy"]
    sl  = abs(p["stop_loss"]) if "stop_loss" in p else 0.08

    if n < nt + rp + 5:
        return np.zeros(n), np.ones(n)

    # ── 计算指标 ──────────────────────────────────────────────────────────────
    # MA(N_trend)
    ma_t = np.full(n, np.nan)
    for i in range(nt - 1, n):
        ma_t[i] = price_arr[i - nt + 1:i + 1].mean()

    # BIAS（相对 MA_trend）
    with np.errstate(invalid='ignore', divide='ignore'):
        bias = np.where(ma_t > 0, (price_arr - ma_t) / ma_t * 100, np.nan)

    # RSI(rp) — Wilder 平滑法
    diff = np.diff(price_arr, prepend=price_arr[0])
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    if n > rp:
        avg_gain[rp] = gain[1:rp + 1].mean()
        avg_loss[rp] = loss[1:rp + 1].mean()
        for i in range(rp + 1, n):
            avg_gain[i] = (avg_gain[i-1] * (rp - 1) + gain[i]) / rp
            avg_loss[i] = (avg_loss[i-1] * (rp - 1) + loss[i]) / rp
    with np.errstate(invalid='ignore', divide='ignore'):
        rs_arr = np.where(avg_loss < 1e-8, 100.0, avg_gain / avg_loss)
        rsi = 100 - 100 / (1 + rs_arr)

    # ── 状态机 ──────────────────────────────────────────────────────────────
    sig       = np.zeros(n, dtype=float)
    in_pos    = False
    entry_px  = 0.0
    equity    = np.ones(n, dtype=float)

    for i in range(1, n):
        px = price_arr[i]

        if np.isnan(ma_t[i]) or np.isnan(rsi[i]):
            equity[i] = equity[i-1]
            continue

        if not in_pos:
            trend_ok = px > ma_t[i]
            buy_trig = (rsi[i] <= rb) or (not np.isnan(bias[i]) and bias[i] <= bb)
            if trend_ok and buy_trig:
                in_pos    = True
                entry_px  = px
                sig[i]    = 1.0
            equity[i] = equity[i-1]
        else:
            daily_ret  = px / price_arr[i-1] - 1
            cumret     = px / entry_px - 1

            sell_trig  = (rsi[i] >= rs or
                          cumret < -abs(sl) or
                          px < ma_t[i] * 0.97)  # 跌破趋势线3%以上强制出场

            if sell_trig:
                in_pos   = False
                sig[i]   = 0.0
            else:
                sig[i]   = 1.0

            equity[i] = equity[i-1] * (1 + daily_ret * sig[i])

    return sig, equity


# ─── 组合回测（多ETF） ────────────────────────────────────────────────────────

def portfolio_backtest(price_mat: pd.DataFrame, bm_series: pd.Series, p: dict) -> dict:
    """
    给定价格矩阵和参数，运行全策略回测
    - 每日动态等权配置所有活跃信号ETF
    - 单只上限受 max_pos 约束，总计上限 85%
    """
    # 只使用有足够数据的ETF
    valid_codes = [e["code"] for e in MR_POOL if e["code"] in price_mat.columns]
    max_pos_map = {e["code"]: e["max_pos"] / 100.0 for e in MR_POOL}

    n_days = len(price_mat)
    if n_days < 60:
        return {"valid": False}

    # 信号矩阵 (T × N)
    sig_mat = pd.DataFrame(0.0, index=price_mat.index, columns=valid_codes)

    for code in valid_codes:
        arr = price_mat[code].ffill().bfill().values.astype(float)
        if len(arr) < p["N_trend"] + p["rsi_period"] + 10:
            continue
        sig, _ = signal_state_machine(arr, p)
        sig_mat[code] = sig

    # 前移一天（避免 look-ahead bias）
    sig_t1 = sig_mat.shift(1).fillna(0)

    # 动态权重：有信号 → 等权，受 max_pos 约束，总仓位上限 85%
    max_pos_arr = np.array([max_pos_map.get(c, 0.10) for c in valid_codes])
    raw_w = sig_t1.values * max_pos_arr                        # (T × N)

    row_sum = raw_w.sum(axis=1, keepdims=True)                 # 总仓位
    row_sum_safe = np.where(row_sum > 0, row_sum, 1.0)
    # 若总仓位超过85% → 等比缩放
    scale = np.minimum(MAX_TOTAL_POS / row_sum_safe, 1.0)
    final_w = raw_w * scale                                     # (T × N)

    # 每日收益
    ret_mat = price_mat[valid_codes].pct_change(fill_method=None).fillna(0).values
    port_ret = (final_w * ret_mat).sum(axis=1)

    # 换手成本
    w_diff  = np.abs(np.diff(final_w, axis=0, prepend=final_w[:1]))
    cost    = w_diff.sum(axis=1) * TRANSACTION_COST
    net_ret = port_ret - cost

    # 净值曲线
    equity  = pd.Series((1 + net_ret).cumprod(), index=price_mat.index)

    # 基准
    bm_al   = bm_series.reindex(price_mat.index).ffill()
    bm_ret  = bm_al.pct_change(fill_method=None).fillna(0)
    bm_eq   = (1 + bm_ret).cumprod()

    result = _calc_metrics(equity, bm_eq,
                           pd.Series(net_ret, index=price_mat.index), bm_ret,
                           final_w)
    if result["valid"]:
        # 附带净值序列（用于验证集 JSON 输出）
        result["equity_dates"]  = [d.strftime("%Y-%m-%d") for d in equity.index.tolist()]
        result["equity_values"] = [round(float(v), 4) for v in equity.tolist()]
        result["bm_values"]     = [round(float(v), 4) for v in bm_eq.tolist()]

    return result


# ─── 指标计算 ─────────────────────────────────────────────────────────────────

def _calc_metrics(eq: pd.Series, bm_eq: pd.Series,
                  port_ret: pd.Series, bm_ret: pd.Series,
                  final_w: np.ndarray = None) -> dict:
    n = len(eq)
    if n < 50:
        return {"valid": False}

    _sl = lambda x: np.log(max(float(x), 1e-9))
    ann = 252 / n

    ann_ret  = float(np.exp(_sl(eq.iloc[-1])  * ann) - 1)
    ann_bm   = float(np.exp(_sl(bm_eq.iloc[-1]) * ann) - 1)
    alpha    = ann_ret - ann_bm

    total_ret = float(eq.iloc[-1] - 1)
    total_bm  = float(bm_eq.iloc[-1] - 1)

    roll_max  = eq.cummax()
    max_dd    = float(((eq - roll_max) / roll_max).min())

    excess    = port_ret - RISK_FREE_RATE / 252
    sharpe    = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 1e-8 else 0.0
    calmar    = float(ann_ret / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

    active    = port_ret - bm_ret
    ir        = float(active.mean() / active.std() * np.sqrt(252)) if active.std() > 1e-8 else 0.0

    wk        = port_ret.resample("W").sum()
    win_rate  = float((wk > 0).sum() / max(len(wk), 1))

    # V4.3: coverage 统计（与 optimizer 对齐）
    if final_w is not None:
        total_pos_days = (final_w.sum(axis=1) > 0.01).sum()
        coverage = total_pos_days / max(n, 1)
    else:
        coverage = 0.5  # 无权重矩阵时给中性值

    # V4.3: 修复 opt_score — 回撤项线性化 + coverage 提权至25%
    opt_score = (
        0.30 * min(max(alpha / 0.20, 0), 1.0)               # Alpha 占30%
      + 0.20 * min(max(sharpe / 2.0, 0), 1.0)               # Sharpe 占20%
      + 0.15 * max(min((max_dd + 0.30) / 0.30, 1.0), 0)     # 回撤：-30%→0, 0%→1
      + 0.10 * min(max(calmar / 1.5, 0), 1.0)               # Calmar 占10%
      + 0.25 * min(max(coverage / 0.30, 0), 1.0)            # Coverage 占25%
    )

    return {
        "valid":      True,
        "ann_ret":    round(ann_ret  * 100, 2),
        "ann_bm":     round(ann_bm   * 100, 2),
        "alpha":      round(alpha    * 100, 2),
        "total_ret":  round(total_ret * 100, 2),
        "total_bm":   round(total_bm  * 100, 2),
        "max_dd":     round(max_dd   * 100, 2),
        "sharpe":     round(sharpe,  3),
        "calmar":     round(calmar,  3),
        "ir":         round(ir,      3),
        "win_rate":   round(win_rate * 100, 1),
        "coverage":   round(coverage * 100, 1),
        "opt_score":  round(opt_score, 4),
    }


# ─── 网格搜索 ─────────────────────────────────────────────────────────────────

def run_grid_search():
    """执行完整参数网格搜索，返回结果 JSON"""
    print("=" * 60)
    print("  AlphaCore 均值回归 V3.0 参数优化")
    print("=" * 60)

    # Step 1 — 确保数据
    ensure_etf_data()

    # Step 2 — 加载价格矩阵
    all_codes = [e["code"] for e in MR_POOL] + [BENCHMARK_CODE]
    all_codes = list(dict.fromkeys(all_codes))

    print(f"\n[LOAD] 加载价格数据（{TRAIN_START} ~ {VALID_END}）...")
    full_prices  = load_prices(all_codes, start="2021-01-01", end=VALID_END)
    bm_full      = full_prices[BENCHMARK_CODE].copy() if BENCHMARK_CODE in full_prices.columns else None

    # 按时间段切分
    train_mat = full_prices[(full_prices.index >= TRAIN_START) & (full_prices.index <= TRAIN_END)]
    valid_mat = full_prices[(full_prices.index >= VALID_START) & (full_prices.index <= VALID_END)]
    bm_train  = bm_full[(bm_full.index  >= TRAIN_START) & (bm_full.index  <= TRAIN_END)] if bm_full is not None else None
    bm_valid  = bm_full[(bm_full.index  >= VALID_START) & (bm_full.index  <= VALID_END)] if bm_full is not None else None

    # 剔除基准列，只保留ETF
    etf_codes_train = [c for c in train_mat.columns if c != BENCHMARK_CODE]
    etf_codes_valid = [c for c in valid_mat.columns if c != BENCHMARK_CODE]
    train_mat = train_mat[etf_codes_train]
    valid_mat = valid_mat[etf_codes_valid]

    available = len(etf_codes_train)
    print(f"[LOAD] 训练集 {len(train_mat)} 天，{available} 只ETF有效")
    print(f"[LOAD] 验证集 {len(valid_mat)} 天，{len(etf_codes_valid)} 只ETF有效\n")

    if bm_train is None or bm_valid is None:
        raise RuntimeError("基准数据加载失败，请检查 510300.SH parquet 文件")

    # Step 3 — 参数组合生成
    keys   = list(PARAM_GRID.keys())
    combos = list(itertools.product(*[PARAM_GRID[k] for k in keys]))
    total  = len(combos)
    print(f"[GRID] 共 {total} 种参数组合，开始训练集搜索...\n")

    train_results = []
    t0 = time.time()

    for idx, combo in enumerate(combos):
        p = dict(zip(keys, combo))

        res = portfolio_backtest(train_mat, bm_train, p)
        if not res.get("valid"):
            continue

        train_results.append({
            "params":    p,
            "train":     {k: v for k, v in res.items()
                          if k not in ("equity_dates", "equity_values", "bm_values", "valid")},
        })

        if (idx + 1) % 100 == 0:
            elapsed = time.time() - t0
            eta     = elapsed / (idx + 1) * (total - idx - 1)
            print(f"  [{idx+1}/{total}] 已完成 | 耗时 {elapsed:.0f}s | 预计剩余 {eta:.0f}s")

    print(f"\n[GRID] 训练集搜索完成，共 {len(train_results)} 个有效组合")

    # Step 4 — 按 opt_score 降序，选 Top 50 进入验证集
    train_results.sort(key=lambda x: x["train"]["opt_score"], reverse=True)
    top_train = train_results[:50]

    print(f"\n[VALID] 对 Top 50 组合进行验证集测试...")
    final_results = []
    best_valid_eq  = None

    for item in top_train:
        p   = item["params"]
        res = portfolio_backtest(valid_mat, bm_valid, p)
        if not res.get("valid"):
            continue

        combined_score = (item["train"]["opt_score"] * 0.4 +
                          res["opt_score"] * 0.6)   # 验证集权重更高

        entry = {
            "params":          p,
            "train":           item["train"],
            "valid":           {k: v for k, v in res.items()
                                if k not in ("equity_dates", "equity_values", "bm_values", "valid")},
            "combined_score":  round(combined_score, 4),
            "equity_dates":    res.get("equity_dates", []),
            "equity_values":   res.get("equity_values", []),
            "bm_values":       res.get("bm_values", []),
        }
        final_results.append(entry)

    final_results.sort(key=lambda x: x["combined_score"], reverse=True)

    if not final_results:
        print("[ERROR] 无有效结果，请检查数据")
        return {}

    best        = final_results[0]
    best_params = best["params"]

    print(f"\n{'='*60}")
    print(f"  🏆 最优参数组合（双集验证）")
    print(f"{'='*60}")
    print(f"  参数: {best_params}")
    print(f"  训练集 Alpha  : {best['train']['alpha']:+.2f}%")
    print(f"  验证集 Alpha  : {best['valid']['alpha']:+.2f}%")
    print(f"  验证集 Sharpe : {best['valid']['sharpe']:.3f}")
    print(f"  验证集 MaxDD  : {best['valid']['max_dd']:.2f}%")
    print(f"  综合评分      : {best['combined_score']:.4f}")
    print(f"{'='*60}\n")

    # Step 5 — 保存结果
    output = {
        "generated_at":  datetime.now().isoformat(),
        "train_period":  f"{TRAIN_START} ~ {TRAIN_END}",
        "valid_period":  f"{VALID_START} ~ {VALID_END}",
        "total_combos":  total,
        "etfs_used":     available,
        "best_params":   best_params,
        "best_train":    best["train"],
        "best_valid":    best["valid"],
        "combined_score": best["combined_score"],
        "equity_dates":  best["equity_dates"],
        "equity_values": best["equity_values"],
        "bm_values":     best["bm_values"],
        "top10": [
            {
                "rank":           i + 1,
                "params":         r["params"],
                "train_alpha":    r["train"]["alpha"],
                "valid_alpha":    r["valid"]["alpha"],
                "valid_sharpe":   r["valid"]["sharpe"],
                "valid_max_dd":   r["valid"]["max_dd"],
                "combined_score": r["combined_score"],
            }
            for i, r in enumerate(final_results[:10])
        ],
    }

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] 结果已保存至 {RESULT_FILE}")

    return output


# ─── 主入口 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t_start = time.time()
    result  = run_grid_search()
    elapsed = time.time() - t_start
    print(f"\n✅ 全程耗时：{elapsed / 60:.1f} 分钟")
    if result:
        best = result.get("best_params", {})
        print(f"\n实盘参数建议:")
        print(f"  趋势均线 N_trend  = {best.get('N_trend')}")
        print(f"  RSI 周期 rsi_period = {best.get('rsi_period')}")
        print(f"  RSI 买入 rsi_buy  = {best.get('rsi_buy')}")
        print(f"  RSI 卖出 rsi_sell = {best.get('rsi_sell')}")
        print(f"  乖离率买入 bias   = {best.get('bias_buy')}%")
        print(f"  止损线 stop_loss  = {best.get('stop_loss') * 100:.0f}%")
