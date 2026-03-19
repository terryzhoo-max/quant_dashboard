"""
AlphaCore · 均值回归策略引擎 V2.0
数据源：Tushare（5000积分用户 — 按trade_date批量获取）
"""

import pandas as pd
import numpy as np
import tushare as ts
from datetime import datetime, timedelta
import traceback
import time

# ====== Tushare 初始化 ======
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ====== 标的池定义（35只ETF） ======
ETF_POOL = [
    # 宽基指数
    {"code": "510500.SH", "name": "中证500ETF",          "max_pos": 15, "category": "宽基指数"},
    {"code": "512100.SH", "name": "中证1000ETF",         "max_pos": 15, "category": "宽基指数"},
    {"code": "510300.SH", "name": "沪深300ETF华泰",      "max_pos": 15, "category": "宽基指数"},
    {"code": "159915.SZ", "name": "创业板ETF易方达",      "max_pos": 10, "category": "宽基指数"},
    {"code": "159949.SZ", "name": "创业板50ETF华安",      "max_pos": 10, "category": "宽基指数"},
    {"code": "588000.SH", "name": "科创50ETF(易方达)",     "max_pos": 10, "category": "宽基指数"},
    {"code": "159781.SZ", "name": "科创创业ETF",          "max_pos": 8,  "category": "宽基指数"},
    
    # 科技/AI/芯片
    {"code": "512480.SH", "name": "半导体ETF",            "max_pos": 8,  "category": "科技AI芯片"},
    {"code": "588200.SH", "name": "科创芯片ETF",          "max_pos": 7,  "category": "科技AI芯片"},
    {"code": "159995.SZ", "name": "芯片ETF",              "max_pos": 7,  "category": "科技AI芯片"},
    {"code": "159516.SZ", "name": "半导体设备ETF",        "max_pos": 6,  "category": "科技AI芯片"},
    {"code": "588220.SH", "name": "科创100ETF鹏华",       "max_pos": 8,  "category": "科技AI芯片"},
    {"code": "515000.SH", "name": "科技ETF",              "max_pos": 6,  "category": "科技AI芯片"},
    {"code": "515070.SH", "name": "人工智能AIETF",        "max_pos": 6,  "category": "科技AI芯片"},
    {"code": "159819.SZ", "name": "人工智能ETF易方达",    "max_pos": 6,  "category": "科技AI芯片"},
    {"code": "515880.SH", "name": "通信ETF国泰",          "max_pos": 6,  "category": "科技AI芯片"},
    {"code": "562500.SH", "name": "机器人ETF",            "max_pos": 5,  "category": "科技AI芯片"},

    # 行业/新能源
    {"code": "512400.SH", "name": "有色金属ETF",          "max_pos": 6,  "category": "行业新能源"},
    {"code": "516160.SH", "name": "新能源ETF",            "max_pos": 7,  "category": "行业新能源"},
    {"code": "515790.SH", "name": "光伏ETF",              "max_pos": 7,  "category": "行业新能源"},
    {"code": "562550.SH", "name": "绿电ETF",              "max_pos": 5,  "category": "行业新能源"},
    {"code": "159870.SZ", "name": "化工ETF",              "max_pos": 5,  "category": "行业新能源"},
    {"code": "512560.SH", "name": "军工ETF",              "max_pos": 7,  "category": "行业新能源"},
    {"code": "159218.SZ", "name": "卫星ETF招商",          "max_pos": 5,  "category": "行业新能源"},
    {"code": "159326.SZ", "name": "电网设备ETF",          "max_pos": 5,  "category": "行业新能源"},
    {"code": "159869.SZ", "name": "游戏ETF",              "max_pos": 5,  "category": "行业新能源"},
    {"code": "159851.SZ", "name": "金融科技ETF",          "max_pos": 5,  "category": "行业新能源"},
    
    # 跨境/港股
    {"code": "159941.SZ", "name": "纳指ETF",              "max_pos": 8,  "category": "跨境港股"},
    {"code": "513500.SH", "name": "标普500ETF博时",       "max_pos": 8,  "category": "跨境港股"},
    {"code": "515100.SH", "name": "红利低波100ETF",       "max_pos": 5,  "category": "跨境港股"},
    {"code": "159545.SZ", "name": "恒生红利低波ETF",      "max_pos": 5,  "category": "跨境港股"},
    {"code": "513130.SH", "name": "恒生科技ETF",          "max_pos": 5,  "category": "跨境港股"},
    {"code": "513970.SH", "name": "恒生消费ETF景顺",      "max_pos": 5,  "category": "跨境港股"},
    {"code": "513090.SH", "name": "香港证券ETF易方达",    "max_pos": 5,  "category": "跨境港股"},
    {"code": "513120.SH", "name": "港股创新药ETF",        "max_pos": 5,  "category": "跨境港股"},
]

