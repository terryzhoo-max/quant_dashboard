"""
Dashboard Module: 行业热力图 (Sector Heatmap)
==============================================
V4.7: 12只核心ETF并行拉取 + RPS排名 + 策略信号交叉标注。
"""

import asyncio
import tushare as ts
import pandas as pd
from core_etf_config import CORE_ETFS, CORE_ETF_NAME_MAP, FALLBACK_MOMENTUM


async def compute_sector_heatmap(executor, mr_res, mom_res):
    """
    计算行业热力图。
    返回: sector_heatmap list
    """
    sector_map = CORE_ETF_NAME_MAP
    sector_heatmap = []

    try:
        loop = asyncio.get_event_loop()

        def fetch_etf_history(code):
            try:
                df = ts.pro_bar(ts_code=code, asset='FD', start_date='20250101', adj='qfq')
                if df is not None and not df.empty:
                    return df.sort_values('trade_date', ascending=True)
                return pd.DataFrame()
            except Exception as e:
                print(f"Fetch Error {code}: {e}")
                return pd.DataFrame()

        # 并行加速
        tasks = [loop.run_in_executor(executor, fetch_etf_history, code) for code in sector_map.keys()]
        results = await asyncio.gather(*tasks)

        raw_data = {}
        for i, (code, name) in enumerate(sector_map.items()):
            df = results[i]
            if not df.empty and len(df) >= 20:
                raw_data[code] = {"name": name, "df": df}

        # 计算指标
        comparison_list = []
        for code, info in raw_data.items():
            df = info["df"]
            p_now = float(df['close'].iloc[-1])
            p_5d = float(df['close'].iloc[-5])
            p_20d = float(df['close'].iloc[-20])

            chg_1d = float(df['pct_chg'].iloc[-1])
            trend_5d = (p_now / p_5d - 1) * 100
            ret_20d = (p_now / p_20d - 1) * 100

            comparison_list.append({
                "code": code,
                "name": info["name"],
                "change": round(chg_1d, 2),
                "trend_5d": round(trend_5d, 2),
                "ret_20d": ret_20d,
                "status": "up" if chg_1d >= 0 else "down"
            })

        # 计算 RPS (基于 20D 收益率的横向排名)
        comparison_list.sort(key=lambda x: x['ret_20d'])
        for i, item in enumerate(comparison_list):
            item["rps"] = int(((i + 1) / len(comparison_list)) * 100)

        # 最终按 5D Trend 降序
        comparison_list.sort(key=lambda x: x['trend_5d'], reverse=True)

        # 交叉标注策略信号
        _mr_sigs = {s.get('ts_code', ''): s.get('signal', '') for s in mr_res.get("data", {}).get("signals", [])}
        _mom_sigs = {s.get('ts_code', ''): s.get('signal', '') for s in mom_res.get("data", {}).get("signals", [])}
        for _item in comparison_list:
            _c = _item["code"]
            _item["mr_signal"] = _mr_sigs.get(_c, "")
            _item["mom_signal"] = _mom_sigs.get(_c, "")
        sector_heatmap = comparison_list

    except Exception as e:
        print(f"Heatmap V4.0 Logic Error: {e}")

    # 兜底逻辑
    if not sector_heatmap:
        sector_heatmap = [
            {"name": e["name"], "code": e["code"],
             "change": 0, "trend_5d": FALLBACK_MOMENTUM.get(e["code"], 0),
             "rps": int((i + 1) / len(CORE_ETFS) * 100),
             "status": "up" if FALLBACK_MOMENTUM.get(e["code"], 0) > 0 else "down"}
            for i, e in enumerate(CORE_ETFS)
        ]

    return sector_heatmap
