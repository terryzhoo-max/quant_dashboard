import pandas as pd
import numpy as np
from typing import Dict, Any, List

class SwingStrategyEngine:
    """
    7大ETF生产级波段止盈算法引擎
    涵盖三大股性聚类策略及QDII溢价防守
    """
    
    def __init__(self):
        # 聚类一：稳态底仓锚（标普500、沪深300）- 单线迟钝防守
        self.slow_ma_assets = {
            'SP500': {'ma_period': 40, 'name': '标普500ETF'},
            'CSI300': {'ma_period': 20, 'name': '沪深300ETF'}
        }
        
        # 聚类二：高景气动量（纳指、日经、中证500）- 双线退坡制
        self.dual_ma_assets = {
            'NASDAQ': {'fast_ma': 10, 'slow_ma': 20, 'name': '纳指100ETF'},
            'NIKKEI': {'fast_ma': 10, 'slow_ma': 20, 'name': '日经225ETF'},
            'CSI500': {'fast_ma': 10, 'slow_ma': 20, 'name': '中证500ETF'}
        }
        
        # 聚类三：高敏渣男（科创50、恒生科技）- 最高收盘价回撤
        self.trailing_drawdown_assets = {
            'STAR50': {'drawdown_limit': 0.10, 'name': '科创50ETF'},
            'HSTECH': {'drawdown_limit': 0.12, 'name': '恒生科技ETF'}
        }

        # QDII 溢价率红线
        self.qdii_premium_threshold = 0.08  # 8% 强平红线
        self.qdii_assets = ['SP500', 'NASDAQ', 'NIKKEI']

    def check_qdii_premium(self, asset_id: str, current_premium: float) -> Dict[str, Any]:
        """QDII溢价率强平拦截器"""
        if asset_id in self.qdii_assets and current_premium >= self.qdii_premium_threshold:
            return {
                "status": "RED",
                "action": "强制清仓",
                "reason": f"溢价率 {current_premium*100:.1f}% 达到极度泡沫区(>8%)，无视技术面直接止盈避险",
                "buffer_pct": 0.0
            }
        return None

    def calculate_slow_ma_signal(self, df: pd.DataFrame, asset_id: str) -> Dict[str, Any]:
        """稳态长牛：单线迟钝防守"""
        period = self.slow_ma_assets[asset_id]['ma_period']
        if len(df) < period:
            return {"status": "UNKNOWN", "reason": "数据不足"}
            
        close = df['close'].iloc[-1]
        ma_val = df['close'].rolling(window=period).mean().iloc[-1]
        
        # 跌破幅度缓冲计算 (负数表示已经跌破)
        buffer_pct = (close - ma_val) / ma_val
        
        status = "GREEN"
        action = "持有"
        if buffer_pct < 0:
            status = "RED"
            action = "清仓"
            
        return {
            "status": status,
            "action": action,
            "reason": f"收盘价与 {period}日均线 防守逻辑",
            "buffer_pct": buffer_pct,
            "metrics": {f"MA{period}": ma_val, "Close": close}
        }

    def calculate_dual_ma_signal(self, df: pd.DataFrame, asset_id: str) -> Dict[str, Any]:
        """高景气动量：双线退坡制"""
        fast_period = self.dual_ma_assets[asset_id]['fast_ma']
        slow_period = self.dual_ma_assets[asset_id]['slow_ma']
        
        if len(df) < slow_period:
            return {"status": "UNKNOWN", "reason": "数据不足"}
            
        close = df['close'].iloc[-1]
        fast_ma = df['close'].rolling(window=fast_period).mean().iloc[-1]
        slow_ma = df['close'].rolling(window=slow_period).mean().iloc[-1]
        
        buffer_fast_pct = (close - fast_ma) / fast_ma
        buffer_slow_pct = (close - slow_ma) / slow_ma
        
        status = "GREEN"
        action = "持有全仓"
        
        if buffer_slow_pct < 0:
            status = "RED"
            action = "清仓"
        elif buffer_fast_pct < 0:
            status = "YELLOW"
            action = "减仓50%"
            
        return {
            "status": status,
            "action": action,
            "reason": f"10日/20日双线退坡逻辑",
            "buffer_pct": buffer_fast_pct if status == "GREEN" else buffer_slow_pct,
            "metrics": {f"MA{fast_period}": fast_ma, f"MA{slow_period}": slow_ma, "Close": close}
        }

    def calculate_trailing_drawdown_signal(self, df: pd.DataFrame, asset_id: str) -> Dict[str, Any]:
        """高敏极客：最高收盘价回撤法"""
        drawdown_limit = self.trailing_drawdown_assets[asset_id]['drawdown_limit']
        
        if len(df) == 0:
            return {"status": "UNKNOWN", "reason": "数据不足"}
            
        # 注意：在真实生产中，应该从“本轮波段买入点”开始计算最高收盘价。
        # 这里为了简化和保守，取过去60个交易日的最高收盘价作为近期波段高点。
        period = min(60, len(df))
        recent_df = df.tail(period)
        
        highest_close = recent_df['close'].max()
        current_close = recent_df['close'].iloc[-1]
        
        current_drawdown = (highest_close - current_close) / highest_close
        
        # 安全垫缓冲距离：还能跌多少才触及红线
        buffer_pct = drawdown_limit - current_drawdown
        
        status = "GREEN"
        action = "持有"
        
        if current_drawdown >= drawdown_limit:
            status = "RED"
            action = "清仓"
        elif buffer_pct < 0.03: # 距离红线不到 3% 时黄灯警告
            status = "YELLOW"
            action = "高度警报，逼近回撤红线"
            
        return {
            "status": status,
            "action": action,
            "reason": f"最高收盘价 {drawdown_limit*100}% 回撤防守逻辑",
            "buffer_pct": buffer_pct,
            "metrics": {"Highest_Close": highest_close, "Close": current_close, "Drawdown": current_drawdown}
        }

    def analyze_asset(self, asset_id: str, df: pd.DataFrame, current_premium: float = 0.0) -> Dict[str, Any]:
        """主入口：分析单只资产并返回决策信号"""
        
        # 1. 优先检查溢价率强平机制 (QDII专用)
        override = self.check_qdii_premium(asset_id, current_premium)
        if override:
            return override
            
        # 2. 根据资产聚类执行对应的科学算法
        if asset_id in self.slow_ma_assets:
            return self.calculate_slow_ma_signal(df, asset_id)
        elif asset_id in self.dual_ma_assets:
            return self.calculate_dual_ma_signal(df, asset_id)
        elif asset_id in self.trailing_drawdown_assets:
            return self.calculate_trailing_drawdown_signal(df, asset_id)
        else:
            return {"status": "UNKNOWN", "reason": "未知的资产类别"}

# 测试桩
if __name__ == "__main__":
    # 构造假数据测试
    engine = SwingStrategyEngine()
    dates = pd.date_range(start='1/1/2026', periods=100)
    # 科创50假数据: 一路涨到 1.5, 然后跌到 1.3
    mock_closes = np.linspace(1.0, 1.5, 80).tolist() + np.linspace(1.5, 1.3, 20).tolist()
    df = pd.DataFrame({'close': mock_closes}, index=dates)
    
    print("--- 算法逻辑连通性测试 ---")
    print("科创50 (高敏极客):", engine.analyze_asset('STAR50', df))
    print("标普500 (QDII溢价熔断测试):", engine.analyze_asset('SP500', df, current_premium=0.09))
    print("中证500 (高景气动量):", engine.analyze_asset('CSI500', df))
