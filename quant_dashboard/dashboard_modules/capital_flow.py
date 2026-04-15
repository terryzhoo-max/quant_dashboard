"""
Dashboard Module: HSGT 跨境资金流 Z-Score 计算
===============================================
A+H 跨境流量共振引擎 — 计算北向/南向资金 5D 累计 Z-Score。
"""

from datetime import datetime, timedelta


def compute_capital_flow(pro, today_str):
    """
    计算 HSGT 资金流数据。
    返回: (capital_a, capital_h, liquidity_score, total_money_z, z_s)
    """
    total_money_z = 0.0
    z_s = 0.0
    try:
        _hsgt_start = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
        df_hsgt = pro.moneyflow_hsgt(start_date=_hsgt_start, end_date=today_str, limit=30)
        if df_hsgt is not None and not df_hsgt.empty:
            df_hsgt_sorted = df_hsgt.sort_values('trade_date', ascending=True)

            # A股 (北向资金)
            df_hsgt_sorted['cum_5d_n'] = df_hsgt_sorted['north_money'].rolling(window=5).sum()
            latest_5d_n = float(df_hsgt_sorted['cum_5d_n'].iloc[-1])
            hist_5d_n = df_hsgt_sorted['cum_5d_n'].dropna().tail(20)
            mean_n, std_n = hist_5d_n.mean(), hist_5d_n.std() if hist_5d_n.std() > 0 else 1.0
            z_n = (latest_5d_n - mean_n) / std_n

            # 港股 (南向资金)
            df_hsgt_sorted['cum_5d_s'] = df_hsgt_sorted['south_money'].rolling(window=5).sum()
            latest_5d_s = float(df_hsgt_sorted['cum_5d_s'].iloc[-1])
            hist_5d_s = df_hsgt_sorted['cum_5d_s'].dropna().tail(20)
            mean_s, std_s = hist_5d_s.mean(), hist_5d_s.std() if hist_5d_s.std() > 0 else 1.0
            z_s = (latest_5d_s - mean_s) / std_s

            total_money_z = z_n + z_s

            capital_a = {
                "value": f"A: {round(latest_5d_n/10000.0, 1)} 亿",
                "trend": "北向稳步流入" if z_n > 0.5 else ("北向抛投中" if z_n < -0.5 else "北向博弈均衡"),
                "status": "up" if z_n > 0.5 else ("down" if z_n < -0.5 else "neutral"),
                "z_score": round(z_n, 2),
                "raw_5d": round(latest_5d_n / 10000.0, 2),
            }
            capital_h = {
                "value": f"H: {round(latest_5d_s/10000.0, 1)} 亿",
                "trend": "南向抢筹中" if z_s > 0.5 else ("南向撤退中" if z_s < -0.5 else "南向博弈均衡"),
                "status": "up" if z_s > 0.5 else ("down" if z_s < -0.5 else "neutral"),
                "z_score": round(z_s, 2),
                "raw_5d": round(latest_5d_s / 10000.0, 2),
            }
            # V8.2: 跨境共振综合判定
            _both_up = z_n > 0.5 and z_s > 0.5
            _both_down = z_n < -0.5 and z_s < -0.5
            _diverge = (z_n > 0.5 and z_s < -0.5) or (z_n < -0.5 and z_s > 0.5)
            capital_a["resonance"] = "双多共振" if _both_up else ("双空共振" if _both_down else ("A/H分歧" if _diverge else "观望中性"))
            capital_a["resonance_status"] = "bull" if _both_up else ("bear" if _both_down else ("diverge" if _diverge else "neutral"))
            capital_a["z_composite"] = round(total_money_z, 2)
            liquidity_score = max(0, min(100, 50 + total_money_z * 12))
        else:
            capital_a = {"value": "A: --", "trend": "数据缺失", "status": "neutral"}
            capital_h = {"value": "H: --", "trend": "数据缺失", "status": "neutral"}
            liquidity_score = 50.0
    except Exception as e:
        print(f"HSGT Logic Error: {e}")
        capital_a = {"value": "A: ERR", "trend": "异常", "status": "down"}
        capital_h = {"value": "H: ERR", "trend": "异常", "status": "down"}
        liquidity_score = 50.0

    return capital_a, capital_h, liquidity_score, total_money_z, z_s
