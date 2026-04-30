import json
from swing_data_fetcher import SwingDataFetcher
from swing_strategy_engine import SwingStrategyEngine

class SwingDecisionOrchestrator:
    """
    波段决策指挥官：串联数据获取与算法引擎
    """
    def __init__(self):
        self.fetcher = SwingDataFetcher()
        self.engine = SwingStrategyEngine()
        
    def generate_all_signals(self) -> dict:
        """为7大ETF生成完整决策信号"""
        results = {}
        
        # 遍历所有配置的资产
        all_assets = list(self.engine.slow_ma_assets.keys()) + \
                     list(self.engine.dual_ma_assets.keys()) + \
                     list(self.engine.trailing_drawdown_assets.keys())
                     
        for asset_id in all_assets:
            print(f"正在拉取并分析: {asset_id} ...")
            # 1. 获取日线数据
            df = self.fetcher.fetch_etf_daily(asset_id, days=120)
            
            # 2. 获取实时溢价率（QDII专享）
            premium = self.fetcher.get_qdii_premium(asset_id)
            
            # 3. 传入引擎计算
            if not df.empty:
                signal = self.engine.analyze_asset(asset_id, df, premium)
                
                # 附加资产名称，方便前端展示
                name = self._get_asset_name(asset_id)
                signal['asset_name'] = name
                
                results[asset_id] = signal
            else:
                results[asset_id] = {"status": "ERROR", "reason": "无法获取数据"}
                
        return results
        
    def _get_asset_name(self, asset_id: str) -> str:
        if asset_id in self.engine.slow_ma_assets:
            return self.engine.slow_ma_assets[asset_id]['name']
        if asset_id in self.engine.dual_ma_assets:
            return self.engine.dual_ma_assets[asset_id]['name']
        if asset_id in self.engine.trailing_drawdown_assets:
            return self.engine.trailing_drawdown_assets[asset_id]['name']
        return asset_id

if __name__ == "__main__":
    orchestrator = SwingDecisionOrchestrator()
    signals = orchestrator.generate_all_signals()
    
    print("\n" + "="*50)
    print(" [Swing Trading Signals] 7 ETF Dashboard ")
    print("="*50)
    
    for asset, data in signals.items():
        status = data.get('status', 'UNKNOWN')
        # 简单颜色映射终端显示
        color_map = {"RED": "[RED]", "YELLOW": "[YEL]", "GREEN": "[GRN]", "ERROR": "[ERR]"}
        icon = color_map.get(status, "[UNK]")
        
        name = data.get('asset_name', asset)
        action = data.get('action', 'N/A')
        buffer_pct = data.get('buffer_pct', 0.0)
        reason = data.get('reason', '')
        
        print(f"{icon} {name.ljust(10)} | 动作: {action.ljust(8)} | 缓冲安全垫: {buffer_pct*100:>5.1f}% | 逻辑: {reason}")
    
    print("\n" + "="*50)