ETF_CODE_SET = {e["code"] for e in ETF_POOL}


def fetch_all_etf_data_batch(days: int = 120) -> dict:
    """
    5000积分用户正确姿势：按trade_date批量获取，不循环ts_code
    每次调用获取当天ALL基金数据，然后本地过滤目标ETF
    """
    print(f"[策略引擎] 开始获取{days}个交易日数据...")

    # 1. 获取交易日历，找到最近 days 个交易日
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=int(days * 2.0))).strftime("%Y%m%d")

    try:
        cal = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date)
        trade_dates = cal[cal['is_open'] == 1]['cal_date'].sort_values().tolist()
        # 只取最近 days 个交易日
        trade_dates = trade_dates[-days:]
        print(f"[策略引擎] 获取到{len(trade_dates)}个交易日：{trade_dates[0]} ~ {trade_dates[-1]}")
    except Exception as e:
        print(f"[策略引擎] 获取日历失败: {e}")
        return {}

    # 2. 按日期批量获取 — 一次API拿到当天所有ETF数据
    all_records = {code: [] for code in ETF_CODE_SET}

    for i, date in enumerate(trade_dates):
        try:
            df = pro.fund_daily(trade_date=date)
            if df is not None and not df.empty:
                # 过滤目标ETF
                target = df[df['ts_code'].isin(ETF_CODE_SET)]
                for _, row in target.iterrows():
                    all_records[row['ts_code']].append({
                        'date': pd.to_datetime(row['trade_date']),
                        'open': row['open'],
                        'high': row['high'],
                        'low': row['low'],
                        'close': row['close'],
                        'volume': row['vol'],
                    })
        except Exception as e:
            print(f"[策略引擎] 日期 {date} 获取失败: {e}")

        if (i + 1) % 40 == 0:
            print(f"[策略引擎] 已处理 {i+1}/{len(trade_dates)} 个交易日")

    # 3. 组装为 DataFrame
    result = {}
    for code, records in all_records.items():
        if records:
            df = pd.DataFrame(records).sort_values('date').reset_index(drop=True)
            result[code] = df

    print(f"[策略引擎] 数据获取完成，共{len(result)}只ETF有数据")
    return result


def calculate_indicators(df: pd.DataFrame) -> dict:
    """计算全部技术指标"""
    if len(df) < 20: # 稍微放宽一点
        return None

    close = df["close"]
    volume = df["volume"]

    ma20 = close.rolling(20).mean()
    boll_std = close.rolling(20).std()
    boll_upper = ma20 + 2 * boll_std
    boll_lower = ma20 - 2 * boll_std

    delta = close.diff(1)
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, 0.001)
    rsi = 100 - (100 / (1 + rs))

    bias = (close - ma20) / ma20 * 100
    deviation = ((close - ma20) / ma20).abs() * 100

    vol_ma5 = volume.rolling(5).mean()
    volume_spike = volume >= vol_ma5 * 1.5

    idx = len(df) - 1
    latest_close = float(close.iloc[idx])
    latest_ma20 = float(ma20.iloc[idx]) if pd.notna(ma20.iloc[idx]) else latest_close
    latest_upper = float(boll_upper.iloc[idx]) if pd.notna(boll_upper.iloc[idx]) else latest_close * 1.05
    latest_lower = float(boll_lower.iloc[idx]) if pd.notna(boll_lower.iloc[idx]) else latest_close * 0.95

    if latest_close <= latest_lower:
        boll_pos = "下轨下"
    elif latest_close >= latest_upper:
        boll_pos = "上轨上"
    elif latest_close < latest_ma20:
        boll_pos = "中轨下"
    else:
        boll_pos = "中轨上"

    return {
        "close": round(latest_close, 3),
        "ma20": round(latest_ma20, 3),
        "boll_upper": round(latest_upper, 3),
        "boll_lower": round(latest_lower, 3),
        "boll_position": boll_pos,
        "rsi": round(float(rsi.iloc[idx]) if pd.notna(rsi.iloc[idx]) else 50, 1),
        "bias": round(float(bias.iloc[idx]) if pd.notna(bias.iloc[idx]) else 0, 2),
        "deviation": round(float(deviation.iloc[idx]) if pd.notna(deviation.iloc[idx]) else 0, 2),
        "volume_spike": bool(volume_spike.iloc[idx]) if pd.notna(volume_spike.iloc[idx]) else False,
        "volume": float(volume.iloc[idx]),
        "vol_ma5": round(float(vol_ma5.iloc[idx]) if pd.notna(vol_ma5.iloc[idx]) else 0, 0),
        "date": df["date"].iloc[idx].strftime("%Y-%m-%d"),
        "_deviation_series": deviation.dropna().tolist(),
        "_close_series": close.tolist(),
        "_ma20_series": ma20.dropna().tolist(),
    }


