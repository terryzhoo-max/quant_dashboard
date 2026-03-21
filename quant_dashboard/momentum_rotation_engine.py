"""
AlphaCore · 行业动量轮动策略引擎 V1.0
数据源：Tushare（5000积分 — 按ts_code批量获取）
标的池：20只行业/赛道ETF · 三层环境过滤 · 牛熊自适应

核心逻辑：
1. 三层市场环境过滤（趋势/波动率/极端风险）
2. 市场状态自适应参数（牛/熊/震荡）
3. 20日动量排名 → 选Top N最强行业
4. 分散化约束（单只≤30%、单行业≤40%、最少3只）
"""

import pandas as pd
import numpy as np
import tushare as ts
import yfinance as yf
from datetime import datetime, timedelta
import traceback

# ====== Tushare 初始化 ======
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ====== 标的池定义（20只行业ETF · 4组） ======
MOMENTUM_POOL = [
    # 科技AI（6只）
    {"code": "512480.SH", "name": "半导体ETF",         "group": "科技AI",     "max_pos": 25},
    {"code": "588200.SH", "name": "科创芯片ETF",       "group": "科技AI",     "max_pos": 20},
    {"code": "159995.SZ", "name": "芯片ETF",           "group": "科技AI",     "max_pos": 20},
    {"code": "515070.SH", "name": "人工智能AIETF",     "group": "科技AI",     "max_pos": 20},
    {"code": "159819.SZ", "name": "人工智能ETF易方达", "group": "科技AI",     "max_pos": 20},
    {"code": "515880.SH", "name": "通信ETF国泰",       "group": "科技AI",     "max_pos": 20},

    # 新能源周期（5只）
    {"code": "516160.SH", "name": "新能源ETF",         "group": "新能源周期", "max_pos": 22},
    {"code": "515790.SH", "name": "光伏ETF",           "group": "新能源周期", "max_pos": 22},
    {"code": "512400.SH", "name": "有色金属ETF",       "group": "新能源周期", "max_pos": 22},
    {"code": "159870.SZ", "name": "化工ETF",           "group": "新能源周期", "max_pos": 18},
    {"code": "562550.SH", "name": "绿电ETF",           "group": "新能源周期", "max_pos": 18},

    # 军工制造金融（5只）
    {"code": "512560.SH", "name": "军工ETF",           "group": "军工制造",   "max_pos": 22},
    {"code": "159218.SZ", "name": "卫星ETF招商",       "group": "军工制造",   "max_pos": 18},
    {"code": "562500.SH", "name": "机器人ETF",         "group": "军工制造",   "max_pos": 20},
    {"code": "159326.SZ", "name": "电网设备ETF",       "group": "军工制造",   "max_pos": 18},
    {"code": "159851.SZ", "name": "金融科技ETF",       "group": "军工制造",   "max_pos": 18},

    # 港股消费（4只）
    {"code": "513130.SH", "name": "恒生科技ETF",       "group": "港股消费",   "max_pos": 22},
    {"code": "513120.SH", "name": "港股创新药ETF",     "group": "港股消费",   "max_pos": 18},
    {"code": "159869.SZ", "name": "游戏ETF",           "group": "港股消费",   "max_pos": 18},
    {"code": "588220.SH", "name": "科创100ETF鹏华",    "group": "港股消费",   "max_pos": 20},
]

# ====== 市场状态自适应参数 ======
REGIME_PARAMS = {
    "BULL": {
        "label": "牛市",
        "top_n": 5,
        "momentum_threshold": 0,
        "position_cap": 85,
        "single_cap": 30,
        "volatility_filter": False,
    },
    "BEAR": {
        "label": "熊市",
        "top_n": 3,
        "momentum_threshold": 5,
        "position_cap": 40,
        "single_cap": 20,
        "volatility_filter": True,
    },
    "RANGE": {
        "label": "震荡",
        "top_n": 5,
        "momentum_threshold": 2,
        "position_cap": 65,
        "single_cap": 25,
        "volatility_filter": True,
    },
}

