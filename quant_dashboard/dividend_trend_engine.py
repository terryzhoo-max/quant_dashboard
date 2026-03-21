"""
AlphaCore · 红利趋势增强策略引擎 V2.0
数据源：Tushare（5000积分用户 — 按ts_code批量获取）
标的池：8只红利类ETF · 固定权重配置
"""

import pandas as pd
import numpy as np
import tushare as ts
from datetime import datetime, timedelta
import traceback

# ====== Tushare 初始化 ======
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ====== 标的池与固定权重 ======
DIVIDEND_POOL = [
    {'code': '515100.SH', 'name': '中证红利低波100ETF', 'weight': 15},
    {'code': '510880.SH', 'name': '红利ETF',           'weight': 15},
    {'code': '159545.SZ', 'name': '恒生红利低波ETF',    'weight': 15},
    {'code': '512890.SH', 'name': '红利低波ETF',        'weight': 15},
    {'code': '515080.SH', 'name': '央企红利ETF',        'weight': 10},
    {'code': '513530.SH', 'name': '港股通红利ETF',      'weight': 10},
    {'code': '513950.SH', 'name': '恒生红利ETF',        'weight': 10},
    {'code': '159201.SZ', 'name': '自由现金流ETF',      'weight': 10},
]


def fetch_etf_data_by_code(days: int = 150) -> dict:
    """
    5000积分用户高效模式：按ts_code逐只获取历史数据
    8只ETF仅需8次API调用，远优于按trade_date循环150次
    """
    print(f"[红利引擎] 开始获取{days}天历史数据（按ts_code获取）...")

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=int(days * 2.0))).strftime("%Y%m%d")

    etf_data = {}
    for item in DIVIDEND_POOL:
        code = item['code']
        try:
            df = pro.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values('trade_date').reset_index(drop=True)
                # 只保留最近 days 条记录
                df = df.tail(days).reset_index(drop=True)
                etf_data[code] = df
                print(f"  [OK] {item['name']}({code}): {len(df)}条数据")
            else:
                print(f"  [FAIL] {item['name']}({code}): 无数据返回")
        except Exception as e:
            print(f"  [FAIL] {item['name']}({code}): {e}")

    print(f"[红利引擎] 数据获取完成，共{len(etf_data)}/8只ETF有数据")
    return etf_data


def calculate_indicators(df):
    """计算红利趋势策略所需的全部指标"""
    close = df['close'].astype(float)

    # 1. 100日趋势均线（核心：牛熊分割线）
    ma100 = close.rolling(100).mean()
    # 趋势方向：当前MA100 > 前一日MA100 = 向上
    trend_up = ma100.iloc[-1] > ma100.iloc[-2] if len(ma100.dropna()) >= 2 else False

    # 2. 布林带 (20, 2)
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    boll_upper = ma20 + 2 * std20
    boll_lower = ma20 - 2 * std20

    # 3. RSI (14)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, 0.001)
    rsi = 100 - (100 / (1 + rs))

    # 4. 乖离率 (BIAS) — 基于MA20
    bias = (close - ma20) / ma20 * 100

    idx = len(df) - 1
    return {
        'close': round(float(close.iloc[idx]), 3),
        'ma100': round(float(ma100.iloc[idx]), 3) if pd.notna(ma100.iloc[idx]) else 0,
        'ma20': round(float(ma20.iloc[idx]), 3) if pd.notna(ma20.iloc[idx]) else 0,
        'trend_up': bool(trend_up),
        'rsi': round(float(rsi.iloc[idx]), 1) if pd.notna(rsi.iloc[idx]) else 50,
        'bias': round(float(bias.iloc[idx]), 2) if pd.notna(bias.iloc[idx]) else 0,
        'boll_upper': round(float(boll_upper.iloc[idx]), 3) if pd.notna(boll_upper.iloc[idx]) else 0,
        'boll_lower': round(float(boll_lower.iloc[idx]), 3) if pd.notna(boll_lower.iloc[idx]) else 0,
        'date': df['trade_date'].iloc[idx],
    }


def generate_signal(ind, weight):
    """根据策略规则生成买卖信号"""
    trend_up = ind['trend_up']
    rsi = ind['rsi']
    bias = ind['bias']
    close = ind['close']
    boll_upper = ind['boll_upper']
    boll_lower = ind['boll_lower']

    # 买入信号: 趋势向上 AND (RSI≤30 OR 触及布林下轨 OR 乖离率≤-5%)
    if trend_up and (rsi <= 30 or close <= boll_lower or bias <= -5):
        return 'buy', weight

    # 卖出信号: 趋势向下 OR 布林上轨 OR 乖离≥15% OR RSI≥72
    if not trend_up:
        return 'sell', 0
    if close >= boll_upper or bias >= 15 or rsi >= 72:
        return 'sell', 0

    # 持有：趋势向上但无超跌/超买信号
    return 'hold', weight


def run_dividend_strategy() -> dict:
    """运行全量红利趋势策略"""
    print("[红利引擎] ========= 红利趋势策略 V2.0 启动 =========")

    # 按ts_code批量获取（仅8次API调用）
    etf_data = fetch_etf_data_by_code(days=150)

    results = []
    errors = []

    for item in DIVIDEND_POOL:
        code = item['code']
        try:
            df = etf_data.get(code)
            if df is None or len(df) < 100:
                count = len(df) if df is not None else 0
                errors.append({
                    "code": code, "name": item['name'],
                    "error": f"历史数据不足({count}条，需100条以上)"
                })
                continue

            ind = calculate_indicators(df)
            signal, suggested_pos = generate_signal(ind, item['weight'])

            results.append({
                'code': code.split('.')[0],
                'name': item['name'],
                'close': ind['close'],
                'ma100': ind['ma100'],
                'trend': 'UP' if ind['trend_up'] else 'DOWN',
                'rsi': ind['rsi'],
                'bias': ind['bias'],
                'boll_pos': round(
                    (ind['close'] - ind['boll_lower']) /
                    (ind['boll_upper'] - ind['boll_lower']) * 100, 1
                ) if (ind['boll_upper'] - ind['boll_lower']) > 0 else 50,
                'signal': signal,
                'suggested_position': suggested_pos,
            })

        except Exception as e:
            errors.append({"code": code, "name": item['name'], "error": str(e)})
            traceback.print_exc()

    # 市场概览统计
    buy_count = len([r for r in results if r['signal'] == 'buy'])
    sell_count = len([r for r in results if r['signal'] == 'sell'])
    total_pos = sum(r['suggested_position'] for r in results if r['signal'] != 'sell')
    trend_up_count = len([r for r in results if r['trend'] == 'UP'])

    # 限制总仓位 80%
    if total_pos > 80:
        total_pos = 80

    print(f"[红利引擎] 完成: {len(results)}只有信号, {len(errors)}只异常")
    print(f"[红利引擎] 趋势向上:{trend_up_count}, 买入:{buy_count}, 卖出:{sell_count}")

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "signals": results,
            "market_overview": {
                "trend_up_count": trend_up_count,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "total_suggested_pos": total_pos,
            },
            "errors": errors,
        }
    }


if __name__ == "__main__":
    import json
    print("正在运行红利趋势策略...")
    result = run_dividend_strategy()
    print(json.dumps(result, ensure_ascii=False, indent=2))
