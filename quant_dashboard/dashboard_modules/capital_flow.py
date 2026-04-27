"""
Dashboard Module: HSGT 跨境资金流 Z-Score 计算
===============================================
A+H 跨境流量共振引擎 — 计算北向/南向资金 5D 累计 Z-Score。

字段说明 (Tushare moneyflow_hsgt):
  north_money: 北向当日资金净买入 (万元) — 直接可用
  south_money: 南向历史累计净买入 (亿元) — 需 diff() 得到每日净买入

⚠️ 所有字段返回类型为 object(字符串), 必须 pd.to_numeric 转换。
"""

import os
import json
import time
from datetime import datetime, timedelta

CACHE_FILE = os.path.join("data_lake", "capital_flow_cache.json")


def compute_capital_flow(pro, today_str):
    """
    计算 HSGT 资金流数据。
    返回: (capital_a, capital_h, liquidity_score, total_money_z, z_s)
    """
    import pandas as pd

    total_money_z = 0.0
    z_s = 0.0
    try:
        _hsgt_start = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
        df_hsgt = pro.moneyflow_hsgt(start_date=_hsgt_start, end_date=today_str, limit=30)
        if df_hsgt is not None and not df_hsgt.empty:
            df_hsgt_sorted = df_hsgt.sort_values('trade_date', ascending=True).reset_index(drop=True)

            # ── 类型转换 (Tushare返回字符串) ──
            df_hsgt_sorted['north_money'] = pd.to_numeric(df_hsgt_sorted['north_money'], errors='coerce')
            df_hsgt_sorted['south_money'] = pd.to_numeric(df_hsgt_sorted['south_money'], errors='coerce')
            df_hsgt_sorted = df_hsgt_sorted.dropna(subset=['north_money', 'south_money'])

            # ══════════════════════════════════════
            # A股 (北向资金)
            # north_money = 当日净买入(万元), 直接 rolling 即可
            # ══════════════════════════════════════
            df_hsgt_sorted['cum_5d_n'] = df_hsgt_sorted['north_money'].rolling(window=5).sum()
            latest_5d_n = float(df_hsgt_sorted['cum_5d_n'].iloc[-1])
            hist_5d_n = df_hsgt_sorted['cum_5d_n'].dropna().tail(20)
            mean_n = hist_5d_n.mean()
            std_n = hist_5d_n.std() if hist_5d_n.std() > 0 else 1.0
            z_n = (latest_5d_n - mean_n) / std_n

            # ══════════════════════════════════════
            # 港股 (南向资金) — 关键修复
            # south_money = 历史累计值(亿元), 必须先 diff() 得到每日净买入
            # ══════════════════════════════════════
            df_hsgt_sorted['south_daily'] = df_hsgt_sorted['south_money'].diff()
            df_hsgt_sorted['cum_5d_s'] = df_hsgt_sorted['south_daily'].rolling(window=5).sum()
            # 取有效行
            valid_s = df_hsgt_sorted['cum_5d_s'].dropna()
            if len(valid_s) > 0:
                latest_5d_s = float(valid_s.iloc[-1])
                hist_5d_s = valid_s.tail(20)
                mean_s = hist_5d_s.mean()
                std_s = hist_5d_s.std() if hist_5d_s.std() > 0 else 1.0
                z_s = (latest_5d_s - mean_s) / std_s
            else:
                latest_5d_s = 0.0
                z_s = 0.0

            total_money_z = z_n + z_s

            capital_a = {
                "value": f"A: {round(latest_5d_n/10000.0, 1)} 亿",
                "trend": "北向稳步流入" if z_n > 0.5 else ("北向抛投中" if z_n < -0.5 else "北向博弈均衡"),
                "status": "up" if z_n > 0.5 else ("down" if z_n < -0.5 else "neutral"),
                "z_score": round(z_n, 2),
                "raw_5d": round(latest_5d_n / 10000.0, 2),
            }
            capital_h = {
                # south_daily 单位已是亿元, 无需 /10000
                "value": f"H: {round(latest_5d_s, 1)} 亿",
                "trend": "南向抢筹中" if z_s > 0.5 else ("南向撤退中" if z_s < -0.5 else "南向博弈均衡"),
                "status": "up" if z_s > 0.5 else ("down" if z_s < -0.5 else "neutral"),
                "z_score": round(z_s, 2),
                "raw_5d": round(latest_5d_s, 2),
            }
            # V8.2: 跨境共振综合判定
            _both_up = z_n > 0.5 and z_s > 0.5
            _both_down = z_n < -0.5 and z_s < -0.5
            _diverge = (z_n > 0.5 and z_s < -0.5) or (z_n < -0.5 and z_s > 0.5)
            capital_a["resonance"] = "双多共振" if _both_up else ("双空共振" if _both_down else ("A/H分歧" if _diverge else "观望中性"))
            capital_a["resonance_status"] = "bull" if _both_up else ("bear" if _both_down else ("diverge" if _diverge else "neutral"))
            capital_a["z_composite"] = round(total_money_z, 2)
            liquidity_score = max(0, min(100, 50 + total_money_z * 12))

            # ── 持久化缓存 (供降级使用) ──
            try:
                cache = {"capital_a": capital_a, "capital_h": capital_h,
                         "liquidity_score": liquidity_score, "total_money_z": total_money_z,
                         "z_s": z_s, "ts": time.time()}
                os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False)
            except Exception:
                pass

        else:
            capital_a = {"value": "A: --", "trend": "数据缺失", "status": "neutral"}
            capital_h = {"value": "H: --", "trend": "数据缺失", "status": "neutral"}
            liquidity_score = 50.0
    except Exception as e:
        print(f"HSGT Logic Error: {e}")
        # ── 降级: 尝试读取磁盘缓存 ──
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                capital_a = cache.get("capital_a", {"value": "A: 缓存", "trend": "降级", "status": "neutral"})
                capital_h = cache.get("capital_h", {"value": "H: 缓存", "trend": "降级", "status": "neutral"})
                liquidity_score = cache.get("liquidity_score", 50.0)
                total_money_z = cache.get("total_money_z", 0.0)
                z_s = cache.get("z_s", 0.0)
                print(f"[CapFlow] 降级到磁盘缓存")
                return capital_a, capital_h, liquidity_score, total_money_z, z_s
            except Exception:
                pass
        capital_a = {"value": "A: ERR", "trend": "异常", "status": "down"}
        capital_h = {"value": "H: ERR", "trend": "异常", "status": "down"}
        liquidity_score = 50.0

    return capital_a, capital_h, liquidity_score, total_money_z, z_s

