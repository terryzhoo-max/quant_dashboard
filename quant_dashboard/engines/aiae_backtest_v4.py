# -*- coding: utf-8 -*-
"""
engines/aiae_backtest_v4.py
============================
AIAE 仓位策略 — 生产级回测引擎 V4

核心升级（vs 旧版 strategies/aiae_backtest_engine.py）：
  1. 信号源：使用 aiae_data_builder 重建的真实 AIAE_V1 序列（非价格代理）
  2. 仓位：POSITION_MATRIX (AIAE × ERP 双维矩阵) + C8 自动比例缩放
  3. 调仓频率：月频策略（月末信号 → 次月第1交易日执行）
  4. 交易成本：ETF 精确三段式（佣金万2.5×2 + 过户费×2 ≈ 0.054%）
  5. 四组对照：BM-0/1/2/3 + 主策略 MAIN
  6. 因子归因：拆分 AIAE_简 / fund_pos / margin_heat / ERP 各自边际贡献
  7. 择时分析：Regime 击中率 / 调仓换手率 / 月度胜率 by Regime

运行:
    python engines/aiae_backtest_v4.py --start 2014-01 --end 2026-05
    python engines/aiae_backtest_v4.py --fast   # 使用现有 Parquet，跳过数据拉取
"""
import os
import sys
import json
import math
import warnings
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from config import TUSHARE_TOKEN
import engines.aiae_params as AP
from engines.aiae_engine import AIAE_ETF_POOL, AIAE_ETF_MATRIX, REGIMES

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [BT_V4] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aiae_backtest_v4")

# ─────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────
DATA_LAKE       = os.path.join(_ROOT, "data_lake")
SIGNAL_FILE     = os.path.join(DATA_LAKE, "aiae_true_history.parquet")
PRICE_DIR       = os.path.join(DATA_LAKE, "daily_prices")
RESULT_FILE     = os.path.join(_ROOT, "aiae_backtest_v4_results.json")
REPORT_FILE     = os.path.join(_ROOT, "aiae_backtest_v4_report.md")
BENCHMARK_CODE  = "510300.SH"
RISK_FREE_RATE  = 0.02          # 无风险利率
CASH_RETURN     = 0.015         # 现金收益率（余额宝）
# 精确交易成本（ETF 双边）
ETF_COST_RATE   = 0.00025 * 2 + 0.00002 * 2   # 佣金+过户费 ≈ 0.00054


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────

def _load_prices(codes: List[str], start: str, end: str) -> pd.DataFrame:
    """加载 ETF 日线价格矩阵。"""
    import tushare as ts
    frames = {}
    s_dt = pd.to_datetime(start)
    e_dt = pd.to_datetime(end)

    for code in codes:
        fp = os.path.join(PRICE_DIR, f"{code}.parquet")
        if not os.path.exists(fp):
            log.info(f"下载价格数据: {code}")
            ts.set_token(TUSHARE_TOKEN)
            pro = ts.pro_api()
            try:
                df = pro.fund_daily(ts_code=code,
                                    start_date=start.replace("-", ""),
                                    end_date=end.replace("-", ""))
                if df is None or df.empty:
                    df = pro.daily(ts_code=code,
                                   start_date=start.replace("-", ""),
                                   end_date=end.replace("-", ""))
                if df is not None and not df.empty:
                    df = df.sort_values("trade_date").reset_index(drop=True)
                    os.makedirs(PRICE_DIR, exist_ok=True)
                    df.to_parquet(fp, index=False)
            except Exception as e:
                log.warning(f"下载失败 {code}: {e}")
                continue
            import time; time.sleep(0.35)

        if os.path.exists(fp):
            df = pd.read_parquet(fp)
            df["trade_date"] = pd.to_datetime(
                df["trade_date"].astype(str).str[:8], format="%Y%m%d"
            )
            col = "adj_close" if "adj_close" in df.columns else "close"
            s = df.set_index("trade_date")[col].rename(code)
            frames[code] = s

    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