# 行业组仓位上限
GROUP_POSITION_CAP = 40  # 单行业组合计 ≤ 40%
MIN_HOLDINGS = 3          # 最少同时持有3只
STOP_LOSS_PCT = -8        # 止损线 (%)
LOOKBACK_PERIOD = 20      # 动量回看期（交易日）
VOLUME_RATIO_MIN = 0.8    # 量比最低要求


# ====================================================================
#  数据获取层
# ====================================================================

def fetch_etf_data(days: int = 60) -> dict:
    """
    按ts_code逐只获取历史数据。
    20只ETF = 20次API调用，高效稳定。
    """
    print(f"[动量引擎] 开始获取{days}天历史数据...")
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=int(days * 2.0))).strftime("%Y%m%d")

    etf_data = {}
    for item in MOMENTUM_POOL:
        code = item["code"]
        try:
            df = pro.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
                df = df.tail(days).reset_index(drop=True)
                etf_data[code] = df
                print(f"  [OK] {item['name']}({code}): {len(df)}条")
            else:
                print(f"  [FAIL] {item['name']}({code}): 无数据")
        except Exception as e:
            print(f"  [FAIL] {item['name']}({code}): {e}")

    print(f"[动量引擎] 数据获取完成: {len(etf_data)}/20 只")
    return etf_data


