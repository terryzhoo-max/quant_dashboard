"""
AlphaCore Factor Analyzer V5.0
科学因子评估引擎：IC分布 + 分组收益 + 质量评级 + 技术因子 + IC直方图
"""
import pandas as pd
import numpy as np
import os
from scipy.stats import spearmanr
from data_manager import FactorDataManager

# V5.0: 技术因子列表 (从日线数据计算，无需财务报表)
TECHNICAL_FACTORS = {'momentum_20d', 'volatility_20d', 'turnover_rate'}

def is_technical_factor(factor_name: str) -> bool:
    return factor_name in TECHNICAL_FACTORS


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
        V5.0: 统一入口 — 自动分派基本面因子 vs 技术因子
        """
        if is_technical_factor(factor_name):
            return self._prepare_technical_data(ts_codes, factor_name)
        return self._prepare_fundamental_data(ts_codes, factor_name)

    def _prepare_fundamental_data(self, ts_codes: list, factor_name: str):
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

        full_df = pd.concat([d for d in all_data if not d.empty])
        full_df = full_df.dropna(subset=[factor_name, 'next_5d_ret'])
        return full_df

    def _prepare_technical_data(self, ts_codes: list, factor_name: str):
        """
        V5.0: 从日线数据动态计算技术因子
        momentum_20d:   20日价格动量 (close / close_20d_ago - 1)
        volatility_20d: 20日收益波动率 (日收益率的20日滚动标准差)
        turnover_rate:   换手率 (vol / 流通股本的代理: 20日均vol比)
        """
        all_data = []
        for code in ts_codes:
            p_df = self.dm.get_price_payload(code)
            if p_df.empty or len(p_df) < 25:
                continue

            df = p_df.sort_values('trade_date').copy()
            df['daily_ret'] = df['close'].pct_change()

            if factor_name == 'momentum_20d':
                df[factor_name] = df['close'] / df['close'].shift(20) - 1
            elif factor_name == 'volatility_20d':
                df[factor_name] = df['daily_ret'].rolling(20).std() * np.sqrt(252)
            elif factor_name == 'turnover_rate':
                if 'vol' in df.columns:
                    df[factor_name] = df['vol'] / df['vol'].rolling(20).mean()
                elif 'amount' in df.columns:
                    df[factor_name] = df['amount'] / df['amount'].rolling(20).mean()
                else:
                    continue

            df = df.dropna(subset=[factor_name, 'next_5d_ret'])
            if not df.empty:
                all_data.append(df)

        if not all_data:
            return pd.DataFrame()

        full_df = pd.concat([d for d in all_data if not d.empty])
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

        # === 7. Alpha Score 综合评分 (V4.0: A股实证校准) ===
        alpha_score, score_breakdown = self._calculate_alpha_score(
            ic_mean, ir, ic_win_rate, monotonicity, ic_stability, ls_spread,
            ic_clean=ic_clean
        )

        # === 8. 因子质量评级 (6-tier: S/A/B/C/D/F) ===
        grade = self._score_to_grade(alpha_score)

        # === 9. IC 分布诊断 (V5.0 增强: 含直方图) ===
        ic_distribution = self._calculate_ic_distribution(ic_clean)

        # === 10. 交易建议生成 (V4.0 增强) ===
        advice = self._generate_trade_advice(
            alpha_score, grade, ic_mean, ic_win_rate,
            monotonicity, ic_stability, ls_spread, q_avg
        )

        # === 11. 健康监控状态 (V4.0 新增) ===
        health_status = self._generate_health_status(
            ic_mean, ir, ic_win_rate, monotonicity,
            ic_stability, ls_spread, ic_distribution
        )

        # === 12. V5.0 IC 滚动窗口数据 (衰减趋势图) ===
        ic_rolling = self._calculate_ic_rolling(ic_clean)

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
            "ic_distribution": ic_distribution,
            "health_status": health_status,
            "ic_rolling": ic_rolling,
        }

    # ================================================================
    #  Alpha Score Engine V4.0 (A股实证校准)
    # ================================================================

    def _calculate_alpha_score(self, ic_mean, ir, ic_win_rate,
                               monotonicity, ic_stability, ls_spread,
                               ic_clean=None):
        """
        V4.0 6维加权综合评分 (0-100)
        校准依据: A股月频因子实证 (30只样本池)
        权重: IC强度(25%) > IR稳定(20%) = 胜率(20%) > 单调性(15%) > 时效(10%) = 盈利(10%)
        """
        # --- IC 强度: A股IC均值通常 0.02-0.04, 0.035为80%分位 ---
        s_ic = min(100, abs(ic_mean) / 0.035 * 100)

        # --- IR 稳定: A股IR通常 0.15-0.30, 0.35为优秀线 ---
        s_ir = min(100, abs(ir) / 0.35 * 100)

        # --- 胜率: 45%以下为随机噪音(0分), 70%满分 ---
        s_win = min(100, max(0, (ic_win_rate - 0.45) / 0.25 * 100))

        # --- 单调性: 不变 ---
        s_mono = monotonicity * 100

        # --- 时效性 V4.0: 线性衰减斜率法 ---
        if ic_clean is not None and len(ic_clean) >= 20:
            s_stab = self._calculate_decay_slope(ic_clean)
        else:
            s_stab = max(0, min(100, (1 - abs(ic_stability - 1)) * 100))

        # --- 多空盈利: 负值惩罚, 0.004为满分线 ---
        if ls_spread >= 0:
            s_ls = min(100, ls_spread / 0.004 * 100)
        else:
            s_ls = max(-50, ls_spread / 0.004 * 100)  # 负值最多扣50分

        weights = {
            'ic_strength': 0.25,
            'ir_stability': 0.20,
            'win_rate': 0.20,
            'monotonicity': 0.15,
            'decay_health': 0.10,
            'ls_profit': 0.10,
        }

        raw_score = (
            weights['ic_strength'] * s_ic +
            weights['ir_stability'] * s_ir +
            weights['win_rate'] * s_win +
            weights['monotonicity'] * s_mono +
            weights['decay_health'] * s_stab +
            weights['ls_profit'] * s_ls
        )
        score = max(0, min(100, raw_score))

        breakdown = {
            'ic_strength': round(max(0, s_ic), 1),
            'ir_stability': round(max(0, s_ir), 1),
            'win_rate': round(max(0, s_win), 1),
            'monotonicity': round(max(0, s_mono), 1),
            'decay_health': round(max(0, s_stab), 1),
            'ls_profit': round(max(0, s_ls), 1),
        }

        return round(score, 1), breakdown

    def _calculate_decay_slope(self, ic_clean):
        """
        V4.0: IC 线性回归斜率法 — 检测趋势性衰减/增强
        slope > 0 → 因子改善中; slope < 0 → 衰减中
        归一化到 [0, 100]
        """
        from scipy.stats import linregress
        try:
            x = np.arange(len(ic_clean))
            slope, _, _, _, _ = linregress(x, ic_clean.values)
            # 斜率 0 → 50分(中性), 正斜率加分, 负斜率减分
            normalized = max(0, min(100, (slope / 0.0001 + 1) * 50))
            return normalized
        except Exception:
            return 50.0  # 计算失败返回中性

    def _calculate_ic_distribution(self, ic_clean):
        """
        V5.0: IC 分布健康度诊断 + 直方图分箱数据
        """
        from scipy.stats import skew, kurtosis
        try:
            ic_vals = ic_clean.values
            ic_skew = float(skew(ic_vals))
            ic_kurt = float(kurtosis(ic_vals))
            skew_ok = abs(ic_skew) < 1.0
            kurt_ok = ic_kurt < 5.0

            # V5.0: 直方图分箱 (前端渲染用)
            n_bins = min(30, max(10, len(ic_vals) // 10))
            counts, bin_edges = np.histogram(ic_vals, bins=n_bins)
            bin_centers = [(bin_edges[i] + bin_edges[i+1]) / 2 for i in range(len(counts))]

            return {
                'skewness': round(ic_skew, 2),
                'kurtosis': round(ic_kurt, 2),
                'skew_status': 'normal' if skew_ok else 'warning',
                'kurt_status': 'normal' if kurt_ok else 'warning',
                'histogram': {
                    'bins': [round(x, 4) for x in bin_centers],
                    'counts': [int(x) for x in counts],
                    'mean': round(float(np.mean(ic_vals)), 4),
                    'std': round(float(np.std(ic_vals)), 4),
                }
            }
        except Exception:
            return {'skewness': 0, 'kurtosis': 0,
                    'skew_status': 'normal', 'kurt_status': 'normal',
                    'histogram': {'bins': [], 'counts': [], 'mean': 0, 'std': 0}}

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
        V4.0 交易建议生成器
        新增: 多条件信号矩阵, 三档止盈, 动态止损, Half-Kelly, 动态持有期, 决策推理链
        """
        # === 1. 信号强度 (多条件矩阵 V4.0) ===
        if (alpha_score >= 60 and monotonicity >= 0.7
                and ic_win_rate >= 0.55 and ls_spread > 0):
            signal = 'STRONG_BUY'
            signal_label = '强烈看多'
            signal_color = '#10b981'
        elif (alpha_score >= 45 and ic_mean > 0
              and (monotonicity >= 0.5 or ic_win_rate >= 0.55)):
            signal = 'BUY'
            signal_label = '适度看多'
            signal_color = '#34d399'
        elif (alpha_score >= 25
              and ls_spread >= 0 and ic_win_rate >= 0.45):
            signal = 'NEUTRAL'
            signal_label = '中性观望'
            signal_color = '#fbbf24'
        else:
            signal = 'AVOID'
            signal_label = '规避'
            signal_color = '#f87171'

        # === 2. 动态持有期 (基于IC衰减速度 V4.0) ===
        if ic_stability > 1.2:
            hold_period = '7-15 个交易日'
            hold_note = 'IC 趋势增强，可延长持有'
        elif ic_stability > 0.7:
            hold_period = '5-10 个交易日'
            hold_note = 'IC 稳定，标准持有窗口'
        else:
            hold_period = '3-5 个交易日'
            hold_note = 'IC 衰减中，快进快出'

        # === 3. 三档止盈 (T1保守/T2中性/T3激进 V4.0) ===
        if len(q_avg) >= 2:
            q5_avg = float(q_avg.iloc[-1])
            q5_std = float(q_avg.std()) if len(q_avg) >= 3 else abs(q5_avg) * 0.5
            t2 = round(abs(q5_avg) * 5 * 100, 2)  # 5日累计
            t2 = max(t2, 0.5)
            t1 = round(t2 * 0.7, 2)               # 保守: 打7折
            t1 = max(t1, 0.3)
            t3 = round((abs(q5_avg) * 5 + q5_std) * 100, 2)  # 加1σ
            t3 = max(t3, t2 * 1.3)
        else:
            t1, t2, t3 = 0.5, 1.0, 2.0

        # === 4. 动态止损 (基于Q5波动率 V4.0) ===
        if len(q_avg) >= 2:
            q5_daily_std = float(q_avg.std()) if len(q_avg) >= 3 else abs(float(q_avg.iloc[-1])) * 0.8
            stop_loss = round(max(1.5, min(5.0, q5_daily_std * 5 * 2 * 100)), 2)
        else:
            stop_loss = 2.5

        # === 5. 仓位 (Half-Kelly V4.0) ===
        if ic_win_rate > 0.45 and t2 > 0 and stop_loss > 0:
            payoff_ratio = t2 / stop_loss
            kelly = max(0, (ic_win_rate * payoff_ratio - (1 - ic_win_rate)) / payoff_ratio)
            half_kelly = kelly / 2  # 半凯利
            position_pct = round(min(25, half_kelly * 100), 1)
        else:
            position_pct = 0

        # === 6. 置信度 ===
        confidence = round(min(95, alpha_score * 1.1), 1)

        # === 7. 动态风险提示 ===
        risks = []
        if ic_stability > 1.5:
            risks.append({
                'level': 'warn',
                'text': f'IC 近期放大({ic_stability:.1f}×)，可能是短期异常，建议减半仓位'
            })
        elif ic_stability < 0.5:
            risks.append({
                'level': 'danger',
                'text': f'IC 显著衰减({ic_stability:.1f}×)，因子可能已失效'
            })
        if monotonicity < 0.5:
            risks.append({
                'level': 'warn',
                'text': f'分组单调性不足({monotonicity:.2f})，选股区分力弱'
            })
        if ic_win_rate < 0.5:
            risks.append({
                'level': 'warn' if ic_win_rate >= 0.45 else 'danger',
                'text': f'IC 胜率仅 {ic_win_rate:.1%}，因子方向不稳定'
            })
        if ls_spread < 0:
            risks.append({
                'level': 'danger',
                'text': '多空收益为负，做多高分组反而亏损'
            })
        if alpha_score < 25:
            risks.append({
                'level': 'danger',
                'text': '综合评分过低，不建议作为交易依据'
            })
        if not risks:
            risks.append({
                'level': 'ok',
                'text': '当前因子状态健康，无重大风险信号'
            })

        # === 8. 决策推理链 (V4.0 新增) ===
        reasoning = self._build_reasoning(
            alpha_score, grade, ic_mean, ir=None, ic_win_rate=ic_win_rate,
            monotonicity=monotonicity, ic_stability=ic_stability,
            ls_spread=ls_spread, signal_label=signal_label
        )

        return {
            'signal': signal,
            'signal_label': signal_label,
            'signal_color': signal_color,
            'hold_period': hold_period,
            'hold_note': hold_note,
            'target_t1': t1,
            'target_t2': t2,
            'target_t3': t3,
            'stop_loss': stop_loss,
            'position_pct': position_pct,
            'confidence': confidence,
            'risks': risks,
            'reasoning': reasoning,
        }

    def _build_reasoning(self, alpha_score, grade, ic_mean, ir,
                          ic_win_rate, monotonicity, ic_stability,
                          ls_spread, signal_label):
        """
        V4.0: 生成人话版决策推理链
        """
        parts = []

        # Alpha 评价
        grade_names = {'S': '顶级', 'A': '优质', 'B': '可用',
                       'C': '边缘', 'D': '噪音', 'F': '无效'}
        parts.append(f'因子综合评分 {alpha_score} ({grade}级·{grade_names.get(grade, "")}因子)')

        # IC 评价
        if abs(ic_mean) >= 0.03:
            parts.append(f'IC均值 {ic_mean:.4f} 超过可用线(0.03)，因子具备选股预测力')
        elif abs(ic_mean) >= 0.01:
            parts.append(f'IC均值 {ic_mean:.4f} 偏低但非随机，因子有微弱信号')
        else:
            parts.append(f'IC均值 {ic_mean:.4f} 接近零，因子几乎无预测力')

        # 胜率评价
        if ic_win_rate >= 0.6:
            parts.append(f'IC胜率 {ic_win_rate:.1%} 方向稳定')
        elif ic_win_rate >= 0.5:
            parts.append(f'IC胜率 {ic_win_rate:.1%} 略高于随机')
        else:
            parts.append(f'IC胜率 {ic_win_rate:.1%} 低于50%，方向不可靠')

        # 单调性评价
        if monotonicity >= 0.8:
            parts.append('分组收益呈完美阶梯状')
        elif monotonicity >= 0.5:
            parts.append(f'单调性 {monotonicity:.2f}，排序能力一般')
        else:
            parts.append(f'单调性仅 {monotonicity:.2f}，选股区分力弱')

        # 多空评价
        if ls_spread > 0:
            parts.append(f'多空价差 +{ls_spread*10000:.1f}bp，做多有正收益')
        else:
            parts.append(f'多空价差 {ls_spread*10000:.1f}bp 为负，做多反亏')

        # 结论
        parts.append(f'综合判定: {signal_label}')

        return '。'.join(parts) + '。'

    def _generate_health_status(self, ic_mean, ir, ic_win_rate,
                                 monotonicity, ic_stability, ls_spread,
                                 ic_distribution):
        """
        V4.0: 指标健康监控面板数据
        每个指标返回: status(ok/warn/danger/dead) + label
        """
        items = []

        # IC 方向
        if abs(ic_mean) >= 0.03:
            items.append({'key': 'ic_direction', 'label': 'IC方向', 'status': 'ok', 'detail': f'{ic_mean:.4f}'})
        elif abs(ic_mean) >= 0.01:
            items.append({'key': 'ic_direction', 'label': 'IC方向', 'status': 'warn', 'detail': f'{ic_mean:.4f} 偏弱'})
        else:
            items.append({'key': 'ic_direction', 'label': 'IC方向', 'status': 'danger', 'detail': f'{ic_mean:.4f} 无信号'})

        # IR 稳定性
        if abs(ir) >= 0.3:
            items.append({'key': 'ir_quality', 'label': 'IR质量', 'status': 'ok', 'detail': f'{ir:.3f}'})
        elif abs(ir) >= 0.1:
            items.append({'key': 'ir_quality', 'label': 'IR质量', 'status': 'warn', 'detail': f'{ir:.3f} 噪声大'})
        else:
            items.append({'key': 'ir_quality', 'label': 'IR质量', 'status': 'danger', 'detail': f'{ir:.3f} 极不稳定'})

        # 胜率
        if ic_win_rate >= 0.55:
            items.append({'key': 'win_rate', 'label': '胜率', 'status': 'ok', 'detail': f'{ic_win_rate:.1%}'})
        elif ic_win_rate >= 0.45:
            items.append({'key': 'win_rate', 'label': '胜率', 'status': 'warn', 'detail': f'{ic_win_rate:.1%}'})
        else:
            items.append({'key': 'win_rate', 'label': '胜率', 'status': 'danger', 'detail': f'{ic_win_rate:.1%} 随机'})

        # 时效性
        if 0.7 <= ic_stability <= 1.3:
            items.append({'key': 'decay', 'label': '时效', 'status': 'ok', 'detail': f'{ic_stability:.2f}x'})
        elif 0.5 <= ic_stability <= 1.5:
            items.append({'key': 'decay', 'label': '时效', 'status': 'warn', 'detail': f'{ic_stability:.2f}x'})
        else:
            items.append({'key': 'decay', 'label': '时效', 'status': 'danger', 'detail': f'{ic_stability:.2f}x 异常'})

        # 多空
        if ls_spread > 0.001:
            items.append({'key': 'ls_spread', 'label': '多空', 'status': 'ok', 'detail': f'+{ls_spread*10000:.1f}bp'})
        elif ls_spread >= 0:
            items.append({'key': 'ls_spread', 'label': '多空', 'status': 'warn', 'detail': f'{ls_spread*10000:.1f}bp 微弱'})
        else:
            items.append({'key': 'ls_spread', 'label': '多空', 'status': 'danger', 'detail': f'{ls_spread*10000:.1f}bp 亏损'})

        # IC 分布
        if ic_distribution:
            dist_ok = (ic_distribution['skew_status'] == 'normal'
                       and ic_distribution['kurt_status'] == 'normal')
            items.append({
                'key': 'distribution', 'label': '分布',
                'status': 'ok' if dist_ok else 'warn',
                'detail': f'偏度{ic_distribution["skewness"]:.1f} 峰度{ic_distribution["kurtosis"]:.1f}'
            })

        return items

    def _calculate_ic_rolling(self, ic_clean, window=20):
        """
        V5.0: 滚动IC均值/胜率 (前端衰减趋势图用)
        返回: dates, rolling_mean, rolling_win_rate
        """
        if len(ic_clean) < window:
            return {'dates': [], 'rolling_mean': [], 'rolling_win_rate': []}
        try:
            rolling_mean = ic_clean.rolling(window).mean().dropna()
            rolling_wr = ic_clean.rolling(window).apply(
                lambda x: (x > 0).mean(), raw=True
            ).dropna()
            # align indices
            common_idx = rolling_mean.index.intersection(rolling_wr.index)
            return {
                'dates': [d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d) for d in common_idx],
                'rolling_mean': [round(float(rolling_mean.loc[d]), 5) for d in common_idx],
                'rolling_win_rate': [round(float(rolling_wr.loc[d]), 3) for d in common_idx],
            }
        except Exception:
            return {'dates': [], 'rolling_mean': [], 'rolling_win_rate': []}


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
