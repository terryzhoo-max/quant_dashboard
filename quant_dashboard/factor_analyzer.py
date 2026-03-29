"""
AlphaCore Factor Analyzer V2.0
科学因子评估引擎：IC分布 + 分组收益 + 质量评级
"""
import pandas as pd
import numpy as np
import os
from scipy.stats import spearmanr
from data_manager import FactorDataManager


class FactorAnalyzer:
    """
    V2.0 因子分析器
    新增: IC胜率、IC衰减、单调性评分、因子质量评级(A/B/C/D/F)
    """

    def __init__(self):
        self.dm = FactorDataManager()

    def _winsorize_mad(self, series: pd.Series, n: float = 3.0) -> pd.Series:
        """中位数绝对偏差 (MAD) 去极值"""
        median = series.median()
        mad = (series - median).abs().median()
        if mad == 0:
            return series
        lower_limit = median - n * 1.4826 * mad
        upper_limit = median + n * 1.4826 * mad
        return series.clip(lower_limit, upper_limit)

    def _standardize(self, series: pd.Series) -> pd.Series:
        """Z-Score 标准化"""
        std = series.std()
        if std == 0 or np.isnan(std):
            return series * 0
        return (series - series.mean()) / std

    def prepare_analysis_data(self, ts_codes: list, factor_name: str):
        """
        准备横截面分析数据 (对齐因子与未来收益)
        采用 Point-in-Time 方法，避免前视偏差
        """
        all_data = []
        for code in ts_codes:
            f_df = self.dm.get_factor_payload(code, [factor_name])
            if f_df.empty:
                continue
            f_df['ann_date'] = pd.to_datetime(f_df['ann_date'])

            p_df = self.dm.get_price_payload(code)
            if p_df.empty:
                continue

            merged = pd.merge_asof(
                p_df.sort_values('trade_date'),
                f_df.sort_values('ann_date'),
                left_on='trade_date',
                right_on='ann_date',
                direction='backward'
            )
            all_data.append(merged)

        if not all_data:
            return pd.DataFrame()

        full_df = pd.concat(all_data)
        full_df = full_df.dropna(subset=[factor_name, 'next_5d_ret'])
        return full_df

    def calculate_metrics(self, data: pd.DataFrame, factor_name: str):
        """
        V2.0 计算: IC分布 + 分组收益 + 质量评级
        """
        # === 1. 每日 Rank-IC ===
        def daily_rank_ic(group):
            if len(group) < 5:
                return np.nan
            processed_f = self._standardize(self._winsorize_mad(group[factor_name]))
            if processed_f.std() == 0:
                return np.nan
            ic, _ = spearmanr(processed_f, group['next_5d_ret'])
            return ic

        ic_series = data.groupby('trade_date').apply(daily_rank_ic)
        ic_clean = ic_series.dropna()

        # === 2. IC 核心统计 ===
        ic_mean = float(ic_clean.mean()) if len(ic_clean) > 0 else 0
        ic_std = float(ic_clean.std()) if len(ic_clean) > 0 else 1
        ir = ic_mean / ic_std if ic_std > 0 else 0
        ic_win_rate = float((ic_clean > 0).mean()) if len(ic_clean) > 0 else 0

        # === 3. 分组收益 (5-Quantile) ===
        def daily_quantile_returns(group):
            if len(group) < 5:
                return pd.Series(dtype=float)
            group = group.copy()
            group[f'{factor_name}_norm'] = self._standardize(
                self._winsorize_mad(group[factor_name])
            )
            try:
                group['quantile'] = pd.qcut(
                    group[f'{factor_name}_norm'], 5,
                    labels=False, duplicates='drop'
                )
                return group.groupby('quantile')['next_5d_ret'].mean()
            except Exception:
                return pd.Series(dtype=float)

        quantile_rets = data.groupby('trade_date').apply(daily_quantile_returns)

        # === 4. 单调性评分 (Monotonicity Score) ===
        # 先将嵌套 Series unstack 为 DataFrame (dates x quantiles)
        if isinstance(quantile_rets, pd.Series) and isinstance(quantile_rets.index, pd.MultiIndex):
            quantile_rets = quantile_rets.unstack()

        q_avg = quantile_rets.mean() if not quantile_rets.empty else pd.Series(dtype=float)

        # 确保 q_avg 是 Series 而非 scalar
        if isinstance(q_avg, (float, np.floating)):
            q_avg = pd.Series(dtype=float)

        if len(q_avg) >= 3:
            mono_corr, _ = spearmanr(range(len(q_avg)), q_avg.values)
            monotonicity = float(abs(mono_corr)) if not np.isnan(mono_corr) else 0
        else:
            monotonicity = 0

        # === 5. IC 衰减分析 (Decay) ===
        # 计算IC的20日移动平均的趋势
        if len(ic_clean) >= 20:
            ic_ma20 = ic_clean.rolling(20).mean().dropna()
            if len(ic_ma20) >= 2:
                # 后半段 vs 前半段的均值比
                half = len(ic_ma20) // 2
                recent_ic = float(ic_ma20.iloc[half:].mean())
                early_ic = float(ic_ma20.iloc[:half].mean())
                ic_stability = recent_ic / early_ic if abs(early_ic) > 0.001 else 1.0
                ic_stability = max(0, min(2, ic_stability))  # clamp 0~2
            else:
                ic_stability = 1.0
        else:
            ic_stability = 1.0

        # === 6. 因子质量评级 (Factor Grade) ===
        abs_ic = abs(ic_mean)
        abs_ir = abs(ir)

        if abs_ic > 0.05 and abs_ir > 0.5 and ic_win_rate > 0.65:
            grade = 'A'
        elif abs_ic > 0.03 and abs_ir > 0.3 and ic_win_rate > 0.55:
            grade = 'B'
        elif abs_ic > 0.02 and abs_ir > 0.2:
            grade = 'C'
        elif abs_ic > 0.01:
            grade = 'D'
        else:
            grade = 'F'

        # === 7. 多空收益差 (Long-Short Spread) ===
        if len(q_avg) >= 2:
            ls_spread = float(q_avg.iloc[-1] - q_avg.iloc[0])
        else:
            ls_spread = 0

        return {
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "ir": ir,
            "ic_win_rate": ic_win_rate,
            "ic_series": ic_series,
            "quantile_rets": quantile_rets,
            "monotonicity": monotonicity,
            "ic_stability": ic_stability,
            "grade": grade,
            "ls_spread": ls_spread,
        }


if __name__ == "__main__":
    analyzer = FactorAnalyzer()
    dm = FactorDataManager()

    stocks = dm.get_all_stocks().head(30)["ts_code"].tolist()
    print("正在检查/同步测试行情数据...")
    dm.sync_daily_prices(stocks)

    factor_to_test = "roe"
    print(f"正在对因子 [{factor_to_test}] 进行 IC 检测...")

    analysis_data = analyzer.prepare_analysis_data(stocks, factor_to_test)
    if not analysis_data.empty:
        results = analyzer.calculate_metrics(analysis_data, factor_to_test)
        print(f"\n====== 因子分析结果 [{factor_to_test}] ======")
        print(f"IC 均值: {results['ic_mean']:.4f}")
        print(f"IR 比率: {results['ir']:.4f}")
        print(f"IC 胜率: {results['ic_win_rate']:.2%}")
        print(f"单调性:  {results['monotonicity']:.2f}")
        print(f"评级:    {results['grade']}")
    else:
        print("未找到有效重合数据，请检查数据同步状态。")