def calculate_score(indicators: dict) -> int:
    """综合评分 0-100"""
    dev = indicators["deviation"]
    rsi = indicators["rsi"]
    bias = indicators["bias"]
    vol_spike = indicators["volume_spike"]
    close = indicators["close"]
    ma20 = indicators["ma20"]
    dev_series = indicators["_deviation_series"]

    # 偏离度评分 (35%)
    if dev_series and len(dev_series) > 10:
        p95 = float(np.percentile(dev_series, 95))
        deviation_score = min(100, (dev / p95) * 100) if p95 > 0 else 50
    else:
        deviation_score = min(100, dev * 20)
    deviation_score = max(0, deviation_score)

    # RSI评分 (25%)
    if close < ma20:
        rsi_score = 100 if rsi <= 28 else max(0, 100 - (rsi - 28) * 2) if rsi <= 50 else max(0, 50 - (rsi - 50))
    else:
        rsi_score = 100 if rsi >= 72 else max(0, (rsi - 50) * 4) if rsi >= 50 else max(0, rsi)

    # 乖离率评分 (20%)
    if close < ma20:
        bias_score = 100 if bias <= -3 else max(0, 100 - abs(bias - (-3)) * 5) if bias <= 0 else max(0, 30 - bias * 5)
    else:
        bias_score = 100 if bias >= 8 else max(0, (bias - 3) * 20) if bias >= 3 else max(0, bias * 10)

    # 成交量评分 (10%)
    volume_score = 100 if vol_spike else 50

    # 历史回归成功率 (10%)
    regression_score = _calc_regression_rate(indicators)

    total = deviation_score * 0.35 + rsi_score * 0.25 + bias_score * 0.20 + volume_score * 0.10 + regression_score * 0.10
    return max(0, min(100, int(round(total))))


def _calc_regression_rate(indicators: dict) -> float:
    close_list = indicators["_close_series"]
    ma20_list = indicators["_ma20_series"]
    dev_list = indicators["_deviation_series"]
    if len(close_list) < 20 or len(ma20_list) < 20:
        return 50
    min_len = min(len(close_list), len(ma20_list), len(dev_list))
    success, total = 0, 0
    for i in range(10, min_len - 3):
        if i < len(dev_list) and dev_list[i] >= 3:
            total += 1
            for j in range(1, 4):
                if i + j < min_len and ma20_list[i + j] != 0:
                    future_dev = abs(close_list[i + j] - ma20_list[i + j]) / ma20_list[i + j] * 100
                    if future_dev < 3:
                        success += 1
                        break
    return min(100, (success / total) * 100) if total > 0 else 50


