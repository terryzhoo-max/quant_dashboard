from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import tushare as ts
import uvicorn
from datetime import datetime

app = FastAPI(title="AlphaCore Quant API", description="AlphaCore量化终端底层数据接口")

# 配置 CORS 跨域，允许本地前端 HTML 网页直接调用 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段允许所有源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/dashboard-data")
async def get_dashboard_data():
    """
    核心数据拉取接口：
    1. 实时获取真实市场的 VIX (恐慌指数) 数据作为大盘风险偏好指标
    2. 融合投研模型的预估趋势数据
    """
    try:
        # 1. 抓取真实的 VIX 恐慌/避险情绪指数
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="5d")
        latest_vix = vix_hist['Close'].iloc[-1]
        prev_vix = vix_hist['Close'].iloc[-2]
        
        # 计算日度涨跌幅
        vix_change = ((latest_vix - prev_vix) / prev_vix) * 100
        vix_status = "up" if vix_change > 0 else "down"

        # 获取 Tushare A股数据作为量化估值池 (演示：拉取沪深300部分股票的当日估值指标)
        ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
        pro = ts.pro_api()
        
        # 实际开发中应该查当天交易日，这里为演示安全，我们拿过去某个稳定交易日的截面数据或最新数据
        # 使用 daily_basic 获取 PE, PB, 等估值指标
        try:
            df_basic = pro.daily_basic(ts_code='', trade_date='', limit=100)
            
            # 简单模拟：筛选出 PE 较低的作为“冰点优选池”
            df_buy = df_basic[(df_basic['pe'] > 0) & (df_basic['pe'] < 15)].head(2)
            # 筛选出 PE 畸高或换手率极高(拥挤度大)的作为“预警池”
            df_sell = df_basic[(df_basic['pe'] > 100) | (df_basic['turnover_rate'] > 20)].head(2)

            buy_list = []
            for _, row in df_buy.iterrows():
                buy_list.append({
                    "name": "高价值标的", # 真实应用需联表获取股票中文名
                    "code": row['ts_code'],
                    "pe": round(row['pe'], 1),
                    "badge": "右侧信号",
                    "badgeClass": "buy"
                })

            sell_list = []
            for _, row in df_sell.iterrows():
                sell_list.append({
                    "name": "高风险标的",
                    "code": row['ts_code'],
                    "pe": round(row['pe'], 1) if row['pe'] else "亏损",
                    "badge": "减持规避",
                    "badgeClass": "sell"
                })
        except Exception as e:
            # 如果 Tushare 未获权限或积分不足，下降为兜底数据
            buy_list = [
                {"name": "量化冰点标的A", "code": "600XXX.SH", "pe": 12.5, "badge": "右侧信号", "badgeClass": "buy"},
                {"name": "量化冰点标的B", "code": "000XXX.SZ", "pe": 14.1, "badge": "左侧建仓", "badgeClass": "wait"}
            ]
            sell_list = [
                {"name": "极端拥挤标的A", "code": "300XXX.SZ", "pe": 150.2, "badge": "减持规避", "badgeClass": "sell"},
                {"name": "高位退潮标的B", "code": "002XXX.SZ", "pe": "估值陷阱", "badge": "盈利下修", "badgeClass": "sell"}
            ]

        # 2. 返回符合前端 JSON 结构的融合数据
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "vix": {
                    "value": round(latest_vix, 2),
                    "change": round(vix_change, 2),
                    "status": vix_status
                },
                "capitalFlow": {
                    "value": -124.5,
                    "change": -1.5,
                    "status": "down"
                },
                "dividendYield": {
                    "value": 4.2,
                    "change": 0.3,
                    "status": "up"
                },
                "trendChart": {
                    "labels": ['2023Q4', '2024Q2', '2024Q4', '2025Q2', '2025Q4', '2026Q2(E)'],
                    "aiInfrastructure": [12, 19, 28, 45, 62, 85],
                    "traditional": [40, 36, 30, 24, 18, 14]
                },
                "radarChart": {
                    "labels": ['盈利动量', '资产质量', '估值倍数(倒数)', '成长性', '交易拥挤度(倒数)', '宏观贝塔'],
                    "alphaModel": [92, 85, 68, 95, 45, 88],
                    "betaModel": [60, 85, 45, 35, 80, 55]
                },
                "stockPools": {
                    "buy": buy_list,
                    "sell": sell_list
                }
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"获取数据源失败: {str(e)}"}

if __name__ == "__main__":
    print("AlphaCore Backend is running!")
    print("访问 http://127.0.0.1:8000/docs 可以查看 API 自动化文档集")
    # 启动 Uvicorn ASGI 服务器
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
