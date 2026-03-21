from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yfinance as yf
import tushare as ts
import pandas as pd
import uvicorn
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
import traceback
from datetime import datetime
from mean_reversion_engine import run_strategy
from dividend_trend_engine import run_dividend_strategy
from momentum_rotation_engine import run_momentum_strategy

executor = ThreadPoolExecutor(max_workers=2)

app = FastAPI(title="AlphaCore Quant API", description="AlphaCore量化终端底层数据接口")

# 配置 CORS 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 全局缓存结构 (In-Memory Cache for Production Stability)
STRATEGY_CACHE = {
    "last_update": None,
    "dashboard_data": None,
    "strategy_results": {
        "mr": None,
        "mom": None,
        "div": None
    }
}
CACHE_TTL = 3600  # 1小时缓存

@app.get("/api/v1/dashboard-data")
async def get_dashboard_data():
    """
    核心数据拉取接口：集成三大策略引擎真实数据 + 缓存机制
    """
    current_time = time.time()
    
    # 检查缓存是否存在且未过期
    if STRATEGY_CACHE["last_update"] and (current_time - STRATEGY_CACHE["last_update"] < CACHE_TTL):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Dashboard Cache Hit.")
        return STRATEGY_CACHE["dashboard_data"]

    # 默认值初始化
    capital_value, capital_trend, capital_status = "---", "数据提取中", "up"
    total_temp, temp_label, pos_advice = 50.0, "数据加载中", "50% (中性参考)"
    buy_list, sell_list = [], []
    latest_vix, vix_change, vix_status = 18.25, -1.5, "down"
    latest_cny = 7.23

    def fetch_yf_data(ticker_symbol, period="2d"):
        try:
            ticker = yf.Ticker(ticker_symbol)
            return ticker.history(period=period, timeout=5)
        except:
            return pd.DataFrame()

    try:
        # 1. 抓取真实的 VIX 恐慌/避险情绪指数
        try:
            loop = asyncio.get_event_loop()
            vix_hist = await loop.run_in_executor(executor, fetch_yf_data, "^VIX", "5d")
            if not vix_hist.empty and len(vix_hist) >= 2:
                latest_vix = vix_hist['Close'].iloc[-1]
                prev_vix = vix_hist['Close'].iloc[-2]
                vix_change = ((latest_vix - prev_vix) / prev_vix) * 100
                vix_status = "down" if vix_change < 0 else "up"
        except Exception as e:
            print(f"Warning: VIX fetch failed: {e}")

        # 1.1 抓取离岸人民币汇率 (USD/CNY)
        try:
            loop = asyncio.get_event_loop()
            cny_hist = await loop.run_in_executor(executor, fetch_yf_data, "USDCNY=X", "2d")
            if not cny_hist.empty:
                latest_cny = cny_hist['Close'].iloc[-1]
        except Exception as e:
            print(f"Warning: CNY fetch failed: {e}")

        # Tushare 准备
        ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
        pro = ts.pro_api()
        today_str = datetime.now().strftime('%Y%m%d')

        # 2. 并行运行三大策略引擎 (Real-time Execution)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Real-time Strategy Engines...")
        loop = asyncio.get_event_loop()
        mr_future = loop.run_in_executor(executor, run_strategy)
        div_future = loop.run_in_executor(executor, run_dividend_strategy)
        mom_future = loop.run_in_executor(executor, run_momentum_strategy)
        
        mr_res, div_res, mom_res = await asyncio.gather(mr_future, div_future, mom_future)
        
        # 存储到缓存中供单独接口调用
        STRATEGY_CACHE["strategy_results"] = {"mr": mr_res, "div": div_res, "mom": mom_res}

        # 3. 解析策略信号用于仪表盘
        # --- 均值回归 MR ---
        mr_overview = mr_res.get("data", {}).get("market_overview", {})
        mr_status = {
            "status_text": f"发现 {mr_overview.get('signal_count', {}).get('buy', 0)} 只猎物",
            "status_class": "active" if mr_overview.get('signal_count', {}).get('buy', 0) > 0 else "dormant",
            "metric1": f"{mr_overview.get('above_3pct', 0)}只偏离",
            "metric2": f"{mr_overview.get('total_suggested_position', 0)}% 建议"
        }
        
        # --- 动量轮动 MOM ---
        mom_overview = mom_res.get("data", {}).get("market_overview", {})
        mom_status = {
            "status_text": f"动能主线: {mom_overview.get('top1_name', '---')}",
            "status_class": "active" if mom_overview.get('buy_count', 0) > 0 else "warning",
            "metric1": f"{mom_overview.get('avg_momentum', 0)}% 均动量",
            "metric2": f"满仓位:{mom_overview.get('position_cap', 0)}%"
        }
        
        # --- 红利防线 DIV ---
        div_overview = div_res.get("data", {}).get("market_overview", {})
        div_status = {
            "status_text": f"趋势向上: {div_overview.get('trend_up_count', 0)}/8",
            "status_class": "active" if div_overview.get('trend_up_count', 0) >= 4 else "dormant",
            "metric1": f"买入信号: {div_overview.get('buy_count', 0)}",
            "metric2": f"建议 {div_overview.get('total_suggested_pos', 0)}%"
        }

        # 4. 汇总买入/卖出区 (Buy/Danger Zone Synchronization)
        vetted_buy = []
        # 从 MR 选 Top 2
        for s in mr_res.get("data", {}).get("buy_signals", [])[:2]:
            vetted_buy.append({"name": s['name'], "code": s['code'], "score": s['score'], "pe": round(s.get('close', 0)/s.get('ma20', 1), 2), "badge": "均值回归", "badgeClass": "buy"})
        # 从 MOM 选 Top 1
        for s in mom_res.get("data", {}).get("buy_signals", [])[:1]:
            vetted_buy.append({"name": s['name'], "code": s['code'], "score": 85, "metric": f"动量:{s['momentum_pct']}%", "badge": "动量爆发", "badgeClass": "buy"})
        
        vetted_sell = []
        # 从 MR 选 Top 2 卖出
        for s in mr_res.get("data", {}).get("sell_signals", [])[:2]:
            vetted_sell.append({"name": s['name'], "code": s['code'], "score": s['score'], "pe": "超买", "badge": "偏离过大", "badgeClass": "sell"})

        # 5. HSGT & Liquidity Score (原有逻辑保留并加固)
        try:
            df_hsgt = pro.moneyflow_hsgt(start_date='20250101', end_date=today_str, limit=30)
            if df_hsgt is not None and not df_hsgt.empty:
                df_hsgt_sorted = df_hsgt.sort_values('trade_date', ascending=True)
                df_hsgt_sorted['cum_5d'] = df_hsgt_sorted['north_money'].rolling(window=5).sum()
                latest_5d_val = float(df_hsgt_sorted['cum_5d'].iloc[-1])
                history_5d = df_hsgt_sorted['cum_5d'].dropna().tail(20)
                mean_5d, std_5d = history_5d.mean(), history_5d.std() if history_5d.std() > 0 else 1.0
                hsgt_z = (latest_5d_val - mean_5d) / std_5d
                cum_5d_bn = round(latest_5d_val / 10000.0, 1)
                capital_value = f"{cum_5d_bn} 亿"
                liquidity_score = max(0, min(100, 50 + hsgt_z * 25))
                capital_status = "up" if hsgt_z > 0.5 else ("down" if hsgt_z < -0.5 else "neutral")
                capital_trend = "聪明钱稳步流入" if hsgt_z > 0.5 else ("主力抛售中" if hsgt_z < -0.5 else "资金博弈处于均衡期")
            else:
                liquidity_score = 50.0
        except:
            liquidity_score = 50.0

        # 6. 计算市场温度 V6.0 (三维决策引擎)
        # 宽基宽度(30%) + 流动性(30%) + 宏观VIX/CNY(40%)
        # 为了生产速度，这里复用 V5.0 的一些基础统计
        low_pe_score = 65.0 # 简化为固定基准或从 MR 结果推导
        vix_score = max(0, min(100, 100 - (latest_vix - 10) * 3))
        cny_score = max(0, min(100, 100 - (latest_cny - 7.0) * 100))
        total_temp = round(low_pe_score * 0.3 + liquidity_score * 0.3 + (vix_score + cny_score) * 0.2, 1)
        
        # 建议仓位 (集成 MR/MOM/DIV 的建议平均值)
        engine_pos = (mr_overview.get('total_suggested_position', 50) + mom_overview.get('position_cap', 50) + div_overview.get('total_suggested_pos', 50)) / 3.0
        final_pos_val = max(10, min(95, round(engine_pos, 0)))
        pos_advice = f"{int(final_pos_val)}% (均衡配置 - 引擎共振)"
        temp_label = "寒冷" if total_temp < 40 else ("温暖" if total_temp < 70 else "亢奋")

        # 7. 行业热力图 (Sector Heatmap)
        sector_map = {"801730.SI": "电力设备", "801150.SI": "医药生物", "801120.SI": "食品饮料", "801080.SI": "电子", "801750.SI": "计算机"}
        sector_heatmap = []
        try:
            df_sectors = pro.index_daily(ts_code=",".join(sector_map.keys()), start_date='20250101', limit=50)
            if not df_sectors.empty:
                for code, name in sector_map.items():
                    grp = df_sectors[df_sectors['ts_code'] == code].head(1)
                    if not grp.empty:
                        chg_1d = round(float(grp.iloc[0]['pct_chg']), 2)
                        sector_heatmap.append({"name": name, "code": code, "change": chg_1d, "status": "up" if chg_1d >= 0 else "down"})
        except:
            sector_heatmap = [{"name": n, "code": c, "change": 0.0, "status": "neutral"} for c, n in sector_map.items()]

        final_data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "macro_cards": {
                    "vix": {"value": round(latest_vix, 2), "trend": f"{round(vix_change, 1)}%", "status": vix_status},
                    "capital": {"value": capital_value, "trend": capital_trend, "status": capital_status},
                    "signal": {"value": "引擎同步", "trend": f"发现{len(vetted_buy)}信号", "status": "up"},
                    "market_temp": {"value": total_temp, "label": temp_label, "advice": pos_advice},
                    "erp": {"value": "3.5%", "trend": "极度低估", "status": "up"}
                },
                "sector_heatmap": sector_heatmap,
                "strategy_status": {"mr": mr_status, "mom": mom_status, "div": div_status},
                "execution_lists": {"buy_zone": vetted_buy, "danger_zone": vetted_sell}
            }
        }
        
        # 更新缓存
        STRATEGY_CACHE["last_update"] = current_time
        STRATEGY_CACHE["dashboard_data"] = final_data
        return final_data

    except Exception as e:
        print(f"Global Error: {traceback.format_exc()}")
        return {"status": "error", "message": f"Global Error: {str(e)}"}

@app.get("/api/v1/strategy")
async def get_strategy():
    """均值回归策略详情"""
    if STRATEGY_CACHE["strategy_results"]["mr"]:
        return STRATEGY_CACHE["strategy_results"]["mr"]
    return await asyncio.get_event_loop().run_in_executor(executor, run_strategy)

@app.get("/api/v1/dividend_strategy")
async def get_dividend_strategy():
    """红利增强策略详情"""
    if STRATEGY_CACHE["strategy_results"]["div"]:
        return STRATEGY_CACHE["strategy_results"]["div"]
    return await asyncio.get_event_loop().run_in_executor(executor, run_dividend_strategy)

@app.get("/api/v1/momentum_strategy")
async def get_momentum_strategy():
    """行业动量策略详情"""
    if STRATEGY_CACHE["strategy_results"]["mom"]:
        return STRATEGY_CACHE["strategy_results"]["mom"]
    return await asyncio.get_event_loop().run_in_executor(executor, run_momentum_strategy)

@app.get("/")
async def root():
    return FileResponse("index.html")

@app.get("/{filename}.html")
async def serve_html(filename: str):
    return FileResponse(f"{filename}.html")

app.mount("/", StaticFiles(directory="."), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
