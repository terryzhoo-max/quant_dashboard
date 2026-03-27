import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
from data_manager import FactorDataManager

def safe_round(val, n):
    """防止 lint 报错的 round 包装器"""
    try:
        return round(float(val), n)
    except:
        return 0.0

class PortfolioEngine:
    def __init__(self, store_path="portfolio_store.json"):
        self.store_path = store_path
        self.dm = FactorDataManager()
        self.holdings = self._load_portfolio()

    def _load_portfolio(self) -> dict:
        """加载持仓数据"""
        default_data = {
            "cash": 1000000.0,
            "positions": {}
        }
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "positions" in data:
                        return data
            except:
                pass
        return default_data

    def _save_portfolio(self):
        """保存持仓数据"""
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(self.holdings, f, indent=4, ensure_ascii=False)

    def add_position(self, ts_code: str, amount: int, price: float, name: str = ""):
        """买入/增加持仓"""
        cost_total = float(amount) * float(price)
        if self.holdings.get("cash", 0) < cost_total:
            return False, "余额不足"
        
        positions = self.holdings.get("positions", {})
        pos = positions.get(ts_code, {"amount": 0, "cost": 0.0, "name": name})
        
        # 计算新的平均成本
        new_amount = int(pos.get("amount", 0)) + amount
        old_total_cost = float(pos.get("amount", 0)) * float(pos.get("cost", 0.0))
        new_cost = (old_total_cost + cost_total) / new_amount if new_amount > 0 else 0.0
        
        positions[ts_code] = {
            "amount": new_amount,
            "cost": safe_round(new_cost, 3),
            "name": name or pos.get("name", "")
        }
        self.holdings["positions"] = positions
        self.holdings["cash"] = float(self.holdings.get("cash", 0)) - cost_total
        self._save_portfolio()
        return True, "买入成功"

    def reduce_position(self, ts_code: str, amount: int, price: float):
        """卖出/减少持仓"""
        positions = self.holdings.get("positions", {})
        if ts_code not in positions:
            return False, "未持有该股票"
        
        pos = positions[ts_code]
        cur_amount = int(pos.get("amount", 0))
        if cur_amount < amount:
            return False, "持仓不足"
            
        pos["amount"] = cur_amount - amount
        self.holdings["cash"] = float(self.holdings.get("cash", 0)) + float(amount) * float(price)
        
        if int(pos["amount"]) <= 0:
            del positions[ts_code]
        else:
            positions[ts_code] = pos
            
        self.holdings["positions"] = positions
        self._save_portfolio()
        return True, "卖出成功"

    def get_valuation(self):
        """获取当前组合估值"""
        total_market_value = 0.0
        details = []
        
        positions = self.holdings.get("positions", {})
        for code, pos in positions.items():
            p_df = self.dm.get_price_payload(code)
            current_price = p_df['close'].iloc[-1] if not p_df.empty else float(pos.get("cost", 0))
            
            amount = int(pos.get("amount", 0))
            cost = float(pos.get("cost", 0))
            
            market_value = amount * current_price
            pnl = market_value - (amount * cost)
            pnl_pct = (pnl / (amount * cost) * 100) if cost > 0 else 0.0
            
            details.append({
                "ts_code": code,
                "name": pos.get("name", "Unknown"),
                "amount": amount,
                "cost": cost,
                "price": safe_round(current_price, 2),
                "market_value": safe_round(market_value, 2),
                "pnl": safe_round(pnl, 2),
                "pnl_pct": safe_round(pnl_pct, 2)
            })
            total_market_value += market_value
            
        return {
            "cash": safe_round(self.holdings.get("cash", 0), 2),
            "market_value": safe_round(total_market_value, 2),
            "total_asset": safe_round(float(self.holdings.get("cash", 0)) + total_market_value, 2),
            "positions": details
        }

    def calculate_risk_metrics(self):
        """计算 MCTR 等风险指标"""
        valuation = self.get_valuation()
        if not valuation["positions"]:
            return {"status": "empty"}
            
        rets_data = {}
        for pos in valuation["positions"]:
            p_df = self.dm.get_price_payload(pos["ts_code"])
            if not p_df.empty:
                rets_data[pos["ts_code"]] = p_df['close'].pct_change().dropna().tail(60)
        
        if len(rets_data) < 1: return {"status": "insufficient_data"}
        
        df_rets = pd.DataFrame(rets_data).fillna(0)
        cov_matrix = df_rets.cov() * 252 
        
        total_val = float(valuation["market_value"])
        if total_val == 0: return {"status": "zero_value"}
        
        weights = np.array([float(pos["market_value"]) / total_val for pos in valuation["positions"]])
        
        port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        if port_vol == 0: port_vol = 0.0001
        
        marginal_risk = np.dot(cov_matrix, weights) / port_vol
        
        risk_details = []
        for i, pos in enumerate(valuation["positions"]):
            risk_details.append({
                "ts_code": pos["ts_code"],
                "name": pos["name"],
                "weight": safe_round(weights[i] * 100, 2),
                "mctr": safe_round(marginal_risk[i], 4),
                "risk_contribution": safe_round(weights[i] * marginal_risk[i] / port_vol * 100, 2)
            })
            
        return {
            "portfolio_vol": safe_round(port_vol, 4),
            "details": risk_details
        }