def _monthly_reindex(signals_df: pd.DataFrame,
                     price_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """
    将月频信号（月末）重索引到日频价格序列。
    关键：月末信号在次月第1交易日生效（前视偏差控制）。
    """
    # 将信号日期设为次月第1交易日（向前偏移1个月后找最近交易日）
    result = pd.DataFrame(index=price_idx,
                          columns=signals_df.columns, dtype=float)
    result[:] = np.nan

    for _, row in signals_df.iterrows():
        month_end_str = str(row.name)[:7]  # YYYY-MM
        y, m = int(month_end_str[:4]), int(month_end_str[5:7])
        # 次月
        if m == 12:
            next_y, next_m = y + 1, 1
        else:
            next_y, next_m = y, m + 1
        next_month_start = pd.Timestamp(f"{next_y}-{next_m:02d}-01")
        # 找次月第1个交易日
        next_days = price_idx[price_idx >= next_month_start]
        if len(next_days) == 0:
            continue
        exec_date = next_days[0]
        result.loc[exec_date] = row.values

    # 前向填充（持仓在下次调仓前不变）
    result = result.ffill().fillna(0.0)
    return result


def _compute_metrics(equity: pd.Series,
                     daily_ret: pd.Series,
                     bm_ret: Optional[pd.Series] = None,
                     rf: float = RISK_FREE_RATE) -> Dict:
    """计算机构级绩效指标。"""
    n_days = len(equity)
    if n_days < 20:
        return {}

    ann_factor = 252
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    n_years = n_days / ann_factor
    ann_ret  = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0

    # 波动率
    ann_vol = float(daily_ret.std() * np.sqrt(ann_factor))

    # 最大回撤
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = float(drawdown.min())

    # Sharpe / Sortino
    excess = daily_ret - rf / ann_factor
    sharpe = float(excess.mean() / daily_ret.std() * np.sqrt(ann_factor)) if daily_ret.std() > 0 else 0
    down = daily_ret[daily_ret < 0]
    sortino = float(excess.mean() / down.std() * np.sqrt(ann_factor)) if len(down) > 0 and down.std() > 0 else 0

    # Calmar
    calmar = float(ann_ret / abs(max_dd)) if max_dd != 0 else 0

    # Alpha / Beta / IR（vs 基准）
    alpha, beta, ir = 0.0, 1.0, 0.0
    if bm_ret is not None:
        aligned = pd.concat([daily_ret, bm_ret], axis=1).dropna()
        if len(aligned) > 30:
            strat_r, bm_r = aligned.iloc[:, 0], aligned.iloc[:, 1]
            cov_mat = np.cov(strat_r, bm_r)
            beta = cov_mat[0, 1] / cov_mat[1, 1] if cov_mat[1, 1] > 0 else 1.0
            alpha = float((ann_ret - (rf + beta * (bm_r.mean() * ann_factor - rf))))
            tracking = float((strat_r - bm_r).std() * np.sqrt(ann_factor))
            ir = float((strat_r - bm_r).mean() * ann_factor / tracking) if tracking > 0 else 0

    # VaR / CVaR (95%)
    var_95  = float(np.percentile(daily_ret, 5))
    cvar_95 = float(daily_ret[daily_ret <= var_95].mean()) if (daily_ret <= var_95).any() else var_95

    # 胜率 / 盈亏比（月度）
    monthly = (1 + daily_ret).resample("ME").prod() - 1
    win_rate = float((monthly > 0).mean())
    wins  = monthly[monthly > 0]
    loses = monthly[monthly < 0]
    pnl_ratio = float(wins.mean() / abs(loses.mean())) if len(loses) > 0 and loses.mean() != 0 else 0

    return {
        "total_return":      round(total_return * 100, 2),
        "annualized_return": round(ann_ret * 100, 2),
        "annualized_vol":    round(ann_vol * 100, 2),
        "max_drawdown":      round(max_dd * 100, 2),
        "sharpe_ratio":      round(sharpe, 3),
        "sortino_ratio":     round(sortino, 3),
        "calmar_ratio":      round(calmar, 3),
        "alpha_pct":         round(alpha * 100, 2),
        "beta":              round(beta, 3),
        "info_ratio":        round(ir, 3),
        "var_95_pct":        round(var_95 * 100, 2),
        "cvar_95_pct":       round(cvar_95 * 100, 2),
        "monthly_win_rate":  round(win_rate * 100, 1),
        "pnl_ratio":         round(pnl_ratio, 2),
        "n_months":          len(monthly),
    }


def _grade(metrics: Dict) -> Tuple[str, float]:
    """100分制策略评级 → 字母级。"""
    s = 0.0
    sr = metrics.get("sharpe_ratio", 0)
    cal = metrics.get("calmar_ratio", 0)
    mdd = abs(metrics.get("max_drawdown", -100))
    wr  = metrics.get("monthly_win_rate", 0)

    # Sharpe (30分)
    s += min(30, max(0, (sr - 0.3) / 1.2 * 30))
    # Calmar (25分)
    s += min(25, max(0, (cal - 0.3) / 1.7 * 25))
    # MDD (25分)
    s += min(25, max(0, (1 - mdd / 30) * 25))
    # 月胜率 (20分)
    s += min(20, max(0, (wr - 45) / 20 * 20))

    s = round(s, 1)
    grade = ("S" if s >= 85 else "A" if s >= 70 else "B" if s >= 55
             else "C" if s >= 40 else "D" if s >= 25 else "F")
    return grade, s


# ─────────────────────────────────────────────────────────────
# 核心回测引擎
# ─────────────────────────────────────────────────────────────

class AIAEBacktestV4:
    """
    AIAE 仓位策略生产级回测引擎 V4。

    策略设计：
      - 信号频率：月频（月末计算，次月首日执行）
      - 仓位来源：POSITION_MATRIX[erp_tier][regime]
      - ETF 分配：AIAE_ETF_MATRIX[regime] × scale（C8缩放）
      - 现金收益：CASH_RETURN（余额宝）
      - 成本：ETF_COST_RATE（双边，约0.054%）
    """

    def __init__(self, start: str = "2014-01-01", end: Optional[str] = None):
        self.start = start
        self.end   = end or datetime.now().strftime("%Y-%m-%d")
        self.signal_df: Optional[pd.DataFrame] = None
        self.price_mat: Optional[pd.DataFrame] = None
        self._etf_codes = [e["ts_code"] for e in AIAE_ETF_POOL]

    # ── 数据加载 ──────────────────────────────────────────────

    def load_signals(self) -> pd.DataFrame:
        """加载真实历史 AIAE 信号序列。"""
        if not os.path.exists(SIGNAL_FILE):
            raise FileNotFoundError(
                f"信号文件不存在: {SIGNAL_FILE}\n"
                "请先运行: python engines/aiae_data_builder.py"
            )
        df = pd.read_parquet(SIGNAL_FILE)
        df["month"] = pd.to_datetime(df["month"] + "-01")
        df = df.set_index("month").sort_index()
        # 过滤区间
        s = pd.to_datetime(self.start).replace(day=1)
        e = pd.to_datetime(self.end)
        df = df[(df.index >= s) & (df.index <= e)]
        log.info(f"信号序列加载: {len(df)} 个月 | {df.index[0]:%Y-%m} ~ {df.index[-1]:%Y-%m}")
        self.signal_df = df
        return df

    def load_prices(self) -> pd.DataFrame:
        """加载 ETF + 基准价格矩阵。"""
        all_codes = self._etf_codes + [BENCHMARK_CODE]
        all_codes = list(dict.fromkeys(all_codes))
        mat = _load_prices(all_codes, self.start, self.end)
        log.info(f"价格矩阵: {mat.shape} | {mat.index[0]:%Y-%m-%d} ~ {mat.index[-1]:%Y-%m-%d}")
        self.price_mat = mat
        return mat

    # ── 权重构建 ──────────────────────────────────────────────

    # V5 精简版阈值（从 aiae_params 读取）
    V5_THRESHOLDS = AP.V5_REGIME_THRESHOLDS

    def _build_weights_for_strategy(self, strategy: str) -> pd.DataFrame:
        """
        构建月频信号的 ETF 权重矩阵。

        strategy 选项：
          'main'   - 主策略 (AIAE_V1 × ERP 双维矩阵)
          'bm1'    - 固定60%等权8只ETF
          'bm2'    - 仅 AIAE_简 单因子（fund_pos=0.20×75%, margin=固定中性）
          'bm3'    - AIAE_V1 但 ERP 固定 neutral (erp_2_4)
          'v5'     - 精简双因子 (AIAE_简 直接分档 × ERP 矩阵)
        """
        sig = self.signal_df
        valid_codes = [c for c in self._etf_codes
                       if c in self.price_mat.columns]
        monthly_weights = pd.DataFrame(index=sig.index,
                                       columns=valid_codes, dtype=float)
        monthly_weights[:] = 0.0

        for dt, row in sig.iterrows():
            regime = int(row.get("regime", 3))
            erp_tier = str(row.get("erp_tier", "erp_2_4"))

            if strategy == "bm1":
                # 固定60%等权
                per_etf = 0.60 / len(valid_codes)
                for c in valid_codes:
                    monthly_weights.loc[dt, c] = per_etf

            elif strategy == "bm2":
                # 仅 AIAE_简（用实际 aiae_simple，但 fund_pos 固定中性，margin 中性）
                aiae_simple = float(row.get("aiae_simple", 20.0))
                fund_norm  = AP.sigmoid_normalize(75.0, AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
                margin_norm = AP.sigmoid_normalize(2.2, AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_K)
                aiae_bm2 = (AP.W_AIAE_SIMPLE * aiae_simple
                           + AP.W_FUND_POS   * fund_norm
                           + AP.W_MARGIN_HEAT * margin_norm)
                regime_bm2 = self._classify_regime_static(aiae_bm2)
                # 用 neutral ERP
                pos = AP.POSITION_MATRIX["erp_2_4"][max(0, min(4, regime_bm2 - 1))]
                self._fill_etf_weights(monthly_weights, dt,
                                       regime_bm2, pos, valid_codes)

            elif strategy == "bm3":
                # AIAE_V1 但 ERP 固定 neutral
                pos = AP.POSITION_MATRIX["erp_2_4"][max(0, min(4, regime - 1))]
                self._fill_etf_weights(monthly_weights, dt,
                                       regime, pos, valid_codes)

            elif strategy == "v5":
                # V5: AIAE_简 直接百分位分档 + ERP 交叉矩阵 (V5仓位矩阵)
                aiae_simple = float(row.get("aiae_simple", 25.0))
                regime_v5 = 5
                for i, t in enumerate(self.V5_THRESHOLDS):
                    if aiae_simple < t:
                        regime_v5 = i + 1
                        break
                v5_matrix = AP.V5_POSITION_MATRIX
                pos = v5_matrix.get(erp_tier, v5_matrix["erp_2_4"])[max(0, min(4, regime_v5 - 1))]
                self._fill_etf_weights(monthly_weights, dt,
                                       regime_v5, pos, valid_codes)

            else:  # main
                pos = AP.POSITION_MATRIX.get(erp_tier, AP.POSITION_MATRIX["erp_2_4"])[max(0, min(4, regime - 1))]
                self._fill_etf_weights(monthly_weights, dt,
                                       regime, pos, valid_codes)

        return monthly_weights

    @staticmethod
    def _classify_regime_static(aiae: float) -> int:
        thresholds = AP.REGIME_THRESHOLDS
        for i, t in enumerate(thresholds):
            if aiae < t:
                return i + 1
        return 5

    @staticmethod
    def _fill_etf_weights(df: pd.DataFrame, dt,
                          regime: int, pos_pct: int, valid_codes: List[str]):
        """将 AIAE_ETF_MATRIX × C8缩放 写入权重 DataFrame。"""
        etf_alloc = AIAE_ETF_MATRIX.get(regime, AIAE_ETF_MATRIX[3])
        raw_total = sum(etf_alloc.values())
        scale = (pos_pct / 100.0) / raw_total if raw_total > 0 else 1.0
        for c in valid_codes:
            raw = etf_alloc.get(c, 0)
            df.loc[dt, c] = round(raw * scale, 4)

    # ── 组合模拟 ──────────────────────────────────────────────

    def _simulate(self, daily_weights: pd.DataFrame,
                  price_mat: pd.DataFrame) -> Tuple[pd.Series, pd.Series, float]:
        """
        事件驱动组合模拟。
        返回: (equity_curve, daily_returns, total_turnover)
        """
        valid_codes = daily_weights.columns.tolist()
        ret_mat = price_mat[valid_codes].pct_change(fill_method=None).fillna(0)

        n = len(price_mat)
        nav = 1.0
        equity = np.zeros(n)
        prev_w = np.zeros(len(valid_codes))
        total_turnover = 0.0

        for i in range(n):
            w = daily_weights.iloc[i].values.astype(float)
            cash_w = max(0.0, 1.0 - w.sum())

            # 交易成本（换手率）
            turnover = np.abs(w - prev_w).sum() / 2
            cost = turnover * ETF_COST_RATE
            total_turnover += turnover

            # 日收益
            etf_ret = (ret_mat.iloc[i].values * w).sum()
            cash_ret = cash_w * CASH_RETURN / 252

            nav = nav * (1 + etf_ret + cash_ret - cost)
            equity[i] = nav
            prev_w = w.copy()

        eq_series  = pd.Series(equity, index=price_mat.index)
        ret_series = eq_series.pct_change(fill_method=None).fillna(0)
        return eq_series, ret_series, total_turnover

    # ── 择时分析 ──────────────────────────────────────────────

    def _timing_analysis(self) -> Dict:
        """
        Regime 择时有效性分析：
          - 调低仓位后次月市场是否下跌？
          - 月度信号与次月收益的相关性
        """
        sig   = self.signal_df
        bm    = self.price_mat[BENCHMARK_CODE]
        bm_monthly = bm.resample("ME").last().pct_change(fill_method=None).dropna()

        hits = {"bearish_correct": 0, "bullish_correct": 0,
                "total_bearish": 0, "total_bullish": 0}

        for dt in sig.index[:-1]:
            regime = int(sig.loc[dt, "regime"])
            # 次月收益
            next_month = bm_monthly[bm_monthly.index > dt]
            if next_month.empty:
                continue
            next_ret = float(next_month.iloc[0])

            if regime >= 4:  # 看空信号
                hits["total_bearish"] += 1
                if next_ret < 0:
                    hits["bearish_correct"] += 1
            elif regime <= 2:  # 看多信号
                hits["total_bullish"] += 1
                if next_ret > 0:
                    hits["bullish_correct"] += 1

        bear_hit = (hits["bearish_correct"] / hits["total_bearish"] * 100
                    if hits["total_bearish"] > 0 else 0)
        bull_hit = (hits["bullish_correct"] / hits["total_bullish"] * 100
                    if hits["total_bullish"] > 0 else 0)

        # 仓位 vs 次月收益相关性
        positions = sig["matrix_position"].values[:-1].astype(float)
        next_rets = []
        for dt in sig.index[:-1]:
            nr = bm_monthly[bm_monthly.index > dt]
            next_rets.append(float(nr.iloc[0]) if not nr.empty else 0.0)

        corr = float(np.corrcoef(positions, next_rets)[0, 1]) if len(positions) > 5 else 0

        # 月度胜率 by Regime
        regime_perf: Dict[int, List[float]] = {i: [] for i in range(1, 6)}
        main_daily_w = _monthly_reindex(
            self._build_weights_for_strategy("main"), self.price_mat.index
        )
        main_eq, main_ret, _ = self._simulate(main_daily_w, self.price_mat)
        main_monthly = (1 + main_ret).resample("ME").prod() - 1

        for dt, row in sig.iterrows():
            regime = int(row.get("regime", 3))
            next_m = main_monthly[main_monthly.index > dt]
            if not next_m.empty:
                regime_perf[regime].append(float(next_m.iloc[0]))

        regime_stats = {}
        for r, rets in regime_perf.items():
            if rets:
                regime_stats[f"R{r}"] = {
                    "count": len(rets),
                    "avg_ret_pct": round(np.mean(rets) * 100, 2),
                    "win_rate_pct": round((np.array(rets) > 0).mean() * 100, 1),
                }

        return {
            "bearish_hit_rate_pct": round(bear_hit, 1),
            "bullish_hit_rate_pct": round(bull_hit, 1),
            "total_bearish_signals": hits["total_bearish"],
            "total_bullish_signals": hits["total_bullish"],
            "position_vs_nextret_corr": round(corr, 3),
            "regime_monthly_stats": regime_stats,
        }

    # ── 因子归因 ──────────────────────────────────────────────

    def _factor_attribution(self) -> Dict:
        """
        逐步因子归因：
          AIAE_简 基线 → +margin_heat → +fund_pos → +ERP
          每步相对上一步的年化超额 = 该因子边际贡献
        """
        sig = self.signal_df
        valid_codes = [c for c in self._etf_codes if c in self.price_mat.columns]

        def _run_factor_config(fund_fixed, margin_fixed, use_erp):
            w_df = pd.DataFrame(index=sig.index, columns=valid_codes, dtype=float)
            w_df[:] = 0.0
            for dt, row in sig.iterrows():
                aiae_s = float(row.get("aiae_simple", 20.0))
                fp = float(row.get("fund_pos", 75.0)) if not fund_fixed else fund_fixed
                mh = float(row.get("margin_heat", 2.2)) if not margin_fixed else margin_fixed
                fn = AP.sigmoid_normalize(fp, AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
                mn = AP.sigmoid_normalize(mh, AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_K)
                aiae_v = (AP.W_AIAE_SIMPLE * aiae_s
                         + AP.W_FUND_POS   * fn
                         + AP.W_MARGIN_HEAT * mn)
                r = self._classify_regime_static(aiae_v)
                erp_t = str(row.get("erp_tier", "erp_2_4")) if use_erp else "erp_2_4"
                pos = AP.POSITION_MATRIX.get(erp_t, AP.POSITION_MATRIX["erp_2_4"])[max(0, min(4, r - 1))]
                self._fill_etf_weights(w_df, dt, r, pos, valid_codes)
            dw = _monthly_reindex(w_df, self.price_mat.index)
            eq, ret, _ = self._simulate(dw, self.price_mat)
            m = _compute_metrics(eq, ret)
            return m.get("annualized_return", 0)

        ann_base     = _run_factor_config(75.0, 2.2,   False)  # 双因子固定
        ann_margin   = _run_factor_config(75.0, None,  False)  # 加融资热度
        ann_fund     = _run_factor_config(None, None,  False)  # 加基金仓位
        ann_erp      = _run_factor_config(None, None,  True)   # 加ERP（完整主策略）

        return {
            "aiae_simple_only_ann_pct":   round(ann_base, 2),
            "margin_heat_contrib_bps":    round((ann_margin - ann_base) * 100, 1),
            "fund_pos_contrib_bps":       round((ann_fund - ann_margin) * 100, 1),
            "erp_contrib_bps":            round((ann_erp - ann_fund) * 100, 1),
            "total_ann_pct":              round(ann_erp, 2),
        }

    # ── 主运行入口 ────────────────────────────────────────────

    def run(self, skip_attribution: bool = False) -> Dict:
        """
        执行完整回测流程。

        Returns: 完整结果 dict，含五组策略 + 择时分析 + 因子归因
        """
        log.info("=" * 60)
        log.info("  AIAE 仓位策略回测 V4 启动")
        log.info(f"  区间: {self.start} ~ {self.end}")
        log.info("=" * 60)

        self.load_signals()
        self.load_prices()

        bm_prices = self.price_mat[BENCHMARK_CODE]
        bm_ret    = bm_prices.pct_change(fill_method=None).fillna(0)
        bm_eq     = (1 + bm_ret).cumprod()
        bm_metrics = _compute_metrics(bm_eq, bm_ret)

        results = {"BM-0 (沪深300全仓)": {"metrics": bm_metrics, "equity": bm_eq}}

        strategies = {
            "BM-1 (固定60%等权ETF)": "bm1",
            "BM-2 (仅AIAE_简单因子)": "bm2",
            "BM-3 (AIAE_V1无ERP调整)": "bm3",
            "MAIN (AIAE_V4主策略)": "main",
            "V5 (AIAE_简+ERP精简版)": "v5",
        }

        for name, strat in strategies.items():
            log.info(f"回测: {name} ...")
            w_monthly = self._build_weights_for_strategy(strat)
            w_daily   = _monthly_reindex(w_monthly, self.price_mat.index)
            eq, ret, turnover = self._simulate(w_daily, self.price_mat)
            m = _compute_metrics(eq, ret, bm_ret)
            grade, score = _grade(m)
            results[name] = {
                "metrics": m, "equity": eq,
                "grade": grade, "score": score,
                "annual_turnover": round(turnover / (len(eq) / 252), 2),
            }
            log.info(
                f"  {name}: CAGR={m.get('annualized_return',0):.1f}% "
                f"MDD={m.get('max_drawdown',0):.1f}% "
                f"Sharpe={m.get('sharpe_ratio',0):.2f} "
                f"评级={grade}({score}分)"
            )

        log.info("择时有效性分析 ...")
        timing = self._timing_analysis()

        attribution = {}
        if not skip_attribution:
            log.info("因子归因分析 ...")
            attribution = self._factor_attribution()

        # 序列化为可 JSON 的格式
        output = {
            "version": "V4.0",
            "generated_at": datetime.now().isoformat(),
            "period": {"start": self.start, "end": self.end},
            "cost_rate_bps": round(ETF_COST_RATE * 10000, 2),
            "strategies": {},
            "timing_analysis": timing,
            "factor_attribution": attribution,
        }

        for name, res in results.items():
            eq = res["equity"]
            output["strategies"][name] = {
                "metrics": res["metrics"],
                "grade":   res.get("grade", "-"),
                "score":   res.get("score", 0),
                "annual_turnover": res.get("annual_turnover", 0),
                "dates":   [d.strftime("%Y-%m-%d") for d in eq.index.tolist()],
                "equity":  [round(float(v), 4) for v in eq.tolist()],
            }

        return output

    def save(self, output: Dict):
        """保存结果 JSON + Markdown 报告。"""
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        log.info(f"结果保存: {RESULT_FILE}")
        self._write_report(output)

    def _write_report(self, out: Dict):
        """生成机构级 Markdown 分析报告。"""
        strats = out["strategies"]
        main   = strats.get("MAIN (AIAE_V4主策略)", {})
        bm0    = strats.get("BM-0 (沪深300全仓)", {})

        main_m = main.get("metrics", {})
        bm0_m  = bm0.get("metrics", {})

        ta = out.get("timing_analysis", {})
        fa = out.get("factor_attribution", {})

        lines = [f"""# AIAE 仓位策略回测分析报告 — V4.0

> 生成时间: {out['generated_at'][:16]}  
> 回测区间: {out['period']['start']} ~ {out['period']['end']}  
> 交易成本: {out['cost_rate_bps']}bps (ETF双边，含佣金+过户费)  
> 信号来源: **真实历史 AIAE_V1 序列**（总市值/M2，非价格代理）

---

## 1. 五策略对比

| 策略 | 年化收益 | 最大回撤 | Sharpe | Calmar | Alpha | 评级 |
|------|---------|---------|--------|--------|-------|------|"""]

        for name, res in strats.items():
            m = res.get("metrics", {})
            g = res.get("grade", "-")
            s = res.get("score", 0)
            lines.append(
                f"| {name} "
                f"| {m.get('annualized_return',0):.1f}% "
                f"| {m.get('max_drawdown',0):.1f}% "
                f"| {m.get('sharpe_ratio',0):.2f} "
                f"| {m.get('calmar_ratio',0):.2f} "
                f"| {m.get('alpha_pct',0):+.1f}% "
                f"| {g}({s}分) |"
            )

        lines.append(f"""
---

## 2. 主策略详细指标

| 指标 | 主策略 | 沪深300基准 |
|------|--------|------------|
| 年化收益 | {main_m.get('annualized_return',0):.1f}% | {bm0_m.get('annualized_return',0):.1f}% |
| 年化波动 | {main_m.get('annualized_vol',0):.1f}% | {bm0_m.get('annualized_vol',0):.1f}% |
| 最大回撤 | {main_m.get('max_drawdown',0):.1f}% | {bm0_m.get('max_drawdown',0):.1f}% |
| Sharpe   | {main_m.get('sharpe_ratio',0):.2f} | {bm0_m.get('sharpe_ratio',0):.2f} |
| Sortino  | {main_m.get('sortino_ratio',0):.2f} | — |
| Calmar   | {main_m.get('calmar_ratio',0):.2f} | {bm0_m.get('calmar_ratio',0):.2f} |
| Alpha    | {main_m.get('alpha_pct',0):+.1f}% | — |
| Beta     | {main_m.get('beta',0):.2f} | 1.00 |
| 月胜率   | {main_m.get('monthly_win_rate',0):.0f}% | {bm0_m.get('monthly_win_rate',0):.0f}% |
| VaR(95%) | {main_m.get('var_95_pct',0):.2f}% | {bm0_m.get('var_95_pct',0):.2f}% |
| 年化换手 | {main.get('annual_turnover',0):.1f}次 | — |

---

## 3. 择时有效性分析

| 指标 | 数值 |
|------|------|
| 看空信号次数 (R4/R5) | {ta.get('total_bearish_signals',0)} |
| 看空后次月确实下跌 | **{ta.get('bearish_hit_rate_pct',0):.1f}%** |
| 看多信号次数 (R1/R2) | {ta.get('total_bullish_signals',0)} |
| 看多后次月确实上涨 | **{ta.get('bullish_hit_rate_pct',0):.1f}%** |
| 仓位 vs 次月收益相关性 | {ta.get('position_vs_nextret_corr',0):.3f} |

### 各 Regime 月度表现

| Regime | 出现次数 | 平均月收益 | 月胜率 |
|--------|---------|---------|-------|""")

        for r, st in ta.get("regime_monthly_stats", {}).items():
            lines.append(
                f"| {r} | {st['count']} | {st['avg_ret_pct']:.2f}% | {st['win_rate_pct']:.0f}% |"
            )

        if fa:
            lines.append(f"""
---

## 4. 因子归因（边际贡献）

| 因子 | 年化收益贡献 |
|------|------------|
| AIAE_简 基线（双因子固定中性） | {fa.get('aiae_simple_only_ann_pct',0):.1f}% |
| + 融资热度（日频因子） | **{fa.get('margin_heat_contrib_bps',0):+.0f} bps** |
| + 基金仓位（季频因子） | **{fa.get('fund_pos_contrib_bps',0):+.0f} bps** |
| + ERP 交叉矩阵（利率维度） | **{fa.get('erp_contrib_bps',0):+.0f} bps** |
| 完整主策略 | **{fa.get('total_ann_pct',0):.1f}%** |""")

        lines.append("""
---

> [!NOTE]
> **数据质量说明**: 2014-2018年基金仓位使用分段估算值（见 FUND_POS_HISTORY），
> 该区间回测结论仅供参考，2019年后三因子数据完整，结论可信度高。

> [!CAUTION]
> **样本内偏差警告**: POSITION_MATRIX 分界线参数在已知历史基础上设定，
> 存在样本内优化偏差，回测结果仅验证策略逻辑，不代表未来预期收益。
""")

        report = "\n".join(lines)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        log.info(f"分析报告保存: {REPORT_FILE}")


# ─────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AIAE 回测引擎 V4")
    parser.add_argument("--start",  default="2014-01-01")
    parser.add_argument("--end",    default=None)
    parser.add_argument("--fast",   action="store_true",
                        help="跳过数据构建，直接使用现有 Parquet")
    parser.add_argument("--no-attr", action="store_true",
                        help="跳过因子归因（节省约30分钟）")
    args = parser.parse_args()

    if not args.fast and not os.path.exists(SIGNAL_FILE):
        log.info("信号文件不存在，启动数据重建 ...")
        from engines.aiae_data_builder import AIAEDataBuilder
        AIAEDataBuilder().build(
            start_month=args.start[:7],
            end_month=(args.end or datetime.now().strftime("%Y-%m")),
        )

    bt = AIAEBacktestV4(start=args.start, end=args.end or datetime.now().strftime("%Y-%m-%d"))
    output = bt.run(skip_attribution=args.no_attr)
    bt.save(output)

    # 终端快报
    print("\n" + "=" * 60)
    print("  AIAE V4 回测结果快报")
    print("=" * 60)
    for name, res in output["strategies"].items():
        m = res["metrics"]
        g = res.get("grade", "-")
        print(f"  {name[:30]:30s} | CAGR={m.get('annualized_return',0):+5.1f}%"
              f" | MDD={m.get('max_drawdown',0):5.1f}%"
              f" | Sharpe={m.get('sharpe_ratio',0):5.2f}"
              f" | {g}")
    ta = output["timing_analysis"]
    print(f"\n  看空击中率: {ta.get('bearish_hit_rate_pct',0):.1f}%  "
          f"看多击中率: {ta.get('bullish_hit_rate_pct',0):.1f}%")
    fa = output.get("factor_attribution", {})
    if fa:
        print(f"  因子归因: 主策略={fa.get('total_ann_pct',0):.1f}% "
              f"(ERP贡献={fa.get('erp_contrib_bps',0):+.0f}bps "
              f"融资={fa.get('margin_heat_contrib_bps',0):+.0f}bps "
              f"基金仓位={fa.get('fund_pos_contrib_bps',0):+.0f}bps)")
    print("=" * 60)