def fetch_hs300_data(days: int = 150) -> pd.DataFrame:
    """获取沪深300指数数据用于市场环境判断"""
    print("[动量引擎] 获取沪深300指数数据...")
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=int(days * 2.0))).strftime("%Y%m%d")
        df = pro.index_daily(ts_code="000300.SH", start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values("trade_date").reset_index(drop=True)
            df = df.tail(days).reset_index(drop=True)
            print(f"  [OK] 沪深300: {len(df)}条")
            return df
    except Exception as e:
        print(f"  [FAIL] 沪深300: {e}")
    return None


def fetch_vix() -> float:
    """获取VIX恐慌指数"""
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        if hist is not None and not hist.empty:
            val = float(hist["Close"].iloc[-1])
            print(f"  [OK] VIX: {val:.2f}")
            return val
    except Exception as e:
        print(f"  [WARN] VIX获取失败: {e}, 使用默认值20")
    return 20.0  # 默认中性


# ====================================================================
#  三层市场环境过滤
# ====================================================================

def assess_market_environment(hs300_df, etf_data: dict) -> dict:
    """
    三层市场过滤 → 确定仓位上限和市场状态

    Layer 1: 趋势过滤 — 沪深300 vs 120日均线
    Layer 2: 波动率过滤 — VIX恐慌指数
    Layer 3: 极端风险 — 全池ETF当日跌幅分析
    """
    env = {
        "layer1_trend": "正常",
        "layer1_cap": 85,
        "layer2_vix": 20.0,
        "layer2_cap": 85,
        "layer3_crash": False,
        "layer3_cap": 85,
        "final_cap": 85,
        "regime": "RANGE",
        "regime_label": "震荡",
    }

    # ---- Layer 1: 沪深300趋势过滤 ----
    if hs300_df is not None and len(hs300_df) >= 120:
        close = hs300_df["close"].astype(float)
        ma120 = close.rolling(120).mean()
        latest_close = float(close.iloc[-1])
        latest_ma120 = float(ma120.iloc[-1])

        if pd.notna(latest_ma120):
            if latest_close > latest_ma120:
                # 判断MA120方向
                ma120_prev = float(ma120.iloc[-2]) if pd.notna(ma120.iloc[-2]) else latest_ma120
                if latest_ma120 > ma120_prev:
                    env["layer1_trend"] = "牛市（站上均线且均线向上）"
                    env["layer1_cap"] = 85
                    env["regime"] = "BULL"
                else:
                    env["layer1_trend"] = "震荡偏多（站上均线但均线走平）"
                    env["layer1_cap"] = 70
                    env["regime"] = "RANGE"
            else:
                ma120_prev = float(ma120.iloc[-2]) if pd.notna(ma120.iloc[-2]) else latest_ma120
                if latest_ma120 < ma120_prev:
                    env["layer1_trend"] = "熊市（跌破均线且均线向下）"
                    env["layer1_cap"] = 40
                    env["regime"] = "BEAR"
                else:
                    env["layer1_trend"] = "震荡偏空（跌破均线但均线走平）"
                    env["layer1_cap"] = 50
                    env["regime"] = "RANGE"
    else:
        env["layer1_trend"] = "数据不足，默认震荡"

    # ---- Layer 2: VIX波动率过滤 ----
    vix_val = fetch_vix()
    env["layer2_vix"] = round(vix_val, 2)
    if vix_val >= 30:
        env["layer2_cap"] = 30
    elif vix_val >= 25:
        env["layer2_cap"] = 50
    else:
        env["layer2_cap"] = 85

    # ---- Layer 3: 极端风险检测 ----
    crash_count = 0
    total_count = 0
    for code, df in etf_data.items():
        if len(df) >= 2:
            total_count += 1
            pct_change = (float(df["close"].iloc[-1]) - float(df["close"].iloc[-2])) / float(df["close"].iloc[-2]) * 100
            if pct_change <= -5:
                crash_count += 1

    if total_count > 0 and (crash_count / total_count) >= 0.3:
        env["layer3_crash"] = True
        env["layer3_cap"] = 0  # 空仓避险
    else:
        env["layer3_crash"] = False
        env["layer3_cap"] = 85

    # ---- 三层取最严 ----
    env["final_cap"] = min(env["layer1_cap"], env["layer2_cap"], env["layer3_cap"])
    env["regime_label"] = REGIME_PARAMS[env["regime"]]["label"]

    print(f"[动量引擎] 环境评估: {env['regime']}")
    print(f"  L1(趋势): {env['layer1_trend']} → {env['layer1_cap']}%")
    print(f"  L2(VIX): {env['layer2_vix']} → {env['layer2_cap']}%")
    print(f"  L3(极端): crash={env['layer3_crash']} → {env['layer3_cap']}%")
    print(f"  最终仓位上限: {env['final_cap']}%")

    return env


# ====================================================================
#  技术指标计算
# ====================================================================

def calculate_indicators(df) -> dict:
    """计算动量、量比、波动率、RSI等指标"""
    close = df["close"].astype(float)
    volume = df["vol"].astype(float) if "vol" in df.columns else df["volume"].astype(float)

    if len(close) < LOOKBACK_PERIOD:
        return None

    # 20日动量 (%)
    close_now = float(close.iloc[-1])
    close_20ago = float(close.iloc[-LOOKBACK_PERIOD]) if len(close) >= LOOKBACK_PERIOD else close_now
    momentum_pct = round((close_now / close_20ago - 1) * 100, 2) if close_20ago > 0 else 0

    # 成交量比率（当日 / 20日均量）
    vol_ma20 = volume.rolling(20).mean()
    latest_vol = float(volume.iloc[-1])
    latest_vol_ma20 = float(vol_ma20.iloc[-1]) if pd.notna(vol_ma20.iloc[-1]) else latest_vol
    volume_ratio = round(latest_vol / latest_vol_ma20, 2) if latest_vol_ma20 > 0 else 1.0

    # 20日历史波动率（年化）
    returns = close.pct_change().dropna()
    if len(returns) >= 20:
        hist_vol = float(returns.tail(20).std() * np.sqrt(252) * 100)
    else:
        hist_vol = 0
    hist_vol = round(hist_vol, 1)

    # RSI (14)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, 0.001)
    rsi = 100 - (100 / (1 + rs))
    latest_rsi = round(float(rsi.iloc[-1]), 1) if pd.notna(rsi.iloc[-1]) else 50

    # 当日涨跌幅
    if len(close) >= 2:
        day_change = round((float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100, 2)
    else:
        day_change = 0

    return {
        "close": round(close_now, 3),
        "momentum_pct": momentum_pct,
        "volume_ratio": volume_ratio,
        "hist_vol": hist_vol,
        "rsi": latest_rsi,
        "day_change": day_change,
        "date": df["trade_date"].iloc[-1],
        "_close_series": close.tolist(),
    }


# ====================================================================
#  信号生成与分散化约束
# ====================================================================

def apply_diversification(ranked_signals: list, regime_params: dict, group_cap: float = GROUP_POSITION_CAP) -> list:
    """
    应用分散化约束：
    1. 单行业组合计 ≤ 40%
    2. 确保最少3只持仓
    3. 单只不超过 regime 上限
    """
    single_cap = regime_params["single_cap"]
    group_positions = {}  # {group: total_position}
    final_signals = []

    for sig in ranked_signals:
        group = sig["group"]
        current_group_pos = group_positions.get(group, 0)
        desired_pos = min(sig["raw_position"], single_cap)

        # 行业组上限检查
        if current_group_pos + desired_pos > group_cap:
            desired_pos = max(0, group_cap - current_group_pos)

        if desired_pos > 0:
            sig["suggested_position"] = round(desired_pos, 1)
            group_positions[group] = current_group_pos + desired_pos
            final_signals.append(sig)

    return final_signals


def generate_signals(etf_data: dict, env: dict) -> dict:
    """
    核心信号生成流程：
    1. 计算全部指标
    2. 排名
    3. 根据市场状态筛选 Top N
    4. 应用分散化约束
    """
    regime = env["regime"]
    params = REGIME_PARAMS[regime]
    position_cap = env["final_cap"]

    all_results = []
    errors = []
    vol_values = []  # 收集波动率用于过滤

    # Step 1: 计算所有标的的指标
    for item in MOMENTUM_POOL:
        code = item["code"]
        try:
            df = etf_data.get(code)
            if df is None or len(df) < LOOKBACK_PERIOD:
                count = len(df) if df is not None else 0
                errors.append({"code": code, "name": item["name"],
                               "error": f"数据不足({count}条，需{LOOKBACK_PERIOD}条)"})
                continue

            ind = calculate_indicators(df)
            if ind is None:
                errors.append({"code": code, "name": item["name"], "error": "指标计算失败"})
                continue

            vol_values.append(ind["hist_vol"])
            all_results.append({
                "code": code.split(".")[0],
                "ts_code": code,
                "name": item["name"],
                "group": item["group"],
                "max_pos": item["max_pos"],
                "close": ind["close"],
                "momentum_pct": ind["momentum_pct"],
                "volume_ratio": ind["volume_ratio"],
                "hist_vol": ind["hist_vol"],
                "rsi": ind["rsi"],
                "day_change": ind["day_change"],
                "date": ind["date"],
            })
        except Exception as e:
            errors.append({"code": code, "name": item["name"], "error": str(e)})
            traceback.print_exc()

    if not all_results:
        return {"signals": [], "buy_signals": [], "sell_signals": [],
                "errors": errors, "market_overview": _empty_overview(env)}

    # Step 2: 动量排名（降序，Rank 1 = 最强）
    all_results.sort(key=lambda x: x["momentum_pct"], reverse=True)
    for i, r in enumerate(all_results):
        r["rank"] = i + 1

    # 波动率均值（用于震荡市过滤）
    avg_vol = np.mean(vol_values) if vol_values else 30

    # Step 3: 信号生成
    top_n = params["top_n"]
    momentum_threshold = params["momentum_threshold"]
    use_vol_filter = params["volatility_filter"]
    buy_candidates = []
    sell_signals = []

    for r in all_results:
        # 量比检查
        volume_ok = r["volume_ratio"] >= VOLUME_RATIO_MIN
        # 动量阈值检查
        momentum_ok = r["momentum_pct"] > momentum_threshold
        # 排名检查
        rank_ok = r["rank"] <= top_n
        # 波动率过滤（震荡/熊市）
        vol_ok = (not use_vol_filter) or (r["hist_vol"] <= avg_vol * 1.2)

        if rank_ok and momentum_ok and volume_ok and vol_ok:
            r["signal"] = "buy"
            r["raw_position"] = min(r["max_pos"], params["single_cap"])
            buy_candidates.append(r)
        elif r["momentum_pct"] < 0:
            r["signal"] = "sell"
            r["suggested_position"] = 0
            sell_signals.append(r)
        elif not rank_ok and r["momentum_pct"] > 0:
            r["signal"] = "hold"
            r["suggested_position"] = 0
        else:
            r["signal"] = "sell_weak"
            r["suggested_position"] = 0
            sell_signals.append(r)

    # Step 4: 分散化约束
    buy_signals = apply_diversification(buy_candidates, params)

    # 确保最少3只（如果可用标的够的话）
    if len(buy_signals) < MIN_HOLDINGS and len(buy_candidates) >= MIN_HOLDINGS:
        for r in buy_candidates:
            if r not in buy_signals:
                r["suggested_position"] = round(params["single_cap"] * 0.5, 1)
                buy_signals.append(r)
                if len(buy_signals) >= MIN_HOLDINGS:
                    break

    # Step 5: 总仓位上限约束
    total_pos = sum(s["suggested_position"] for s in buy_signals)
    if total_pos > position_cap:
        scale = position_cap / total_pos
        for s in buy_signals:
            s["suggested_position"] = round(s["suggested_position"] * scale, 1)
        total_pos = position_cap

    # 给所有非买入的标注 suggested_position
    for r in all_results:
        if "suggested_position" not in r:
            r["suggested_position"] = 0
        if "signal" not in r:
            r["signal"] = "hold"

    # 统计概览
    overview = {
        "regime": env["regime"],
        "regime_label": env["regime_label"],
        "position_cap": env["final_cap"],
        "layer1_trend": env["layer1_trend"],
        "layer2_vix": env["layer2_vix"],
        "layer3_crash": env["layer3_crash"],
        "top1_momentum": all_results[0]["momentum_pct"] if all_results else 0,
        "top1_name": all_results[0]["name"] if all_results else "-",
        "avg_momentum": round(np.mean([r["momentum_pct"] for r in all_results]), 2),
        "buy_count": len(buy_signals),
        "sell_count": len(sell_signals),
        "total_suggested_pos": round(total_pos, 1),
        "total_etfs": len(all_results),
    }

    return {
        "signals": all_results,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "errors": errors,
        "market_overview": overview,
    }


def _empty_overview(env):
    return {
        "regime": env["regime"],
        "regime_label": env["regime_label"],
        "position_cap": env["final_cap"],
        "layer1_trend": env["layer1_trend"],
        "layer2_vix": env["layer2_vix"],
        "layer3_crash": env["layer3_crash"],
        "top1_momentum": 0, "top1_name": "-",
        "avg_momentum": 0, "buy_count": 0, "sell_count": 0,
        "total_suggested_pos": 0, "total_etfs": 0,
    }


# ====================================================================
#  策略主入口
# ====================================================================

def run_momentum_strategy() -> dict:
    """运行完整行业动量轮动策略"""
    print("[动量引擎] ========= 行业动量轮动策略 V1.0 启动 =========")

    # 1. 获取ETF数据
    etf_data = fetch_etf_data(days=60)

    # 2. 获取沪深300数据（环境判断）
    hs300_df = fetch_hs300_data(days=150)

    # 3. 三层市场环境评估
    env = assess_market_environment(hs300_df, etf_data)

    # 4. 如果极端风险 → 直接空仓返回
    if env["layer3_crash"]:
        print("[动量引擎] ! 极端风险 ! 全池30%+标的跌幅超5%，空仓避险")
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "signals": [],
                "buy_signals": [],
                "sell_signals": [],
                "errors": [],
                "market_overview": _empty_overview(env),
            }
        }

    # 5. 信号生成
    result = generate_signals(etf_data, env)

    print(f"[动量引擎] 完成: {result['market_overview']['total_etfs']}只有信号, "
          f"{len(result['errors'])}只异常")
    print(f"[动量引擎] 状态:{env['regime']} "
          f"买入:{result['market_overview']['buy_count']} "
          f"卖出:{result['market_overview']['sell_count']} "
          f"建议总仓:{result['market_overview']['total_suggested_pos']}%")

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "data": result,
    }


if __name__ == "__main__":
    import json
    print("正在运行行业动量轮动策略...")
    result = run_momentum_strategy()
    print(json.dumps(result, ensure_ascii=False, indent=2))
