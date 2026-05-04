"""
AlphaCore · 行业动量轮动回测引擎 V2.0
====================================================
框架：向量化多因子复合评分 + 5年网格搜索参数优化
目标：在2021-2025年完整周期内稳定跑赢沪深300ETF

核心模块：
1. MomentumBacktester     - 多因子评分 + 向量化回测循环
2. ParameterOptimizer     - 网格搜索 (param grid search)
3. PerformanceEvaluator   - 绩效指标矩阵 (Alpha/Sharpe/MaxDD/IR)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data_manager import FactorDataManager
import traceback

# ====================================================================
#  标的池定义（与 V1.0 兼容，20只行业ETF）
# ====================================================================
MOMENTUM_POOL_V2 = [
    # 科技AI（6只）
    {"code": "512480.SH", "name": "半导体ETF",         "group": "科技AI"},
    {"code": "588200.SH", "name": "科创芯片ETF",       "group": "科技AI"},
    {"code": "159995.SZ", "name": "芯片ETF",           "group": "科技AI"},
    {"code": "515070.SH", "name": "人工智能AIETF",     "group": "科技AI"},
    {"code": "159819.SZ", "name": "人工智能ETF",       "group": "科技AI"},
    {"code": "515880.SH", "name": "通信ETF",           "group": "科技AI"},
    # 新能源周期（5只）
    {"code": "516160.SH", "name": "新能源ETF",         "group": "新能源周期"},
    {"code": "515790.SH", "name": "光伏ETF",           "group": "新能源周期"},
    {"code": "512400.SH", "name": "有色金属ETF",       "group": "新能源周期"},
    {"code": "159870.SZ", "name": "化工ETF",           "group": "新能源周期"},
    {"code": "562550.SH", "name": "绿电ETF",           "group": "新能源周期"},
    # 军工制造（5只）
    {"code": "512560.SH", "name": "军工ETF",           "group": "军工制造"},
    {"code": "159218.SZ", "name": "卫星ETF",           "group": "军工制造"},
    {"code": "562500.SH", "name": "机器人ETF",         "group": "军工制造"},
    {"code": "159326.SZ", "name": "电网设备ETF",       "group": "军工制造"},
    {"code": "159851.SZ", "name": "金融科技ETF",       "group": "军工制造"},
    # 港股消费（4只）
    {"code": "513130.SH", "name": "恒生科技ETF",       "group": "港股消费"},
    {"code": "513120.SH", "name": "港股创新药ETF",     "group": "港股消费"},
    {"code": "159869.SZ", "name": "游戏ETF",           "group": "港股消费"},
    {"code": "588220.SH", "name": "科创100ETF",        "group": "港股消费"},
]

BENCHMARK_CODE = "510300.SH"  # 沪深300ETF (基准)
RISK_FREE_RATE = 0.025        # 无风险利率 2.5%
TRANSACTION_COST = 0.0015     # 双边摩擦成本 0.15%

# ====================================================================
#  数据加载层（复用 DataManager 本地缓存）
# ====================================================================

def load_price_matrix(codes: list, start_date: str, end_date: str, dm: FactorDataManager) -> pd.DataFrame:
    """
    加载多只ETF的收盘价，拼合成 Price Matrix (dates x codes)
    依赖本地 data_lake parquet 缓存，不实时调用 API。
    """
    frames = {}
    for code in codes:
        try:
            df = dm.get_price_payload(code)
            if df.empty:
                continue
            df = df.set_index('trade_date')['close']
            df.index = pd.to_datetime(df.index)
            frames[code] = df
        except Exception as e:
            print(f"  [WARN] {code} 价格加载失败: {e}")

    if not frames:
        return pd.DataFrame()

    matrix = pd.DataFrame(frames)
    # 筛选日期范围
    s = pd.to_datetime(start_date)
    e = pd.to_datetime(end_date)
    matrix = matrix.loc[s:e]
    # 前向填充（处理节假日停牌）
    matrix = matrix.ffill().dropna(how='all')
    return matrix


# ====================================================================
#  MomentumBacktester — 核心回测引擎
# ====================================================================

class MomentumBacktester:
    """
    向量化行业动量轮动回测引擎 V2.0

    参数说明：
    - top_n            int     选取最强 N 个行业（3-6）
    - rebalance_days   int     调仓周期（5/10/15/20 交易日）
    - mom_s_window     int     短期动量回看窗口（15-30 交易日）
    - mom_m_window     int     中期动量回看窗口（45-90 交易日）
    - w_mom_s          float   短期动量权重
    - w_mom_m          float   中期动量权重
    - w_slope          float   趋势斜率权重
    - w_sharpe         float   波动调整收益权重
    - stop_loss        float   个别持仓止损线（-0.05 ~ None）
    - position_cap     float   总仓位上限（默认 0.85）
    - group_cap        float   单行业组上限（默认 0.40）
    """

    def __init__(self,
                 top_n: int = 4,
                 rebalance_days: int = 10,
                 mom_s_window: int = 20,
                 mom_m_window: int = 60,
                 w_mom_s: float = 0.40,
                 w_mom_m: float = 0.30,
                 w_slope: float = 0.15,
                 w_sharpe: float = 0.15,
                 stop_loss: float = -0.08,
                 position_cap: float = 0.85,
                 group_cap: float = 0.40,
                 hs300_filter: bool = True):

        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.mom_s_window = mom_s_window
        self.mom_m_window = mom_m_window
        self.w_mom_s   = w_mom_s
        self.w_mom_m   = w_mom_m
        self.w_slope   = w_slope
        self.w_sharpe  = w_sharpe
        self.stop_loss = stop_loss
        self.position_cap = position_cap
        self.group_cap = group_cap
        self.hs300_filter = hs300_filter

    # ------------------------------------------------------------------
    # 因子计算
    # ------------------------------------------------------------------

    def _compute_factors(self, price_matrix: pd.DataFrame) -> pd.DataFrame:
        """
        向量化计算4个子因子，返回 DataFrame (dates x codes)
        """
        codes = price_matrix.columns

        # 短期动量 (MOM_S): mom_s_window 日收益率
        mom_s = price_matrix.pct_change(self.mom_s_window)

        # 中期动量 (MOM_M): mom_m_window 日收益率
        mom_m = price_matrix.pct_change(self.mom_m_window)

        # 趋势斜率 (SLOPE): 线性回归斜率（标准化）
        slope = self._rolling_slope(price_matrix, self.mom_s_window)

        # 波动调整收益 (SHARPE): mom_s / rolling_std
        rolling_vol = price_matrix.pct_change().rolling(self.mom_s_window).std() * np.sqrt(252)
        sharpe_factor = mom_s / rolling_vol.replace(0, np.nan)

        # 跨截面标准化 (Z-Score，使各因子可比)
        def zscore(df):
            return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1).replace(0, 1), axis=0)

        mom_s_z  = zscore(mom_s)
        mom_m_z  = zscore(mom_m)
        slope_z  = zscore(slope)
        sharpe_z = zscore(sharpe_factor)

        # 合成评分
        composite = (
            self.w_mom_s   * mom_s_z +
            self.w_mom_m   * mom_m_z +
            self.w_slope   * slope_z +
            self.w_sharpe  * sharpe_z
        )
        return composite

    @staticmethod
    def _rolling_slope(price_matrix: pd.DataFrame, window: int) -> pd.DataFrame:
        """
        计算每个序列在 window 内的线性回归斜率（时间序列方向），向量化实现。
        """
        log_prices = np.log(price_matrix.replace(0, np.nan))
        x = np.arange(window)
        xm = x - x.mean()
        xvar = (xm ** 2).sum()

        result = pd.DataFrame(np.nan, index=price_matrix.index, columns=price_matrix.columns)
        arr = log_prices.values

        for i in range(window - 1, len(arr)):
            chunk = arr[i - window + 1: i + 1]  # shape: (window, n_codes)
            ym = chunk - chunk.mean(axis=0)
            slopes = (xm[:, None] * ym).sum(axis=0) / xvar
            result.iloc[i] = slopes

        return result

    # ------------------------------------------------------------------
    # 沪深300趋势过滤
    # ------------------------------------------------------------------

    def _hs300_regime(self, hs300_prices: pd.Series) -> pd.Series:
        """
        基于HS300 120日均线判断市场状态：
        - BULL (1): 站上MA120 且 MA120上行
        - RANGE (0.7): 站上MA120 但MA120走平或下行
        - BEAR (0.5): 跌破MA120
        返回每日仓位系数 (position_multiplier)
        """
        ma120 = hs300_prices.rolling(120).mean()
        ma120_slope = ma120.diff(5)

        regime = pd.Series('RANGE', index=hs300_prices.index)
        regime[hs300_prices > ma120] = 'BULL'
        regime[(hs300_prices > ma120) & (ma120_slope < 0)] = 'RANGE'
        regime[hs300_prices <= ma120] = 'BEAR'

        multiplier = regime.map({'BULL': 1.0, 'RANGE': 0.7, 'BEAR': 0.5})
        return multiplier

    # ------------------------------------------------------------------
    # 回测主循环
    # ------------------------------------------------------------------

    def run(self, price_matrix: pd.DataFrame, hs300_prices: pd.Series = None,
            group_map: dict = None) -> dict:
        """
        向量化回测主循环。
        
        参数：
        - price_matrix   : 价格矩阵 (DatetimeIndex x code)
        - hs300_prices   : 沪深300收盘价序列（用于趋势过滤）
        - group_map      : {code: group_name} 行业组映射
        
        返回：
        - portfolio_returns : pd.Series (日度策略收益)
        - holdings_log      : list of dicts (每次调仓记录)
        """
        if price_matrix.empty:
            return self._empty_result()

        # 计算因子评分矩阵
        scores = self._compute_factors(price_matrix)

        # 处理沪深300仓位系数
        if self.hs300_filter and hs300_prices is not None:
            aligned_hs300 = hs300_prices.reindex(price_matrix.index).ffill()
            pos_multiplier = self._hs300_regime(aligned_hs300)
        else:
            pos_multiplier = pd.Series(1.0, index=price_matrix.index)

        # 日度收益矩阵
        daily_returns = price_matrix.pct_change()

        # 初始化
        portfolio_values = [1.0]
        holdings = {}       # {code: weight}
        holdings_log = []
        cost_log = []
        dates = price_matrix.index.tolist()

        warmup = max(self.mom_m_window, 120) + 5  # 预热期（确保所有因子计算稳定）
        last_rebalance = warmup

        for i, date in enumerate(dates):
            if i < warmup:
                portfolio_values.append(portfolio_values[-1])
                continue

            # 计算当日组合收益（按持仓权重）
            if holdings:
                day_ret = sum(
                    w * daily_returns.loc[date, code]
                    if code in daily_returns.columns and pd.notna(daily_returns.loc[date, code])
                    else 0
                    for code, w in holdings.items()
                )
            else:
                day_ret = 0.0

            # 止损检查
            if self.stop_loss is not None:
                holdings = self._apply_stop_loss(
                    holdings, daily_returns, date, self.stop_loss
                )

            portfolio_values.append(portfolio_values[-1] * (1 + day_ret))

            # 调仓判断
            if i - last_rebalance >= self.rebalance_days:
                last_rebalance = i
                new_holdings = self._select_holdings(
                    scores, date, pos_multiplier.get(date, 1.0), group_map
                )

                # 交易成本
                if holdings or new_holdings:
                    turnover = self._compute_turnover(holdings, new_holdings)
                    cost = turnover * TRANSACTION_COST
                    portfolio_values[-1] *= (1 - cost)
                    cost_log.append({"date": str(date.date()), "cost": round(cost, 5)})

                holdings = new_holdings
                holdings_log.append({
                    "date": str(date.date()),
                    "holdings": {k: round(v, 3) for k, v in holdings.items()},
                    "pos_multiplier": round(pos_multiplier.get(date, 1.0), 2),
                })

        # 转为日度收益率序列
        # portfolio_values 初始为 [1.0]，循环中每日 append，共 1+len(dates) 个值
        # 取 [1+warmup:] 跳过哨兵值和预热期，与 dates[warmup:] 等长
        pv = pd.Series(portfolio_values[1 + warmup:], index=dates[warmup:])
        returns = pv.pct_change().dropna()

        return {
            "portfolio_values": pv,
            "portfolio_returns": returns,
            "holdings_log": holdings_log,
            "cost_log": cost_log,
        }

    def _select_holdings(self, scores: pd.DataFrame, date, pos_mult: float,
                         group_map: dict) -> dict:
        """在给定日期，根据因子评分选出 Top N 标的，分配权重"""
        if date not in scores.index:
            return {}

        row = scores.loc[date].dropna().sort_values(ascending=False)
        if row.empty:
            return {}

        # 选 Top N（控制行业组集中度）
        selected = []
        group_exposure = {}
        for code in row.index:
            g = group_map.get(code, "OTHER") if group_map else "OTHER"
            if len(selected) >= self.top_n:
                break
            if group_exposure.get(g, 0) >= 2:  # 同行业组最多选2只
                continue
            selected.append(code)
            group_exposure[g] = group_exposure.get(g, 0) + 1

        if not selected:
            return {}

        # 按评分比例分配权重（上限 self.position_cap / top_n * 1.5）
        raw_scores = row[selected]
        raw_scores = raw_scores - raw_scores.min() + 1e-6  # 确保全正
        weights = raw_scores / raw_scores.sum() * self.position_cap * pos_mult
        weights = weights.clip(upper=self.position_cap / max(1, self.top_n - 1))

        return weights.to_dict()

    @staticmethod
    def _compute_turnover(old_h: dict, new_h: dict) -> float:
        """计算换手率：所有权重变动之和的一半"""
        all_codes = set(old_h) | set(new_h)
        return sum(abs(new_h.get(c, 0) - old_h.get(c, 0)) for c in all_codes) / 2

    @staticmethod
    def _apply_stop_loss(holdings: dict, daily_returns: pd.DataFrame,
                         date, stop_loss_pct: float) -> dict:
        """对当日超过止损线的持仓清零"""
        remaining = {}
        for code, weight in holdings.items():
            if code in daily_returns.columns:
                ret = daily_returns.loc[date, code] if date in daily_returns.index else 0
                if pd.notna(ret) and ret <= stop_loss_pct:
                    continue  # 触发止损，清零
            remaining[code] = weight
        return remaining

    @staticmethod
    def _empty_result() -> dict:
        return {
            "portfolio_values": pd.Series(dtype=float),
            "portfolio_returns": pd.Series(dtype=float),
            "holdings_log": [],
            "cost_log": [],
        }


# ====================================================================
#  PerformanceEvaluator — 绩效评估矩阵
# ====================================================================

class PerformanceEvaluator:
    """计算完整的量化绩效指标矩阵"""

    @staticmethod
    def evaluate(returns: pd.Series, benchmark_returns: pd.Series = None,
                 label: str = "Strategy") -> dict:
        """
        参数：
        - returns            : 日度策略收益率序列
        - benchmark_returns  : 日度基准收益率（用于Alpha/IR计算）
        - label              : 策略名称标签
        
        返回：完整绩效字典
        """
        if returns.empty or len(returns) < 20:
            return {"error": "数据不足，无法评估"}

        ret = returns.dropna()
        n_days = len(ret)
        n_years = n_days / 252

        # ---- 基础收益指标 ----
        cum_return = float((1 + ret).prod() - 1)
        cagr = float((1 + cum_return) ** (1 / n_years) - 1) if n_years > 0 else 0

        # ---- 最大回撤 ----
        pv = (1 + ret).cumprod()
        drawdown = pv / pv.cummax() - 1
        max_dd = float(drawdown.min())

        # ---- 夏普比率 ----
        ann_vol = float(ret.std() * np.sqrt(252))
        sharpe = (cagr - RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0

        # ---- Calmar 比率 ----
        calmar = cagr / abs(max_dd) if max_dd < 0 else float('inf')

        # ---- 月度胜率 & 超额 ----
        monthly = ret.resample('ME').apply(lambda x: (1 + x).prod() - 1)
        win_rate = float((monthly > 0).sum() / len(monthly)) if len(monthly) > 0 else 0

        result = {
            "label": label,
            "n_days": int(n_days),
            "cum_return": round(cum_return * 100, 2),
            "cagr": round(cagr * 100, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "ann_vol": round(ann_vol * 100, 2),
            "sharpe": round(sharpe, 3),
            "calmar": round(calmar, 3),
            "monthly_win_rate": round(win_rate * 100, 1),
            "monthly_returns": {str(k.date()): round(v * 100, 2) for k, v in monthly.items()},
            "portfolio_values": [(1 + ret[:i+1]).prod() for i in range(len(ret))],
        }

        # ---- 超额收益指标（vs 基准）----
        if benchmark_returns is not None and not benchmark_returns.empty:
            bench = benchmark_returns.reindex(ret.index).ffill().dropna()
            excess = ret - bench.reindex(ret.index).fillna(0)

            excess_cum = float((1 + excess).prod() - 1)
            excess_cagr = float((1 + excess_cum) ** (1 / n_years) - 1) if n_years > 0 else 0
            te = float(excess.std() * np.sqrt(252))  # 跟踪误差
            ir = excess_cagr / te if te > 0 else 0

            bench_pv = (1 + bench).cumprod()
            bench_dd = bench_pv / bench_pv.cummax() - 1
            bench_max_dd = float(bench_dd.min())
            bench_cagr = float((bench_pv.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0

            monthly_bench = bench.resample('ME').apply(lambda x: (1 + x).prod() - 1)
            monthly_excess = monthly - monthly_bench.reindex(monthly.index).fillna(0)
            excess_win_rate = float((monthly_excess > 0).sum() / len(monthly_excess)) if len(monthly_excess) > 0 else 0

            result.update({
                "excess_cum_return": round(excess_cum * 100, 2),
                "excess_cagr": round(excess_cagr * 100, 2),
                "tracking_error": round(te * 100, 2),
                "information_ratio": round(ir, 3),
                "excess_win_rate": round(excess_win_rate * 100, 1),
                "benchmark_cagr": round(bench_cagr * 100, 2),
                "benchmark_max_dd": round(bench_max_dd * 100, 2),
                "benchmark_values": [(1 + bench[:i+1]).prod() for i in range(len(bench))],
                "dates": [str(d.date()) for d in ret.index],
            })

        return result


# ====================================================================
#  ParameterOptimizer — 网格搜索参数优化
# ====================================================================

class ParameterOptimizer:
    """
    对 MomentumBacktester 核心参数进行网格搜索，
    在样本内找到最优参数（综合评分最高），
    并在样本外验证是否稳健。
    """

    PARAM_GRID = {
        "top_n":          [3, 4, 5],
        "rebalance_days": [5, 10, 15],
        "mom_s_window":   [15, 20, 30],
        "w_mom_s":        [0.35, 0.45],
        "stop_loss":      [-0.06, -0.08, None],
    }

    def __init__(self, price_matrix: pd.DataFrame, benchmark_returns: pd.Series,
                 hs300_prices: pd.Series, group_map: dict):
        self.price_matrix = price_matrix
        self.benchmark_returns = benchmark_returns
        self.hs300_prices = hs300_prices
        self.group_map = group_map

    def _score_params(self, perf: dict) -> float:
        """综合评分函数：为每套参数计算一个可比分数"""
        if not perf or "error" in perf:
            return -999

        sharpe = perf.get("sharpe", -999)
        excess_cagr = perf.get("excess_cagr", -999)
        max_dd = perf.get("max_drawdown", -100)
        ir = perf.get("information_ratio", -999)

        # 组合评分：夏普*30% + 超额CAGR*40% + 最大回撤惩罚*20% + IR*10%
        dd_score = max(0, 20 + max_dd) / 20  # DD 为负数，越差越小
        score = (
            0.30 * min(max(sharpe, -2), 3) +
            0.40 * min(max(excess_cagr / 10, -2), 3) +
            0.20 * dd_score +
            0.10 * min(max(ir, -2), 2)
        )
        return round(float(score), 4)

    def run(self, in_sample_end: str = "2023-12-31",
            out_sample_start: str = "2024-01-01") -> dict:
        """
        运行参数网格搜索.
        
        in_sample_end    : 样本内数据截止日（用于选参数）
        out_sample_start : 样本外验证开始（用于验证稳健性）
        """
        evaluator = PerformanceEvaluator()
        results = []
        total = 1
        for v in self.PARAM_GRID.values():
            total *= len(v)
        print(f"[Optimizer] 共 {total} 套参数组合，开始网格搜索...")

        # 生成所有参数组合
        from itertools import product
        keys = list(self.PARAM_GRID.keys())
        values = [self.PARAM_GRID[k] for k in keys]

        for i, combo in enumerate(product(*values)):
            params = dict(zip(keys, combo))
            try:
                bt = MomentumBacktester(
                    top_n=params["top_n"],
                    rebalance_days=params["rebalance_days"],
                    mom_s_window=params["mom_s_window"],
                    mom_m_window=params["mom_s_window"] * 3,  # 中期 = 短期 * 3
                    w_mom_s=params["w_mom_s"],
                    w_mom_m=round(1 - params["w_mom_s"] - 0.30, 2),
                    w_slope=0.15,
                    w_sharpe=0.15,
                    stop_loss=params["stop_loss"],
                )

                # 样本内回测
                pm_in = self.price_matrix.loc[:in_sample_end]
                result_in = bt.run(pm_in, self.hs300_prices, self.group_map)

                bench_in = self.benchmark_returns.loc[:in_sample_end]
                perf_in = PerformanceEvaluator.evaluate(
                    result_in["portfolio_returns"], bench_in, "In-Sample"
                )
                score_in = self._score_params(perf_in)

                entry = {
                    "params": params,
                    "in_sample": {
                        "sharpe": perf_in.get("sharpe"),
                        "excess_cagr": perf_in.get("excess_cagr"),
                        "max_dd": perf_in.get("max_drawdown"),
                        "ir": perf_in.get("information_ratio"),
                        "score": score_in,
                    }
                }
                results.append(entry)

                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{total}] 最优评分: {max(r['in_sample']['score'] for r in results):.4f}")

            except Exception as e:
                print(f"  [SKIP] params={combo}: {e}")
                continue

        if not results:
            return {"error": "全部参数组合失败"}

        # 找样本内最优参数
        results.sort(key=lambda r: r["in_sample"]["score"], reverse=True)
        best = results[0]
        print(f"[Optimizer] 最优参数: {best['params']}")
        print(f"[Optimizer] 样本内评分: {best['in_sample']['score']:.4f}, 超额CAGR: {best['in_sample']['excess_cagr']}%")

        # 样本外验证（防止过拟合）
        pm_out = self.price_matrix.loc[out_sample_start:]
        perf_oos = {}
        if not pm_out.empty:
            try:
                bp = best["params"]
                bt_best = MomentumBacktester(
                    top_n=bp["top_n"],
                    rebalance_days=bp["rebalance_days"],
                    mom_s_window=bp["mom_s_window"],
                    mom_m_window=bp["mom_s_window"] * 3,
                    w_mom_s=bp["w_mom_s"],
                    w_mom_m=round(1 - bp["w_mom_s"] - 0.30, 2),
                    w_slope=0.15,
                    w_sharpe=0.15,
                    stop_loss=bp["stop_loss"],
                )
                result_oos = bt_best.run(pm_out, self.hs300_prices, self.group_map)
                bench_oos = self.benchmark_returns.loc[out_sample_start:]
                perf_oos = PerformanceEvaluator.evaluate(
                    result_oos["portfolio_returns"], bench_oos, "Out-of-Sample"
                )
            except Exception as e:
                perf_oos = {"error": str(e)}

        # 汇总 Top 10 参数排行
        top10 = [
            {
                "rank": idx + 1,
                "params": r["params"],
                "score": r["in_sample"]["score"],
                "sharpe": r["in_sample"]["sharpe"],
                "excess_cagr": r["in_sample"]["excess_cagr"],
                "max_dd": r["in_sample"]["max_dd"],
                "ir": r["in_sample"]["ir"],
            }
            for idx, r in enumerate(results[:10])
        ]

        return {
            "best_params": best["params"],
            "in_sample_perf": best["in_sample"],
            "out_of_sample_perf": perf_oos,
            "top10_params": top10,
            "total_combinations": total,
            "tested": len(results),
        }


# ====================================================================
#  主入口函数（供 main.py 调用）
# ====================================================================

def run_momentum_backtest(start_date: str = "2021-01-01", end_date: str = "2025-12-31",
                          params: dict = None) -> dict:
    """
    运行行业动量轮动完整历史回测。
    
    参数：
    - start_date : 回测开始日期
    - end_date   : 回测结束日期（默认今天）
    - params     : 可选，自定义参数字典；不传则使用优化推荐参数
    
    返回：
    - 完整绩效报告字典（供前端展示）
    """
    print(f"[V2.0 Backtest] {start_date} → {end_date}")
    dm = FactorDataManager()

    all_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE]
    group_map = {etf["code"]: etf["group"] for etf in MOMENTUM_POOL_V2}

    # 加载价格矩阵
    price_matrix = load_price_matrix(all_codes, start_date, end_date, dm)
    if price_matrix.empty:
        return {"status": "error", "message": "无法获取历史数据，请先运行数据同步"}

    # 分离基准（沪深300ETF）& 策略标的
    benchmark_prices = price_matrix.get(BENCHMARK_CODE)
    strategy_prices = price_matrix.drop(columns=[BENCHMARK_CODE], errors='ignore')

    if strategy_prices.empty:
        return {"status": "error", "message": "策略标的数据为空"}

    benchmark_returns = benchmark_prices.pct_change().dropna() if benchmark_prices is not None else None

    # 加载HS300指数（用于市场状态过滤）
    hs300_prices = load_price_matrix(["000300.SH"], start_date, end_date, dm).get("000300.SH")

    if params is None:
        # 默认最优参数（基于预回测结果）
        params = {
            "top_n": 4,
            "rebalance_days": 10,
            "mom_s_window": 20,
            "mom_m_window": 60,
            "w_mom_s": 0.40,
            "w_mom_m": 0.30,
            "w_slope": 0.15,
            "w_sharpe": 0.15,
            "stop_loss": -0.08,
            "position_cap": 0.85,
        }

    bt = MomentumBacktester(**params)
    result = bt.run(strategy_prices, hs300_prices, group_map)

    perf = PerformanceEvaluator.evaluate(
        result["portfolio_returns"],
        benchmark_returns,
        label="行业动量轮动 V2.0"
    )

    return {
        "status": "success",
        "params": params,
        "performance": perf,
        "holdings_log": result["holdings_log"][-20:],
        "cost_log": result["cost_log"][-20:],
    }


def run_momentum_optimize(in_sample_end: str = "2023-12-31",
                          out_sample_start: str = "2024-01-01") -> dict:
    """
    运行参数优化（网格搜索）
    """
    print("[V2.0 Optimizer] 启动参数优化...")
    dm = FactorDataManager()

    all_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE]
    group_map = {etf["code"]: etf["group"] for etf in MOMENTUM_POOL_V2}

    price_matrix = load_price_matrix(all_codes, "2021-01-01", "2025-12-31", dm)
    if price_matrix.empty:
        return {"status": "error", "message": "无历史数据，请先同步"}

    benchmark_prices = price_matrix.get(BENCHMARK_CODE)
    strategy_prices = price_matrix.drop(columns=[BENCHMARK_CODE], errors='ignore')
    benchmark_returns = benchmark_prices.pct_change().dropna() if benchmark_prices is not None else None
    hs300_prices = load_price_matrix(["000300.SH"], "2021-01-01", "2025-12-31", dm).get("000300.SH")

    optimizer = ParameterOptimizer(strategy_prices, benchmark_returns, hs300_prices, group_map)
    result = optimizer.run(in_sample_end=in_sample_end, out_sample_start=out_sample_start)

    return {"status": "success", "data": result}


if __name__ == "__main__":
    import json
    print("=== 运行回测 ===")
    bt_result = run_momentum_backtest("2021-01-01", "2025-12-31")
    print(json.dumps({k: v for k, v in bt_result.items() if k != 'performance'}, ensure_ascii=False, indent=2))
    if "performance" in bt_result:
        p = bt_result["performance"]
        print(f"\n📊 绩效摘要:")
        print(f"  年化收益  : {p.get('cagr')}%")
        print(f"  超额收益  : {p.get('excess_cagr')}%")
        print(f"  最大回撤  : {p.get('max_drawdown')}%")
        print(f"  夏普比率  : {p.get('sharpe')}")
        print(f"  信息比率  : {p.get('information_ratio')}")
        print(f"  月度胜率  : {p.get('monthly_win_rate')}%")
