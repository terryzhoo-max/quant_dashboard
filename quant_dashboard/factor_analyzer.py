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

        # === 6. 多空收益差 (Long-Short Spread) ===
        if len(q_avg) >= 2:
            ls_spread = float(q_avg.iloc[-1] - q_avg.iloc[0])
        else:
            ls_spread = 0

        # === 7. Alpha Score 综合评分 (0-100, 6维加权) ===
        alpha_score, score_breakdown = self._calculate_alpha_score(
            ic_mean, ir, ic_win_rate, monotonicity, ic_stability, ls_spread
        )

        # === 8. 因子质量评级 (6-tier: S/A/B/C/D/F) ===
        grade = self._score_to_grade(alpha_score)

        # === 9. 交易建议生成 ===
        advice = self._generate_trade_advice(
            alpha_score, grade, ic_mean, ic_win_rate,
            monotonicity, ic_stability, ls_spread, q_avg
        )

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
            "alpha_score": alpha_score,
            "score_breakdown": score_breakdown,
            "advice": advice,
        }

    # ================================================================
    #  Alpha Score Engine (MSCI Barra 参考框架)
    # ================================================================

    def _calculate_alpha_score(self, ic_mean, ir, ic_win_rate,
                               monotonicity, ic_stability, ls_spread):
        """
        6 维加权综合评分 (0-100)
        权重依据: IC强度(25%) > IR稳定(20%) = 胜率(20%) > 单调性(15%) > 时效(10%) = 盈利(10%)
        """
        s_ic = min(100, abs(ic_mean) / 0.05 * 100)           # IC 强度
        s_ir = min(100, abs(ir) / 0.6 * 100)                  # IR 稳定
        s_win = min(100, ic_win_rate / 0.70 * 100)            # IC 胜率
        s_mono = monotonicity * 100                            # 单调性
        s_stab = max(0, min(100, (1 - abs(ic_stability - 1)) * 100))  # 时效性
        s_ls = min(100, abs(ls_spread) / 0.005 * 100)         # 多空盈利

        weights = {
            'ic_strength': 0.25,
            'ir_stability': 0.20,
            'win_rate': 0.20,
            'monotonicity': 0.15,
            'decay_health': 0.10,
            'ls_profit': 0.10,
        }

        score = (
            weights['ic_strength'] * s_ic +
            weights['ir_stability'] * s_ir +
            weights['win_rate'] * s_win +
            weights['monotonicity'] * s_mono +
            weights['decay_health'] * s_stab +
            weights['ls_profit'] * s_ls
        )

        breakdown = {
            'ic_strength': round(s_ic, 1),
            'ir_stability': round(s_ir, 1),
            'win_rate': round(s_win, 1),
            'monotonicity': round(s_mono, 1),
            'decay_health': round(s_stab, 1),
            'ls_profit': round(s_ls, 1),
        }

        return round(score, 1), breakdown

    @staticmethod
    def _score_to_grade(score):
        """Alpha Score → 6级评级"""
        if score >= 80:
            return 'S'
        elif score >= 60:
            return 'A'
        elif score >= 45:
            return 'B'
        elif score >= 30:
            return 'C'
        elif score >= 15:
            return 'D'
        else:
            return 'F'

    def _generate_trade_advice(self, alpha_score, grade, ic_mean, ic_win_rate,
                                monotonicity, ic_stability, ls_spread, q_avg):
        """
        交易建议生成器 — 基于统计推断，非预测
        """
        # 1. 信号强度
        if alpha_score >= 60 and monotonicity >= 0.7:
            signal = 'STRONG_BUY'
            signal_label = '强烈看多'
            signal_color = '#10b981'
        elif alpha_score >= 45 and ic_mean > 0:
            signal = 'BUY'
            signal_label = '适度看多'
            signal_color = '#34d399'
        elif alpha_score >= 30:
            signal = 'NEUTRAL'
            signal_label = '中性观望'
            signal_color = '#fbbf24'
        else:
            signal = 'AVOID'
            signal_label = '规避'
            signal_color = '#f87171'

        # 2. 持有期 (基于5日IC窗口)
        hold_period = '5-10 个交易日'

        # 3. 止盈/止损 (基于Q5组的历史统计)
        if len(q_avg) >= 2:
            q5_avg = float(q_avg.iloc[-1])  # 最优分组的日均收益
            target_ret = round(abs(q5_avg) * 5 * 100, 2)  # 5日累计 → 百分比
            target_ret = max(target_ret, 0.5)  # 至少 0.5%
        else:
            target_ret = 2.0

        stop_loss = round(max(2.0, target_ret * 0.5), 2)  # 止损不低于 2%

        # 4. 仓位建议 (简化凯利公式)
        if ic_win_rate > 0 and target_ret > 0 and stop_loss > 0:
            payoff_ratio = target_ret / stop_loss
            kelly = max(0, (ic_win_rate * payoff_ratio - (1 - ic_win_rate)) / payoff_ratio)
            position_pct = round(min(30, kelly * 100), 1)
        else:
            position_pct = 0

        # 5. 置信度
        confidence = round(min(95, alpha_score * 1.1), 1)

        # 6. 动态风险提示
        risks = []
        if ic_stability > 1.5:
            risks.append(f'IC 近期放大({ic_stability:.1f}×)，可能是短期异常，建议减半仓位')
        elif ic_stability < 0.5:
            risks.append(f'IC 显著衰减({ic_stability:.1f}×)，因子可能已失效')
        if monotonicity < 0.5:
            risks.append(f'分组单调性不足({monotonicity:.2f})，选股区分力弱')
        if ic_win_rate < 0.5:
            risks.append('IC 胜率低于 50%，因子方向不稳定')
        if ls_spread < 0:
            risks.append('多空收益为负，做多高分组反而亏损')
        if alpha_score < 30:
            risks.append('综合评分过低，不建议作为交易依据')
        if not risks:
            risks.append('当前因子状态健康，无重大风险信号')

        return {
            'signal': signal,
            'signal_label': signal_label,
            'signal_color': signal_color,
            'hold_period': hold_period,
            'target_ret': target_ret,
            'stop_loss': stop_loss,
            'position_pct': position_pct,
            'confidence': confidence,
            'risks': risks,
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