def generate_signal(indicators: dict, score: int) -> str:
    close = indicators["close"]
    ma20 = indicators["ma20"]
    dev = indicators["deviation"]
    rsi = indicators["rsi"]
    bias = indicators["bias"]
    boll_pos = indicators["boll_position"]
    vol_spike = indicators["volume_spike"]

    if dev >= 3 and close < ma20 and (boll_pos == "下轨下" or rsi <= 28 or bias <= -3) and vol_spike:
        return "buy"
    if dev >= 3 and close > ma20 and (boll_pos == "上轨上" or rsi >= 72 or bias >= 8):
        return "sell"
    if score < 60:
        return "sell_weak"
    return "hold"


def pyramid_position(score: int, max_pos: float) -> float:
    if score < 60:
        return 0.0
    elif score < 75:
        return round(max_pos * 0.33, 2)
    elif score < 85:
        return round(max_pos * 0.66, 2)
    else:
        return round(max_pos * 1.0, 2)


def run_strategy() -> dict:
    """运行完整均值回归策略"""
    results = []
    errors = []
    buy_signals = []
    sell_signals = []

    # 按trade_date批量获取所有ETF数据
    etf_data = fetch_all_etf_data_batch(days=120)

    for etf in ETF_POOL:
        code = etf["code"]
        try:
            df = etf_data.get(code)
            if df is None or len(df) < 20:
                count = len(df) if df is not None else 0
                errors.append({"code": code, "name": etf["name"], "error": f"数据不足({count}条)"})
                continue

            ind = calculate_indicators(df)
            if ind is None:
                errors.append({"code": code, "name": etf["name"], "error": "指标计算失败"})
                continue

            score = calculate_score(ind)
            signal = generate_signal(ind, score)
            suggested_pos = pyramid_position(score, etf["max_pos"])

            row = {
                "code": code, "name": etf["name"], "category": etf["category"],
                "max_position": etf["max_pos"],
                "close": ind["close"], "ma20": ind["ma20"],
                "deviation": ind["deviation"], "rsi": ind["rsi"], "bias": ind["bias"],
                "boll_upper": ind["boll_upper"], "boll_lower": ind["boll_lower"],
                "boll_position": ind["boll_position"],
                "volume_spike": ind["volume_spike"],
                "volume_ratio": round(ind["volume"] / ind["vol_ma5"], 2) if ind["vol_ma5"] > 0 else 0,
                "score": score, "signal": signal,
                "suggested_position": suggested_pos, "date": ind["date"],
            }
            results.append(row)
            if signal == "buy":
                buy_signals.append(row)
            elif signal in ("sell", "sell_weak"):
                sell_signals.append(row)
        except Exception as e:
            errors.append({"code": code, "name": etf["name"], "error": str(e)})

    buy_signals.sort(key=lambda x: x["score"], reverse=True)
    sell_signals.sort(key=lambda x: x["score"])
    results.sort(key=lambda x: x["score"], reverse=True)

    if results:
        deviations = [r["deviation"] for r in results]
        avg_dev = round(np.mean(deviations), 2)
        max_dev_item = max(results, key=lambda x: x["deviation"])
        min_dev_item = min(results, key=lambda x: x["deviation"])
        above_3pct = sum(1 for d in deviations if d >= 3)
        total_suggested = min(round(sum(r["suggested_position"] for r in results), 1), 85.0)
    else:
        avg_dev, above_3pct, total_suggested = 0, 0, 0
        max_dev_item = min_dev_item = {"code": "-", "name": "-", "deviation": 0}

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "market_overview": {
                "avg_deviation": avg_dev,
                "max_deviation": {"code": max_dev_item["code"], "name": max_dev_item["name"], "value": max_dev_item["deviation"]},
                "min_deviation": {"code": min_dev_item["code"], "name": min_dev_item["name"], "value": min_dev_item["deviation"]},
                "signal_count": {"buy": len(buy_signals), "sell": len(sell_signals), "hold": len(results) - len(buy_signals) - len(sell_signals)},
                "above_3pct": above_3pct,
                "total_suggested_position": total_suggested,
                "total_etfs": len(results),
                "market_divergence": "高分化" if above_3pct >= 10 else ("中等分化" if above_3pct >= 5 else "低分化"),
            },
            "signals": results,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "errors": errors,
        }
    }


if __name__ == "__main__":
    import json
    print("正在运行均值回归策略...")
    result = run_strategy()
    print(json.dumps(result, ensure_ascii=False, indent=2))
