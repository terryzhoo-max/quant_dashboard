"""
AlphaCore Portfolio Engine V2.0 — Institutional Grade
=====================================================
- 单例化引擎，避免请求级重建
- 交易历史独立持久化 (trade_history.json)
- 净值曲线生成 (NAV Series)
- 扩展风险指标: Sharpe / Max Drawdown / Calmar Ratio
- 单票仓位上限 20%
- MCTR 窗口 120 根 K 线
"""

import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
from data_manager import FactorDataManager
from services import db as ac_db

# ─── 全局单例 ───
_engine_instance = None

def get_portfolio_engine():
    """全局单例工厂 — 避免每次请求重建实例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PortfolioEngine()
    return _engine_instance


def safe_round(val, n):
    try:
        return round(float(val), n)
    except Exception:
        return 0.0


class PortfolioEngine:
    """AlphaCore 投资组合引擎 V2.0"""

    # 仓位常量 (从 config.POSITION_CONFIG 统一读取)
    try:
        from config import POSITION_CONFIG as _POS_CFG
        POSITION_LIMIT = _POS_CFG["single_limit"] / 100.0   # 单票仓位上限
    except ImportError:
        POSITION_LIMIT = 0.20
    MCTR_LOOKBACK  = 120           # 风险窗口 120 根 K 线 (约半年)
    RISK_FREE_RATE = 0.02          # 无风险利率 (一年期国债)

    def __init__(self, store_path="portfolio_store.json", history_path="trade_history.json"):
        self.store_path = store_path
        self.history_path = history_path
        self.dm = FactorDataManager()
        self.holdings = self._load_portfolio()
        self.trade_history = self._load_history()

        try:
            stocks_df = self.dm.get_all_stocks()
            self.industry_map = stocks_df.set_index('ts_code')['industry'].to_dict()
        except Exception:
            self.industry_map = {}

    # ──────────────────────────────────────
    #  V4.0: 审计执行器交易阻断
    # ──────────────────────────────────────

    def _is_trade_blocked(self) -> bool:
        """检查审计执行器是否阻断了交易"""
        try:
            from audit_enforcer import is_trade_blocked
            blocked, _ = is_trade_blocked()
            return blocked
        except ImportError:
            return False

    def _get_trade_block_info(self):
        """获取阻断详情"""
        try:
            from audit_enforcer import is_trade_blocked
            return is_trade_blocked()
        except ImportError:
            return False, ""

    # ──────────────────────────────────────
    #  I/O 持久化
    # ──────────────────────────────────────

    def _load_portfolio(self) -> dict:
        default = {"cash": 1000000.0, "positions": {}}
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "positions" in data:
                        return data
            except Exception:
                pass
        return default

    def _save_portfolio(self):
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(self.holdings, f, indent=4, ensure_ascii=False)

    def _load_history(self) -> list:
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_history(self):
        with open(self.history_path, 'w', encoding='utf-8') as f:
            json.dump(self.trade_history, f, indent=4, ensure_ascii=False)

    def _record_trade(self, action: str, ts_code: str, name: str, amount: int, price: float, success: bool, msg: str):
        """追加交易记录 (SQLite 主存储 + JSON 备份)"""
        trade = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "ts_code": ts_code,
            "name": name,
            "amount": amount,
            "price": price,
            "total": safe_round(amount * price, 2),
            "success": success,
            "message": msg
        }
        # SQLite 主写入
        try:
            ac_db.add_trade(trade)
        except Exception:
            pass  # SQLite 失败不阻塞交易
        # JSON 备份写入 (双写期)
        self.trade_history.append(trade)
        if len(self.trade_history) > 200:
            self.trade_history = self.trade_history[-200:]
        self._save_history()

    # ──────────────────────────────────────
    #  交易执行
    # ──────────────────────────────────────

    def _check_position_limit(self, ts_code: str, add_value: float) -> bool:
        """检查单票仓位是否超过 20% 上限"""
        val = self.get_valuation()
        total_asset = val["total_asset"]
        if total_asset <= 0:
            return True

        # 现有市值 + 本次买入
        existing_mv = 0.0
        for pos in val["positions"]:
            if pos["ts_code"] == ts_code:
                existing_mv = pos["market_value"]
                break

        projected_weight = (existing_mv + add_value) / (total_asset + add_value)
        return projected_weight <= self.POSITION_LIMIT

    def add_position(self, ts_code: str, amount: int, price: float, name: str = ""):
        """买入/增加持仓 (含 20% 仓位上限校验 + V4.0 审计阻断校验)"""
        cost_total = float(amount) * float(price)

        # V4.0: 审计执行器交易阻断检查
        if self._is_trade_blocked():
            blocked, reason = self._get_trade_block_info()
            self._record_trade("buy", ts_code, name, amount, price, False, f"审计执行器阻断: {reason}")
            return False, f"⛔ 交易被审计执行器阻断: {reason}"

        # 余额校验
        if self.holdings.get("cash", 0) < cost_total:
            self._record_trade("buy", ts_code, name, amount, price, False, "余额不足")
            return False, "余额不足"

        # 单票仓位上限校验
        if not self._check_position_limit(ts_code, cost_total):
            self._record_trade("buy", ts_code, name, amount, price, False, f"单票仓位超过{int(self.POSITION_LIMIT*100)}%上限")
            return False, f"单票仓位将超过 {int(self.POSITION_LIMIT*100)}% 上限，交易被拒绝"

        positions = self.holdings.get("positions", {})
        pos = positions.get(ts_code, {"amount": 0, "cost": 0.0, "name": name})

        old_amount = int(pos.get("amount", 0))
        old_cost = float(pos.get("cost", 0.0))
        new_amount = old_amount + amount
        new_cost = (old_amount * old_cost + cost_total) / new_amount if new_amount > 0 else 0.0

        # 保留导入时的 broker 数据 (不被交易覆盖)
        updated_pos = {
            "amount": new_amount,
            "cost": safe_round(new_cost, 3),
            "name": name or pos.get("name", "")
        }
        for broker_key in ("broker_price", "broker_market_value", "broker_pnl", "broker_pnl_pct", "import_date"):
            if pos.get(broker_key) is not None:
                updated_pos[broker_key] = pos[broker_key]
        positions[ts_code] = updated_pos
        self.holdings["positions"] = positions
        self.holdings["cash"] = float(self.holdings.get("cash", 0)) - cost_total
        self._save_portfolio()

        self._record_trade("buy", ts_code, name, amount, price, True, "买入成功")
        return True, "买入成功"

    def reduce_position(self, ts_code: str, amount: int, price: float):
        """卖出/减少持仓"""
        positions = self.holdings.get("positions", {})
        if ts_code not in positions:
            self._record_trade("sell", ts_code, ts_code, amount, price, False, "未持有该股票")
            return False, "未持有该股票"

        pos = positions[ts_code]
        name = pos.get("name", ts_code)
        cur_amount = int(pos.get("amount", 0))
        if cur_amount < amount:
            self._record_trade("sell", ts_code, name, amount, price, False, "持仓不足")
            return False, "持仓不足"

        pos["amount"] = cur_amount - amount
        self.holdings["cash"] = float(self.holdings.get("cash", 0)) + float(amount) * float(price)

        if int(pos["amount"]) <= 0:
            del positions[ts_code]
        else:
            positions[ts_code] = pos

        self.holdings["positions"] = positions
        self._save_portfolio()

        self._record_trade("sell", ts_code, name, amount, price, True, "卖出成功")
        return True, "卖出成功"

    # ──────────────────────────────────────
    #  估值与行业推断
    # ──────────────────────────────────────

    @staticmethod
    def _infer_industry(code: str, name: str) -> str:
        """智能推断 ETF 和 港股 的行业归属"""
        name_lower = name.lower()
        if "半导体" in name_lower or "芯片" in name_lower:
            return "半导体"
        if "电网" in name_lower or "电力" in name_lower or "绿电" in name_lower:
            return "电力设备"
        if "卫星" in name_lower or "军工" in name_lower or "航天" in name_lower:
            return "国防军工"
        if "黄金" in name_lower or "贵金属" in name_lower:
            return "贵金属"
        if "机器" in name_lower or "机床" in name_lower:
            return "机械设备"
        if "红利" in name_lower or "高股息" in name_lower or "低波" in name_lower:
            if "恒生" in name_lower or "港股" in name_lower:
                return "港股-红利"
            return "红利/低波"
        if "科创50" in name_lower or "科创板" in name_lower:
            return "宽基-科创板"
        if "中证500" in name_lower or "500etf" in name_lower:
            return "宽基-中证500"
        if "沪深300" in name_lower or "300etf" in name_lower:
            return "宽基-沪深300"
        if "创业板" in name_lower:
            return "宽基-创业板"
        if "恒生科技" in name_lower or "中概" in name_lower:
            return "港股-科技"
        if "恒生" in name_lower or "港股" in name_lower:
            return "港股-宽基"
        if "新材" in name_lower or "化工" in name_lower:
            return "基础化工"
        if "医药" in name_lower or "医疗" in name_lower:
            return "医药生物"
        if "证券" in name_lower or "券商" in name_lower:
            return "证券"
        if "白酒" in name_lower or "食品" in name_lower or "饮料" in name_lower:
            return "食品饮料"
        
        if code.endswith(".HK"):
            return "港股"
            
        if "etf" in name_lower:
            return "主题ETF"
            
        return "其他"

    def _pick_price(self, code: str, pos: dict):
        """
        智能价格选取 (当日优先 + 过期降级):

          导入当日 (import_date == today):
            1) broker_price (券商导入的「当前价」) — 最权威
            2) Tushare 收盘价 — 回退
            3) cost — 最终兜底

          隔日 (import_date != today 或无 import_date):
            1) Tushare 收盘价 — 优先
            2) broker_price — 回退 (ETF/港股 Tushare 可能次日才更新)
            3) cost — 最终兜底

        Returns: (price: float, source: str)
        """
        broker_price = float(pos.get("broker_price", 0))
        cost = float(pos.get("cost", 0))
        import_date = pos.get("import_date", "")
        today_str = datetime.now().strftime("%Y-%m-%d")
        is_same_day = (import_date == today_str)

        # ── 导入当日: broker_price 绝对优先 ──
        if is_same_day and broker_price > 0:
            return broker_price, "broker"

        # ── 隔日 (或当日无 broker): Tushare 优先 ──
        try:
            p_df = self.dm.get_price_payload(code)
            if not p_df.empty:
                tushare_price = float(p_df['close'].iloc[-1])
                if tushare_price > 0:
                    return tushare_price, "tushare"
        except Exception:
            pass

        # Tushare 取不到 → 回退券商报价 (ETF/港股次日补数据前的过渡)
        if broker_price > 0:
            return broker_price, "broker"

        # 最终兜底: 成本价
        return cost if cost > 0 else 1.0, "cost"

    def get_valuation(self):
        """获取当前组合估值 (含仓位权重 + 价格来源标识)
        
        当日导入: 市值和浮动盈亏直接使用券商原始数据
        隔日:     根据 Tushare/broker 价格重新计算
        """
        total_market_value = 0.0
        details = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        positions = self.holdings.get("positions", {})
        for code, pos in positions.items():
            current_price, price_source = self._pick_price(code, pos)

            amount = int(pos.get("amount", 0))
            cost = float(pos.get("cost", 0))
            import_date = pos.get("import_date", "")
            is_same_day = (import_date == today_str)

            # ── 当日导入: 市值和盈亏以券商数据为准 ──
            if is_same_day and pos.get("broker_market_value", 0) > 0:
                market_value = float(pos["broker_market_value"])
                pnl = float(pos.get("broker_pnl", 0))
                pnl_pct = float(pos.get("broker_pnl_pct", 0))
            else:
                # ── 隔日: 根据当前价格重新计算 ──
                market_value = amount * current_price
                pnl = market_value - (amount * cost)
                pnl_pct = (pnl / (amount * cost) * 100) if cost > 0 else 0.0

            name = pos.get("name", "Unknown")
            industry = self.industry_map.get(code, "其他")
            if industry == "其他" or not industry or str(industry) == "nan":
                industry = self._infer_industry(code, name)

            details.append({
                "ts_code": code,
                "name": name,
                "industry": industry,
                "amount": amount,
                "cost": cost,
                "price": safe_round(current_price, 2),
                "price_source": price_source,
                "market_value": safe_round(market_value, 2),
                "pnl": safe_round(pnl, 2),
                "pnl_pct": safe_round(pnl_pct, 2)
            })
            total_market_value += market_value

        # 计算仓位权重 + 汇总盈亏
        # V2.1: 当日导入时使用 broker 文件头的总资产 (最权威)
        broker_total_asset_val = float(self.holdings.get("broker_total_asset", 0))
        broker_import_date = self.holdings.get("import_date", "")
        is_import_day = (broker_import_date == today_str)

        if is_import_day and broker_total_asset_val > 0:
            total_asset = broker_total_asset_val
        else:
            total_asset = float(self.holdings.get("cash", 0)) + total_market_value

        total_pnl = sum(d["pnl"] for d in details)

        # V2.1: 当日导入时使用 broker 文件头的盈亏 (已含所有持仓, 包括冻结标的)
        broker_total_pnl_val = float(self.holdings.get("broker_total_pnl", 0))
        if is_import_day and broker_total_pnl_val != 0:
            total_pnl = broker_total_pnl_val

        # 成本基: 市值 - 盈亏 (确保和 pnl 数据源一致, 无论是券商还是自算)
        total_cost_basis = total_market_value - total_pnl
        total_pnl_pct = (total_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0

        # V2.1: 当日导入时, 市值也使用 broker 文件头的参考市值
        broker_ref_mv = float(self.holdings.get("broker_ref_market_value", 0))
        display_market_value = broker_ref_mv if (is_import_day and broker_ref_mv > 0) else total_market_value

        for d in details:
            d["weight"] = safe_round(d["market_value"] / total_asset * 100, 2) if total_asset > 0 else 0.0

        cash_weight = safe_round(float(self.holdings.get("cash", 0)) / total_asset * 100, 2) if total_asset > 0 else 100.0

        return {
            "cash": safe_round(self.holdings.get("cash", 0), 2),
            "cash_weight": cash_weight,
            "market_value": safe_round(display_market_value, 2),
            "total_asset": safe_round(total_asset, 2),
            "total_pnl": safe_round(total_pnl, 2),
            "total_pnl_pct": safe_round(total_pnl_pct, 2),
            "positions": details,
            "position_count": len(details)
        }

    # ──────────────────────────────────────
    #  风险指标
    # ──────────────────────────────────────

    def calculate_risk_metrics(self):
        """计算 MCTR + Sharpe + Max Drawdown + Calmar"""
        valuation = self.get_valuation()
        if not valuation["positions"]:
            return {"status": "empty"}

        rets_data = {}
        for pos in valuation["positions"]:
            p_df = self.dm.get_price_payload(pos["ts_code"])
            if not p_df.empty:
                rets_data[pos["ts_code"]] = p_df['close'].pct_change().dropna().tail(self.MCTR_LOOKBACK)

        if len(rets_data) < 1:
            return {"status": "insufficient_data"}

        df_rets = pd.DataFrame(rets_data)
        # Ensure all holding codes are columns in df_rets in the same order
        ordered_codes = [pos["ts_code"] for pos in valuation["positions"]]
        for code in ordered_codes:
            if code not in df_rets.columns:
                df_rets[code] = 0.0
        df_rets = df_rets[ordered_codes].fillna(0)
        cov_matrix = df_rets.cov() * 252

        total_val = float(valuation["market_value"])
        if total_val == 0:
            return {"status": "zero_value"}

        weights = np.array([float(pos["market_value"]) / total_val for pos in valuation["positions"]])

        # ── 组合波动率 ──
        port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        if port_vol == 0:
            port_vol = 0.0001

        # ── MCTR ──
        marginal_risk = np.dot(cov_matrix, weights) / port_vol

        # ── 组合日收益率序列 ──
        port_daily_rets = df_rets.values @ weights
        ann_return = float(np.mean(port_daily_rets) * 252)

        # ── Sharpe Ratio ──
        sharpe = (ann_return - self.RISK_FREE_RATE) / port_vol if port_vol > 0 else 0.0

        # ── Max Drawdown ──
        cumulative = np.cumprod(1 + port_daily_rets)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

        # ── Calmar Ratio ──
        calmar = ann_return / abs(max_drawdown) if max_drawdown != 0 else 0.0

        # ── 个股风险明细 + 行业敞口 ──
        risk_details = []
        sector_weights = {}
        for i, pos in enumerate(valuation["positions"]):
            ind = pos.get("industry", "其他")
            w = weights[i] * 100
            sector_weights[ind] = sector_weights.get(ind, 0.0) + w

            risk_details.append({
                "ts_code": pos["ts_code"],
                "name": pos["name"],
                "industry": ind,
                "weight": safe_round(w, 2),
                "mctr": safe_round(marginal_risk[i], 4),
                "risk_contribution": safe_round(weights[i] * marginal_risk[i] / port_vol * 100, 2)
            })

        industry_exposure = [{"name": k, "value": safe_round(v, 2)} for k, v in sector_weights.items()]

        return {
            "portfolio_vol": safe_round(port_vol, 4),
            "annualized_return": safe_round(ann_return * 100, 2),
            "sharpe_ratio": safe_round(sharpe, 2),
            "max_drawdown": safe_round(max_drawdown * 100, 2),
            "calmar_ratio": safe_round(calmar, 2),
            "details": risk_details,
            "industry_exposure": sorted(industry_exposure, key=lambda x: x["value"], reverse=True)
        }

    # ──────────────────────────────────────
    #  V21.1: 相关性矩阵 + MCTR 风险贡献
    # ──────────────────────────────────────

    def get_correlation_data(self) -> dict:
        """
        计算持仓间皮尔逊相关系数矩阵 + MCTR 风险贡献分解。
        复用 calculate_risk_metrics 的收益率拉取逻辑。

        Returns:
            {
                "status": "success",
                "codes": [...],
                "names": [...],
                "correlation_matrix": [[float]],  # N×N
                "mctr_details": [{code, name, weight, mctr, risk_contribution, industry}],
                "portfolio_vol": float,
                "data_days": int,
                "high_corr_pairs": [{a, b, corr, level}],
            }
        """
        valuation = self.get_valuation()
        positions = valuation.get("positions", [])
        if len(positions) < 2:
            return {
                "status": "insufficient",
                "message": "至少需要 2 只持仓才能计算相关性矩阵",
                "position_count": len(positions),
            }

        # ── 拉取日收益率 ──
        rets_data = {}
        for pos in positions:
            try:
                p_df = self.dm.get_price_payload(pos["ts_code"])
                if not p_df.empty:
                    rets_data[pos["ts_code"]] = p_df['close'].pct_change().dropna().tail(self.MCTR_LOOKBACK)
            except Exception:
                pass

        if len(rets_data) < 2:
            return {"status": "insufficient_data", "message": "可用收益率数据不足 2 只"}

        # ── 构建收益率 DataFrame ──
        ordered_codes = [p["ts_code"] for p in positions]
        ordered_names = [p["name"] for p in positions]
        df_rets = pd.DataFrame(rets_data)
        for code in ordered_codes:
            if code not in df_rets.columns:
                df_rets[code] = 0.0
        df_rets = df_rets[ordered_codes].fillna(0)
        data_days = len(df_rets)

        # ── 皮尔逊相关系数矩阵 ──
        corr_matrix = df_rets.corr().fillna(0)  # 零方差列产生 NaN → 填 0
        corr_list = []
        for i in range(len(ordered_codes)):
            row = []
            for j in range(len(ordered_codes)):
                v = corr_matrix.iloc[i, j]
                # 防御 NaN/Inf (JSON 不支持)
                if np.isnan(v) or np.isinf(v):
                    v = 0.0
                row.append(safe_round(v, 3))
            corr_list.append(row)

        # ── 高相关对检测 (|r| > 0.7, 排除对角线) ──
        high_corr_pairs = []
        for i in range(len(ordered_codes)):
            for j in range(i + 1, len(ordered_codes)):
                r = corr_matrix.iloc[i, j]
                abs_r = abs(r)
                if abs_r > 0.7:
                    level = "extreme" if abs_r > 0.9 else "high"
                    high_corr_pairs.append({
                        "a": ordered_names[i],
                        "b": ordered_names[j],
                        "a_code": ordered_codes[i],
                        "b_code": ordered_codes[j],
                        "corr": safe_round(r, 3),
                        "level": level,
                    })
        high_corr_pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)

        # ── MCTR 风险贡献 (复用 cov → MCTR 公式) ──
        cov_matrix = df_rets.cov().fillna(0) * 252
        total_val = float(valuation.get("market_value", 0))
        if total_val == 0:
            return {"status": "zero_value", "message": "组合市值为零"}

        weights = np.array([float(p["market_value"]) / total_val for p in positions])
        port_var = np.dot(weights.T, np.dot(cov_matrix, weights))
        if np.isnan(port_var) or port_var <= 0:
            port_var = 0.0001
        port_vol = np.sqrt(port_var)
        marginal_risk = np.dot(cov_matrix, weights) / port_vol
        # 清理 NaN/Inf
        marginal_risk = np.nan_to_num(marginal_risk, nan=0.0, posinf=0.0, neginf=0.0)

        mctr_details = []
        for i, pos in enumerate(positions):
            rc = weights[i] * marginal_risk[i] / port_vol * 100
            rc = 0.0 if (np.isnan(rc) or np.isinf(rc)) else rc
            mctr_details.append({
                "code": pos["ts_code"],
                "name": pos["name"],
                "industry": pos.get("industry", "其他"),
                "weight": safe_round(weights[i] * 100, 2),
                "mctr": safe_round(marginal_risk[i], 4),
                "risk_contribution": safe_round(rc, 2),
            })
        mctr_details.sort(key=lambda x: x["risk_contribution"], reverse=True)

        return {
            "status": "success",
            "codes": ordered_codes,
            "names": ordered_names,
            "correlation_matrix": corr_list,
            "mctr_details": mctr_details,
            "portfolio_vol": safe_round(port_vol, 4),
            "data_days": data_days,
            "high_corr_pairs": high_corr_pairs[:10],
            "position_count": len(positions),
        }

    # ──────────────────────────────────────
    #  净值曲线
    # ──────────────────────────────────────


    def get_nav_history(self, days: int = 120):
        """生成组合近 N 日的模拟净值曲线 (基于持仓加权日收益)"""
        valuation = self.get_valuation()
        if not valuation["positions"]:
            return {"status": "empty", "dates": [], "nav": [], "benchmark": []}

        total_val = float(valuation["market_value"])
        if total_val == 0:
            return {"status": "zero_value", "dates": [], "nav": [], "benchmark": []}

        # 获取各持仓日线收益
        all_rets = {}
        for pos in valuation["positions"]:
            p_df = self.dm.get_price_payload(pos["ts_code"])
            if not p_df.empty:
                rets = p_df[['trade_date', 'close']].copy()
                rets['ret'] = rets['close'].pct_change()
                rets = rets.dropna().tail(days)
                all_rets[pos["ts_code"]] = rets.set_index('trade_date')['ret']

        if not all_rets:
            return {"status": "no_data", "dates": [], "nav": [], "benchmark": []}

        df_rets = pd.DataFrame(all_rets).fillna(0)
        weights = np.array([float(pos["market_value"]) / total_val for pos in valuation["positions"]])

        port_rets = df_rets.values @ weights
        nav = np.cumprod(1 + port_rets)

        # 基准: 沪深300
        bench_nav = []
        try:
            bench_df = self.dm.get_price_payload("000300.SH")
            if not bench_df.empty:
                bench_rets = bench_df['close'].pct_change().dropna().tail(days)
                bench_nav = np.cumprod(1 + bench_rets.values).tolist()
        except Exception:
            pass

        dates = df_rets.index.tolist()
        # 将日期转为字符串
        date_strs = []
        for d in dates:
            if hasattr(d, 'strftime'):
                date_strs.append(d.strftime('%Y-%m-%d'))
            else:
                date_strs.append(str(d))

        return {
            "status": "ok",
            "dates": date_strs,
            "nav": [safe_round(v, 4) for v in nav.tolist()],
            "benchmark": [safe_round(v, 4) for v in bench_nav[:len(nav)]],
            "benchmark_name": "沪深300"
        }

    # ──────────────────────────────────────
    #  交易历史
    # ──────────────────────────────────────

    def get_trade_history(self, limit: int = 30):
        """返回最近 N 条交易记录 (SQLite 优先, JSON 降级)"""
        try:
            rows = ac_db.get_trades(limit=limit)
            if rows:
                return rows
        except Exception:
            pass
        # JSON fallback
        records = self.trade_history[-limit:] if len(self.trade_history) > limit else self.trade_history
        return list(reversed(records))  # 最新的在前

    # ──────────────────────────────────────
    #  清零组合
    # ──────────────────────────────────────

    def reset_portfolio(self) -> dict:
        """清零组合: 归零持仓 + 现金，交易记录保留"""
        old_count = len(self.holdings.get("positions", {}))
        old_cash = self.holdings.get("cash", 0)

        self.holdings = {"cash": 0.0, "positions": {}}
        self._save_portfolio()

        self._record_trade(
            action="reset",
            ts_code="SYSTEM",
            name=f"清零 {old_count} 只持仓",
            amount=old_count,
            price=0,
            success=True,
            msg=f"组合清零: 原 {old_count} 只持仓 + 现金 ¥{old_cash:,.2f} → 归零"
        )

        return {
            "success": True,
            "cleared_positions": old_count,
            "cleared_cash": round(old_cash, 2)
        }

    # ──────────────────────────────────────
    #  同步行情数据 (Tushare 增量拉取)
    # ──────────────────────────────────────

    def sync_prices(self) -> dict:
        """
        强制同步当前持仓的最新日线行情数据 (Tushare → data_lake)
        用途: 导入当天是 broker_price 优先，次日点「同步数据」让 Tushare 接管

        Returns:
            {
                success: bool,
                synced: int,         # 成功同步的标的数
                failed: int,         # 失败的标的数
                total: int,          # 总持仓数
                freshness: dict,     # 数据新鲜度
                details: [...]       # 每只标的的同步结果
            }
        """
        positions = self.holdings.get("positions", {})
        if not positions:
            return {"success": True, "synced": 0, "failed": 0, "total": 0,
                    "freshness": {}, "details": [], "message": "无持仓可同步"}

        ts_codes = list(positions.keys())
        details = []
        synced_count = 0
        failed_count = 0

        import time as _time
        t0 = _time.time()

        for i, code in enumerate(ts_codes):
            name = positions[code].get("name", code)
            try:
                self.dm.sync_daily_prices([code])
                synced_count += 1
                details.append({"ts_code": code, "name": name, "status": "ok"})
            except Exception as e:
                failed_count += 1
                details.append({"ts_code": code, "name": name, "status": "error", "error": str(e)})
            # Tushare API 频率控制: 避免触发限流
            if i < len(ts_codes) - 1:
                _time.sleep(0.25)

        elapsed = round(_time.time() - t0, 1)

        # 同步后检查新鲜度
        freshness = self.dm.check_data_freshness(ts_codes[:5])

        return {
            "success": True,
            "synced": synced_count,
            "failed": failed_count,
            "total": len(ts_codes),
            "elapsed_sec": elapsed,
            "freshness": freshness,
            "details": details,
            "message": f"同步完成: {synced_count}/{len(ts_codes)} 只标的 ({elapsed}s)"
        }

    # ──────────────────────────────────────
    #  TXT 持仓导入 (券商导出文件)
    # ──────────────────────────────────────

    @staticmethod
    def _auto_suffix(code: str) -> str:
        """
        自动补全证券代码市场后缀
        规则:
          6xxxxx → .SH (上证主板)
          000/001/002/003 → .SZ (深证主板/中小板)
          300/301 → .SZ (创业板)
          159xxx → .SZ (深交所 ETF)
          510/511/512/513/515/518/560/562/563/588 → .SH (上交所 ETF/LOF)
          688/689 → .SH (科创板)
          0xxxx (5位,非6位) → .HK (港股通)
        """
        code = code.strip()
        if '.' in code:
            return code  # 已含后缀

        # 港股通: 5位纯数字且首位为0或非6开头的5位
        if len(code) == 5:
            return code + '.HK'

        # 6位代码规则
        if len(code) == 6:
            prefix2 = code[:2]
            prefix3 = code[:3]

            # 深交所 ETF
            if prefix3 == '159':
                return code + '.SZ'

            # 上交所 ETF/LOF
            if prefix3 in ('510', '511', '512', '513', '515', '516', '518',
                           '560', '561', '562', '563', '588'):
                return code + '.SH'

            # 深交所股票
            if prefix3 in ('000', '001', '002', '003', '300', '301'):
                return code + '.SZ'

            # 上交所股票
            if code[0] == '6':
                return code + '.SH'

            # 科创板
            if prefix3 in ('688', '689'):
                return code + '.SH'

        # 兜底: 无法识别的返回原样 + .SZ
        return code + '.SZ'

    def import_from_txt(self, file_content: str) -> dict:
        """
        解析券商导出的 '资金股份查询.txt'，一键覆盖式同步持仓

        文件格式 (GBK 编码, 空格/Tab 分隔):
          Line 1: 人民币: 余额:xxx  可用:xxx  参考市值:xxx  资产:xxx  盈亏:xxx
          Line 2: ---------- (分隔线)
          Line 3: (空行)
          Line 4: 列头 (证券代码 证券名称 证券数量 ... 买入均价 ...)
          Line 5+: 数据行

        关键列索引 (0-based, 按空格 split):
          [0] 证券代码  [1] 证券名称  [2] 证券数量  [5] 买入均价  [9] 当前价

        Returns:
            {
                success: bool,
                imported: int,         # 成功导入的持仓数
                cash: float,           # 可用资金
                total_asset: float,    # 总资产
                positions: [...],      # 导入的持仓明细
                errors: [...]          # 解析错误列表
            }
        """
        import re

        result = {
            "success": False,
            "imported": 0,
            "cash": 0.0,
            "total_asset": 0.0,
            "positions": [],
            "errors": []
        }

        lines = file_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        lines = [l for l in lines if l.strip()]  # 去空行

        if len(lines) < 3:
            result["errors"].append("文件内容不足，至少需要3行 (汇总行 + 列头 + 数据)")
            return result

        # ── Step 1: 解析第一行汇总行 ──
        # V2.1: 提取「余额」(含冻结) 而非「可用」，因为冻结资金仍属账户资产
        header_line = lines[0]
        balance_match = re.search(r'余额[:\s]*([0-9,.]+)', header_line)
        asset_match = re.search(r'资产[:\s]*([0-9,.]+)', header_line)
        ref_mv_match = re.search(r'参考市值[:\s]*([0-9,.]+)', header_line)
        pnl_match = re.search(r'盈亏[:\s]*(-?[0-9,.]+)', header_line)

        if balance_match:
            try:
                result["cash"] = float(balance_match.group(1).replace(',', ''))
            except ValueError:
                result["errors"].append(f"无法解析余额: {balance_match.group(1)}")

        if asset_match:
            try:
                result["total_asset"] = float(asset_match.group(1).replace(',', ''))
            except ValueError:
                pass

        broker_ref_mv = 0.0
        if ref_mv_match:
            try:
                broker_ref_mv = float(ref_mv_match.group(1).replace(',', ''))
            except ValueError:
                pass

        broker_total_pnl = 0.0
        if pnl_match:
            try:
                broker_total_pnl = float(pnl_match.group(1).replace(',', ''))
            except ValueError:
                pass

        # ── Step 2: 定位列头行 (包含 "证券代码" 的行) ──
        header_idx = -1
        for i, line in enumerate(lines):
            if '证券代码' in line:
                header_idx = i
                break

        if header_idx < 0:
            # 退化模式: 假设第二个非分隔行是列头
            for i, line in enumerate(lines):
                if '---' not in line and i > 0:
                    header_idx = i
                    break

        if header_idx < 0:
            result["errors"].append("无法找到列头行 (需包含 '证券代码')")
            return result

        # ── Step 3: 解析列头，动态映射列索引 ──
        header_parts = lines[header_idx].split()
        col_map = {}
        target_cols = {
            '证券代码': 'code',
            '证券名称': 'name',
            '证券数量': 'amount',
            '库存数量': 'amount_alt',
            '买入均价': 'cost',
            '参考成本价': 'cost_alt',
            '当前价': 'price',
            '最新市值': 'market_value',
            '参考浮动盈亏': 'pnl',
            '盈亏比例': 'pnl_pct',
            '个股仓位': 'weight',
        }

        for idx, col_name in enumerate(header_parts):
            for key, field in target_cols.items():
                if key in col_name:
                    col_map[field] = idx
                    break

        # 校验必要列
        if 'code' not in col_map:
            result["errors"].append(f"列头中未找到 '证券代码' 列: {header_parts}")
            return result

        # ── Step 4: 解析数据行 ──
        new_positions = {}
        data_lines = lines[header_idx + 1:]

        for line_num, line in enumerate(data_lines, start=header_idx + 2):
            # 跳过分隔线和汇总行
            if '---' in line or '合计' in line or line.strip() == '':
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            try:
                # 证券代码
                raw_code = parts[col_map.get('code', 0)].strip()
                if not raw_code or not any(c.isdigit() for c in raw_code):
                    continue

                ts_code = self._auto_suffix(raw_code)

                # 证券名称
                name = parts[col_map.get('name', 1)].strip() if col_map.get('name', 1) < len(parts) else ''

                # 数量: V2.1 优先使用「库存数量」(含冻结/在途), 退化到「证券数量」
                # 修复: 002916 等 "证券数量=0 但 库存数量=200" 的冻结持仓
                amount_idx = col_map.get('amount_alt', col_map.get('amount', 2))
                amount_str = parts[amount_idx] if amount_idx < len(parts) else '0'
                amount = int(float(amount_str.replace(',', '')))
                if amount <= 0:
                    # 再尝试另一个数量列
                    alt_idx = col_map.get('amount', col_map.get('amount_alt', 2))
                    if alt_idx != amount_idx and alt_idx < len(parts):
                        amount = int(float(parts[alt_idx].replace(',', '')))
                    if amount <= 0:
                        continue

                # 成本价 (优先 买入均价，退化到 参考成本价)
                cost_idx = col_map.get('cost', col_map.get('cost_alt', 5))
                cost_str = parts[cost_idx] if cost_idx < len(parts) else '0'
                cost = abs(float(cost_str.replace(',', '')))

                # 当前价
                price_idx = col_map.get('price', 9)
                price_str = parts[price_idx] if price_idx < len(parts) else '0'
                price = float(price_str.replace(',', ''))

                # 最新市值 (券商原始数据)
                broker_mv = 0.0
                if 'market_value' in col_map:
                    mv_idx = col_map['market_value']
                    if mv_idx < len(parts):
                        try:
                            broker_mv = float(parts[mv_idx].replace(',', ''))
                        except ValueError:
                            pass

                # 参考浮动盈亏 (券商原始数据)
                broker_pnl = 0.0
                if 'pnl' in col_map:
                    pnl_idx = col_map['pnl']
                    if pnl_idx < len(parts):
                        try:
                            broker_pnl = float(parts[pnl_idx].replace(',', ''))
                        except ValueError:
                            pass

                # 盈亏比例 (券商原始数据, 百分比)
                broker_pnl_pct = 0.0
                if 'pnl_pct' in col_map:
                    pp_idx = col_map['pnl_pct']
                    if pp_idx < len(parts):
                        try:
                            raw_pct = parts[pp_idx].replace(',', '').replace('%', '')
                            broker_pnl_pct = float(raw_pct)
                        except ValueError:
                            pass

                # 负成本处理 (新股/融券可能出现负值，用当前价替代)
                if cost <= 0:
                    cost = price if price > 0 else 1.0

                new_positions[ts_code] = {
                    "amount": amount,
                    "cost": safe_round(cost, 3),
                    "name": name,
                    "broker_price": safe_round(price, 3) if price > 0 else 0.0,
                    "broker_market_value": safe_round(broker_mv, 2) if broker_mv > 0 else 0.0,
                    "broker_pnl": safe_round(broker_pnl, 2),
                    "broker_pnl_pct": safe_round(broker_pnl_pct, 2),
                    "import_date": datetime.now().strftime("%Y-%m-%d")
                }

                result["positions"].append({
                    "ts_code": ts_code,
                    "raw_code": raw_code,
                    "name": name,
                    "amount": amount,
                    "cost": safe_round(cost, 3),
                    "price": safe_round(price, 2)
                })

            except (ValueError, IndexError) as e:
                result["errors"].append(f"行 {line_num} 解析失败: {str(e)} | 原文: {line.strip()[:80]}")
                continue

        if not new_positions:
            result["errors"].append("未解析到有效持仓数据")
            return result

        # ── Step 5: 覆盖写入 portfolio_store.json ──
        # V2.1: 同时存储 broker 文件头的参考市值/总资产/盈亏，供 get_valuation() 当日直接引用
        self.holdings = {
            "cash": result["cash"],
            "positions": new_positions,
            "broker_ref_market_value": broker_ref_mv,
            "broker_total_asset": result["total_asset"],
            "broker_total_pnl": broker_total_pnl,
            "import_date": datetime.now().strftime("%Y-%m-%d")
        }
        self._save_portfolio()

        # ── Step 6: 记录导入历史 ──
        self._record_trade(
            action="import",
            ts_code="SYSTEM",
            name=f"TXT导入 {len(new_positions)} 只持仓",
            amount=len(new_positions),
            price=0,
            success=True,
            msg=f"从券商TXT文件覆盖导入 {len(new_positions)} 只持仓，可用资金 ¥{result['cash']:,.2f}"
        )

        result["success"] = True
        result["imported"] = len(new_positions)
        return result
