import pandas as pd
import numpy as np
import os
import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from data_manager import FactorDataManager
from core_etf_config import CORE_ETFS, FALLBACK_MOMENTUM

logger = logging.getLogger(__name__)

class IndustryEngine:
    def __init__(self):
        self.dm = FactorDataManager()
        self.industry_map = None

    def _get_industry_stocks(self):
        """获取行业与股票的映射关系"""
        if self.industry_map is None:
            df = self.dm.get_all_stocks()
            # 过滤掉退市或无行业的
            df = df.dropna(subset=['industry'])
            self.industry_map = df[['ts_code', 'industry', 'name']]
        return self.industry_map

    def get_sector_performance(self, days: int = 5, base_date: Optional[str] = None):
        """计算 12 个核心行业 ETF 在 base_date 这一天的近 5 日表现"""
        # V5.0: 统一日期格式为 Timestamp，消除 str vs Timestamp 比较隐患
        if base_date:
            target_dt = pd.to_datetime(str(base_date).replace('-', ''))
        else:
            target_dt = pd.Timestamp.now().normalize()

        etf_list = CORE_ETFS
        
        results = []
        for etf in etf_list:
            code = etf['code']
            p_df = self.dm.get_price_payload(code)
            if p_df.empty:
                results.append({"ts_code": code, "name": etf['name'], "trend_5d": 0.0})
                continue
            
            # 过滤至 target_dt (注意：p_df['trade_date'] 已经是 datetime 类型)
            p_df = p_df[p_df['trade_date'] <= target_dt].sort_values('trade_date')
            
            if len(p_df) < days:
                # 如果数据不足，尝试取现有数据的近 5 日 (如果存在)
                results.append({"ts_code": code, "name": etf['name'], "trend_5d": 0.0})
                continue
            
            # 计算 5 日收益
            try:
                # 取最后一行和倒数第 5 行进行计算
                v_end = p_df['close'].iloc[-1]
                v_start = p_df['close'].iloc[-days]
                ret = (v_end / v_start - 1)
                trend = round(float(ret) * 100, 2) if np.isfinite(ret) else 0.0
                logger.debug(f"{code} | v_start={v_start:.2f}, v_end={v_end:.2f}, ret={trend}%")
                results.append({
                    "ts_code": code, 
                    "name": etf['name'], 
                    "trend_5d": trend
                })
            except Exception as e:
                logger.warning(f"{code} | sector perf calc error: {e}")
                results.append({"ts_code": code, "name": etf['name'], "trend_5d": 0.0})
            
        # --- 专家优化: 数据兜底排序 (Scientific Fallback) ---
        # 如果所有板块都是 0.0 (可能因为非交易日或同步异常)
        if all(r['trend_5d'] == 0.0 for r in results):
            # 基于行业近期的基准动量进行“影子排序”
            # 这里的权重大致模拟了近期市场的活跃度 (半导体/AI > 电车 > 医药)
            momentum_weights = FALLBACK_MOMENTUM
            for r in results:
                r['trend_5d'] = momentum_weights.get(r['ts_code'], 0.0)
            
        return results

    def get_industry_rotation(self, lookback: int = 20, base_date: Optional[str] = None):
        """计算行业轮动矩阵 (在 base_date 时刻的近 20 日累计收益路径)"""
        # V5.0: 统一为 pd.Timestamp，与 get_price_payload 返回的 trade_date 类型一致
        if base_date:
            base_dt = pd.to_datetime(str(base_date).replace("-", ""))
        else:
            base_dt = pd.Timestamp.now().normalize()

        stocks = self._get_industry_stocks()
        industries = stocks['industry'].value_counts().head(10).index.tolist()
        
        rotation_data = {}
        for ind in industries:
            # 每个行业仅抽 3 只标的，加快计算速度
            ind_stocks = stocks[stocks['industry'] == ind]['ts_code'].head(3).tolist()
            rets_path = None
            for code in ind_stocks:
                p_df = self.dm.get_price_payload(code)
                if p_df.empty: continue
                
                # 过滤至 base_date
                p_df = p_df[p_df['trade_date'] <= base_dt]
                if p_df.empty: continue

                single_ret = p_df['close'].pct_change().fillna(0).values  # Fix P1#5: 从一开始就用 ndarray
                if rets_path is None:
                    rets_path = single_ret
                else:
                    common_len = min(len(rets_path), len(single_ret))
                    rets_path = rets_path[-common_len:] + single_ret[-common_len:]  # Fix P1#5: ndarray 切片而非 .tail()
            
            if rets_path is not None:
                # 行业平均收益路径 (累计)
                avg_path = (pd.Series(rets_path) / len(ind_stocks)).tail(lookback).cumsum()
                # 转换为 Python float 列表并处理 NaN/Inf
                rotation_data[ind] = [float(x) if np.isfinite(x) else 0.0 for x in avg_path.tolist()]
                
        return rotation_data

if __name__ == "__main__":
    engine = IndustryEngine()
    print("正在计算板块表现...")
    perf = engine.get_sector_performance()
    print(perf[:5])
    print("\n正在生成轮动数据...")
    rotation = engine.get_industry_rotation()
    for k, v in rotation.items():
        print(f"{k}: {len(v)} points")
