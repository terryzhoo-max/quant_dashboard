import pandas as pd
import numpy as np
import os
from scipy.stats import spearmanr
from data_manager import FactorDataManager

class FactorAnalyzer:
    def __init__(self):
        self.dm = FactorDataManager()

    def _winsorize_mad(self, series: pd.Series, n: float = 3.0) -> pd.Series:
        """中位数绝对偏差 (MAD) 去极值"""
        median = series.median()
        mad = (series - median).abs().median()
        lower_limit = median - n * 1.4826 * mad
        upper_limit = median + n * 1.4826 * mad
        return series.clip(lower_limit, upper_limit)

    def _standardize(self, series: pd.Series) -> pd.Series:
        """Z-Score 标准化"""
        return (series - series.mean()) / series.std()

    def prepare_analysis_data(self, ts_codes: list, factor_name: str):
        """
        准备横截面分析数据 (对齐因子与未来收益)
        """
        all_data = []
        for code in ts_codes:
            # 获取因子数据 (PIT)
            f_df = self.dm.get_factor_payload(code, [factor_name])
            if f_df.empty: continue
            f_df['ann_date'] = pd.to_datetime(f_df['ann_date'])
            
            # 获取价格与未来收益数据
            p_df = self.dm.get_price_payload(code)
            if p_df.empty: continue
            
            # 这里的逻辑是：将公告后的因子值映射到每一个交易日
            # 本策略采用 point-in-time，即 T 日能用到的因子是 max(ann_date <= T)
            merged = pd.merge_asof(
                p_df.sort_values('trade_date'),
                f_df.sort_values('ann_date'),
                left_on='trade_date',
                right_on='ann_date',
                direction='backward'
            )
            all_data.append(merged)
            
        if not all_data: return pd.DataFrame()
        
        full_df = pd.concat(all_data)
        # 清洗：去掉缺失值
        full_df = full_df.dropna(subset=[factor_name, 'next_5d_ret'])
        return full_df

    def calculate_metrics(self, data: pd.DataFrame, factor_name: str):
        """
        计算 IC 分布和分组收益
        """
        # 1. 计算每日 IC (Rank-IC)
        def daily_rank_ic(group):
            if len(group) < 5: return np.nan
            # 预处理横截面因子
            processed_f = self._standardize(self._winsorize_mad(group[factor_name]))
            ic, _ = spearmanr(processed_f, group['next_5d_ret'])
            return ic

        ic_series = data.groupby('trade_date').apply(daily_rank_ic)
        
        # 2. 分组收益 (Quantile Analysis) - 简化为 5 组
        def daily_quantile_returns(group):
            if len(group) < 5: return pd.Series()
            # 预处理
            group[f'{factor_name}_norm'] = self._standardize(self._winsorize_mad(group[factor_name]))
            # 划分 5 组
            try:
                group['quantile'] = pd.qcut(group[f'{factor_name}_norm'], 5, labels=False, duplicates='drop')
                return group.groupby('quantile')['next_5d_ret'].mean()
            except:
                return pd.Series()

        quantile_rets = data.groupby('trade_date').apply(daily_quantile_returns)
        
        return {
            "ic_mean": ic_series.mean(),
            "ic_std": ic_series.std(),
            "ir": ic_series.mean() / ic_series.std() if ic_series.std() != 0 else 0,
            "ic_series": ic_series,
            "quantile_rets": quantile_rets
        }

if __name__ == "__main__":
    analyzer = FactorAnalyzer()
    dm = FactorDataManager()
    
    # 获取测试样本
    stocks = dm.get_all_stocks().head(30)["ts_code"].tolist()
    
    # 确保行情数据已同步 (Phase 2 需要)
    print("正在检查/同步测试行情数据...")
    dm.sync_daily_prices(stocks)
    
    # 财务数据在 Phase 1 已同步部分，此处直接分析
    factor_to_test = "roe" # 净资产收益率
    print(f"正在对因子 [{factor_to_test}] 进行 IC 检测...")
    
    analysis_data = analyzer.prepare_analysis_data(stocks, factor_to_test)
    if not analysis_data.empty:
        results = analyzer.calculate_metrics(analysis_data, factor_to_test)
        print(f"\n====== 因子分析结果 [{factor_to_test}] ======")
        print(f"IC 均值: {results['ic_mean']:.4f}")
        print(f"IR 比率: {results['ir']:.4f}")
        print(f"IC 胜率: {(results['ic_series'] > 0).mean():.2%}")
        
        # 打印各组平均收益量级 (年化简化)
        q_avg = results['quantile_rets'].mean()
        print("\n五分组 5 日平均收益率:")
        print(q_avg)
    else:
        print("未找到有效重合数据，请检查数据同步状态。")
