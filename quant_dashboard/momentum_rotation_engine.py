"""
AlphaCore · 行业动量轮动策略引擎 V3.0
数据源：Tushare（5000积分 — 按ts_code批量获取）
标的池：20只进攻型 + 4只防御型行业ETF · 三层环境过滤 · Regime自适应因子权重

V3.0 升级：
- Regime 自适应因子权重（BULL追强 / RANGE均衡 / BEAR防守）
- 新增防御型标的池（红利低波/医药/消费），仅BEAR/RANGE模式激活
- 6维100分制动量评分函数 calculate_momentum_score()
- 信号评分交叉验证（温和版：技术面警告标注）
- 止损线分状态：BULL -8% / RANGE -7% / BEAR -5%
"""

import pandas as pd
import numpy as np
import tushare as ts
import os
import time
from datetime import datetime, timedelta
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== Tushare 初始化 ======
from config import TUSHARE_TOKEN
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ====== 标的池定义 ======
# 进攻型标的池（20只 · 全市场ALL状态可用）
MOMENTUM_POOL_OFFENSE = [
    # 科技AI（6只）
    {"code": "512480.SH", "name": "半导体ETF",         "group": "科技AI",     "max_pos": 25, "type": "offense"},
    {"code": "588200.SH", "name": "科创芯片ETF",       "group": "科技AI",     "max_pos": 20, "type": "offense"},
    {"code": "159995.SZ", "name": "芯片ETF",           "group": "科技AI",     "max_pos": 20, "type": "offense"},
    {"code": "515070.SH", "name": "人工智能AIETF",     "group": "科技AI",     "max_pos": 20, "type": "offense"},
    {"code": "159819.SZ", "name": "人工智能ETF易方达", "group": "科技AI",     "max_pos": 20, "type": "offense"},
    {"code": "515880.SH", "name": "通信ETF国泰",       "group": "科技AI",     "max_pos": 20, "type": "offense"},
    # 新能源周期（5只）
    {"code": "516160.SH", "name": "新能源ETF",         "group": "新能源周期", "max_pos": 22, "type": "offense"},
    {"code": "515790.SH", "name": "光伏ETF",           "group": "新能源周期", "max_pos": 22, "type": "offense"},
    {"code": "512400.SH", "name": "有色金属ETF",       "group": "新能源周期", "max_pos": 22, "type": "offense"},
    {"code": "159870.SZ", "name": "化工ETF",           "group": "新能源周期", "max_pos": 18, "type": "offense"},
    {"code": "562550.SH", "name": "绿电ETF",           "group": "新能源周期", "max_pos": 18, "type": "offense"},
    # 军工制造金融（5只）
    {"code": "512560.SH", "name": "军工ETF",           "group": "军工制造",   "max_pos": 22, "type": "offense"},
    {"code": "159218.SZ", "name": "卫星ETF招商",       "group": "军工制造",   "max_pos": 18, "type": "offense"},
    {"code": "562500.SH", "name": "机器人ETF",         "group": "军工制造",   "max_pos": 20, "type": "offense"},
    {"code": "159326.SZ", "name": "电网设备ETF",       "group": "军工制造",   "max_pos": 18, "type": "offense"},
    {"code": "159851.SZ", "name": "金融科技ETF",       "group": "军工制造",   "max_pos": 18, "type": "offense"},
    # 港股消费（4只）
    {"code": "513130.SH", "name": "恒生科技ETF",       "group": "港股消费",   "max_pos": 22, "type": "offense"},
    {"code": "513120.SH", "name": "港股创新药ETF",     "group": "港股消费",   "max_pos": 18, "type": "offense"},
    {"code": "159869.SZ", "name": "游戏ETF",           "group": "港股消费",   "max_pos": 18, "type": "offense"},
    {"code": "588220.SH", "name": "科创100ETF鹏华",    "group": "港股消费",   "max_pos": 20, "type": "offense"},
]

# 防御型标的池（4只 · 仅RANGE/BEAR状态激活）
MOMENTUM_POOL_DEFENSE = [
    {"code": "515100.SH", "name": "红利低波100ETF",   "group": "防御红利",   "max_pos": 20, "type": "defense"},
    {"code": "510880.SH", "name": "红利ETF",           "group": "防御红利",   "max_pos": 18, "type": "defense"},
    {"code": "512010.SH", "name": "医药ETF",           "group": "防御消费",   "max_pos": 18, "type": "defense"},
    {"code": "159928.SZ", "name": "消费ETF",           "group": "防御消费",   "max_pos": 18, "type": "defense"},
]

# 向后兼容：MOMENTUM_POOL = 全部进攻型（外部模块引用）
MOMENTUM_POOL = MOMENTUM_POOL_OFFENSE


def get_active_pool(regime: str) -> list:
    """根据 Regime 返回当前活跃标的池"""
    if regime in ("BEAR", "RANGE"):
        return MOMENTUM_POOL_OFFENSE + MOMENTUM_POOL_DEFENSE
    return MOMENTUM_POOL_OFFENSE


# ====== V3.0 Regime 自适应参数（含因子权重+止损+评分门槛） ======
REGIME_PARAMS = {
    "BULL": {
        "label":    "牛市",
        "strategy": "追强",      # 核心策略标签
        "top_n":    5,
        "momentum_threshold": 0,
        "position_cap": 85,
        "single_cap":   30,
        "stop_loss":    -8,      # V3.0: 分状态止损
        "volatility_filter": False,
        # V3.0: Regime自适应因子权重
        "w_mom_s":  0.50,       # 牛市：重短期动量（追强）
        "w_mom_m":  0.25,
        "w_slope":  0.15,
        "w_sharpe": 0.10,
        "signal_safety_gate": 55,  # 信号安全门槛（温和）
    },
    "RANGE": {
        "label":    "震荡",
        "strategy": "均衡",
        "top_n":    4,
        "momentum_threshold": 2,
        "position_cap": 60,
        "single_cap":   25,
        "stop_loss":    -7,
        "volatility_filter": True,
        "w_mom_s":  0.35,       # 震荡：均衡配置
        "w_mom_m":  0.30,
        "w_slope":  0.20,
        "w_sharpe": 0.15,
        "signal_safety_gate": 60,
    },
    "BEAR": {
        "label":    "熊市",
        "strategy": "防守",
        "top_n":    3,
        "momentum_threshold": 5,
        "position_cap": 35,
        "single_cap":   20,
        "stop_loss":    -5,
        "volatility_filter": True,
        "w_mom_s":  0.15,       # 熊市：重波动调整（防守）
        "w_mom_m":  0.25,
        "w_slope":  0.20,
        "w_sharpe": 0.40,
        "signal_safety_gate": 70,
    },
}

# 行业组仓位上限
GROUP_POSITION_CAP = 40  # 单行业组合计 ≤ 40%
MIN_HOLDINGS = 3          # 最少同时持有3只
LOOKBACK_PERIOD = 20      # 动量回看期（交易日）
VOLUME_RATIO_MIN = 0.8    # 量比最低要求


# ====================================================================
#  数据获取层
# ====================================================================

def _fetch_single_mom_etf(item, start_date, end_date, days, pro):
    code = item["code"]
    cache_file = f"data_lake/daily_prices/{code}.parquet"
    tag = "[DEF]" if item.get("type") == "defense" else "[OFF]"
    try:
        df = pro.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values("trade_date").reset_index(drop=True)
            df = df.tail(days).reset_index(drop=True)
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            df.to_parquet(cache_file)
            return code, df, f"  {tag} [OK] {item['name']}({code}): {len(df)}条"
    except Exception as e:
        if os.path.exists(cache_file):
            df = pd.read_parquet(cache_file)
            if not df.empty:
                df = df.tail(days).reset_index(drop=True)
                return code, df, f"  {tag} [WARN] {item['name']}({code}) API失败, 降级缓存: {len(df)}条"
        return code, None, f"  [FAIL] {item['name']}({code}): {e}"
    return code, None, f"  [FAIL] {item['name']}({code}): 无数据"

def fetch_etf_data(days: int = 60) -> dict:
    """
    V5.0: 并发拉取历史数据并引入本地 Parquet 降级保护
    """
    full_pool = MOMENTUM_POOL_OFFENSE + MOMENTUM_POOL_DEFENSE
    total = len(full_pool)
    print(f"[动量引擎] 开始并发获取{days}天历史数据 ({total}只)...")
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=int(days * 2.0))).strftime("%Y%m%d")

    etf_data = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_fetch_single_mom_etf, item, start_date, end_date, days, pro) for item in full_pool]
        for future in as_completed(futures):
            code, df, msg = future.result()
            print(msg)
            if df is not None:
                etf_data[code] = df

    print(f"[动量引擎] 数据获取完成: {len(etf_data)}/{total} 只")
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
    """获取VIX恐慌指数 (FRED VIXCLS → CNBC 爬虫 → 默认值)"""
    # Tier 1: FRED VIXCLS
    try:
        from fredapi import Fred
        from config import FRED_API_KEY
        fred = Fred(api_key=FRED_API_KEY)
        series = fred.get_series("VIXCLS", observation_start=(datetime.now() - timedelta(days=10)))
        if series is not None and not series.empty:
            val = float(series.dropna().iloc[-1])
            print(f"  [OK] VIX from FRED: {val:.2f}")
            return val
    except Exception as e:
        print(f"  [WARN] FRED VIX failed: {e}")

    # Tier 2: CNBC 爬虫
    try:
        import requests, re
        url = "https://www.cnbc.com/quotes/.VIX"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            match = re.search(r'"last":"([\d.]+)"', resp.text)
            if match:
                val = float(match.group(1))
                print(f"  [OK] VIX from CNBC: {val:.2f}")
                return val
    except Exception as e:
        print(f"  [WARN] CNBC VIX failed: {e}")

    print(f"  [WARN] VIX全部失败, 使用默认值20")
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
    """V3.0 增强指标计算：新增60日中期动量、趋势斜率、RSI方向、均线偏离"""
    close = df["close"].astype(float)
    volume = df["vol"].astype(float) if "vol" in df.columns else df["volume"].astype(float)

    if len(close) < LOOKBACK_PERIOD:
        return None

    close_now = float(close.iloc[-1])

    # ── 短期动量 MOM_S (20日收益率 %) ──
    close_20ago = float(close.iloc[-LOOKBACK_PERIOD]) if len(close) >= LOOKBACK_PERIOD else close_now
    momentum_pct = round((close_now / close_20ago - 1) * 100, 2) if close_20ago > 0 else 0

    # ── 中期动量 MOM_M (60日收益率 %) ──
    if len(close) >= 60:
        close_60ago = float(close.iloc[-60])
        momentum_m = round((close_now / close_60ago - 1) * 100, 2) if close_60ago > 0 else 0
    else:
        momentum_m = momentum_pct  # 数据不足用短期替代

    # ── 成交量比率（当日 / 20日均量）──
    vol_ma20 = volume.rolling(20).mean()
    latest_vol = float(volume.iloc[-1])
    latest_vol_ma20 = float(vol_ma20.iloc[-1]) if pd.notna(vol_ma20.iloc[-1]) else latest_vol
    volume_ratio = round(latest_vol / latest_vol_ma20, 2) if latest_vol_ma20 > 0 else 1.0

    # ── 20日历史波动率（年化 %）──
    returns = close.pct_change().dropna()
    if len(returns) >= 20:
        hist_vol = float(returns.tail(20).std() * np.sqrt(252) * 100)
    else:
        hist_vol = 0
    hist_vol = round(hist_vol, 1)

    # ── 波动调整收益 SHARPE = MOM_S / hist_vol ──
    # 修复除零错误：防止波动率为0或极小值产生 NaN
    sharpe_factor = round(momentum_pct / hist_vol, 3) if hist_vol > 1e-4 else 0

    # ── 趋势斜率 SLOPE (20日线性回归斜率) ──
    if len(close) >= 20:
        y = np.log(close.tail(20).values.astype(float))
        x = np.arange(20)
        xm = x - x.mean()
        ym = y - y.mean()
        slope = float((xm * ym).sum() / (xm ** 2).sum()) * 252  # 年化
    else:
        slope = 0
    slope = round(slope, 4)

    # ── RSI(14) ──
    delta = close.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, 0.001)
    rsi_series = 100 - (100 / (1 + rs))
    latest_rsi = round(float(rsi_series.iloc[-1]), 1) if pd.notna(rsi_series.iloc[-1]) else 50

    # ── RSI 5日斜率（方向判断）──
    if len(rsi_series) >= 5:
        rsi_slope5 = float(rsi_series.iloc[-1]) - float(rsi_series.iloc[-5])
    else:
        rsi_slope5 = 0
    rsi_slope5 = round(rsi_slope5, 2)

    # ── 均线偏离（close vs MA20）──
    ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else close_now
    ma_deviation = round((close_now / ma20 - 1) * 100, 2) if ma20 > 0 else 0

    # ── 当日涨跌幅 ──
    if len(close) >= 2:
        day_change = round((close_now - float(close.iloc[-2])) / float(close.iloc[-2]) * 100, 2)
    else:
        day_change = 0

    return {
        "close":          round(close_now, 3),
        "momentum_pct":   momentum_pct,     # MOM_S (20d)
        "momentum_m":     momentum_m,        # MOM_M (60d) V3.0新增
        "volume_ratio":   volume_ratio,
        "hist_vol":       hist_vol,
        "sharpe_factor":  sharpe_factor,      # V3.0新增
        "slope":          slope,              # V3.0新增
        "rsi":            latest_rsi,
        "rsi_slope5":     rsi_slope5,          # V3.0新增
        "ma_deviation":   ma_deviation,        # V3.0新增
        "day_change":     day_change,
        "date":           df["trade_date"].iloc[-1],
        "_close_series":  close.tolist(),
    }


# ====================================================================
#  V3.0 动量策略专属6维评分（满分100分）
# ====================================================================

def calculate_momentum_score(indicators: dict, regime: str) -> dict:
    """
    动量策略6维评分体系（满分100分）——权重随 Regime 自适应调整

    ① 短期动量 MOM_S      max 30分（BULL: max 40分）
    ② 中期趋势 MOM_M      max 20分
    ③ 趋势斜率 SLOPE       max 15分
    ④ 波动调整 SHARPE      max 15分（BEAR: max 30分）
    ⑤ 量价配合             max 10分
    ⑥ RSI方向 + 均线偏离    max 10分
    """
    params = REGIME_PARAMS.get(regime, REGIME_PARAMS["RANGE"])
    w_s  = params["w_mom_s"]
    w_m  = params["w_mom_m"]
    w_sl = params["w_slope"]
    w_sh = params["w_sharpe"]

    mom_s = indicators.get("momentum_pct", 0)
    mom_m = indicators.get("momentum_m", 0)
    slope = indicators.get("slope", 0)
    sharpe = indicators.get("sharpe_factor", 0)
    vol_ratio = indicators.get("volume_ratio", 1.0)
    rsi = indicators.get("rsi", 50)
    rsi_slope5 = indicators.get("rsi_slope5", 0)
    ma_dev = indicators.get("ma_deviation", 0)

    # ① 短期动量 (0-40, 根据Regime缩放)
    max_s1 = round(100 * w_s)  # BULL=50, RANGE=35, BEAR=15
    if mom_s >= 15:
        s1 = max_s1
    elif mom_s >= 8:
        s1 = round(max_s1 * 0.8)
    elif mom_s >= 3:
        s1 = round(max_s1 * 0.55)
    elif mom_s >= 0:
        s1 = round(max_s1 * 0.3)
    elif mom_s >= -3:
        s1 = round(max_s1 * 0.1)
    else:
        s1 = 0

    # ② 中期趋势 (0-25)
    max_s2 = round(100 * w_m)
    if mom_m >= 20:
        s2 = max_s2
    elif mom_m >= 10:
        s2 = round(max_s2 * 0.8)
    elif mom_m >= 3:
        s2 = round(max_s2 * 0.5)
    elif mom_m >= 0:
        s2 = round(max_s2 * 0.2)
    else:
        s2 = 0

    # ③ 趋势斜率 (0-20)
    max_s3 = round(100 * w_sl)
    if slope >= 0.5:
        s3 = max_s3
    elif slope >= 0.2:
        s3 = round(max_s3 * 0.7)
    elif slope >= 0:
        s3 = round(max_s3 * 0.3)
    else:
        s3 = 0

    # ④ 波动调整收益 SHARPE (0-30, BEAR时满分30)
    max_s4 = round(100 * w_sh)
    if sharpe >= 1.5:
        s4 = max_s4
    elif sharpe >= 0.8:
        s4 = round(max_s4 * 0.75)
    elif sharpe >= 0.3:
        s4 = round(max_s4 * 0.45)
    elif sharpe >= 0:
        s4 = round(max_s4 * 0.15)
    else:
        s4 = 0

    # ⑤ 量价配合 (0-10)
    s5 = 0
    if vol_ratio >= 2.0:
        s5 = 10
    elif vol_ratio >= 1.5:
        s5 = 8
    elif vol_ratio >= 1.0:
        s5 = 5
    elif vol_ratio >= 0.8:
        s5 = 2

    # ⑥ 行业景气度：RSI方向 + 均线偏离 (0-10)
    s6 = 0
    if rsi_slope5 > 3:
        s6 += 5
    elif rsi_slope5 > 0:
        s6 += 3
    elif rsi_slope5 > -3:
        s6 += 1

    if ma_dev >= 3:
        s6 += 5   # 站稳均线上方
    elif ma_dev >= 0:
        s6 += 3
    elif ma_dev >= -2:
        s6 += 1
    s6 = min(10, s6)

    total = min(100, s1 + s2 + s3 + s4 + s5 + s6)

    return {
        "total": total,
        "breakdown": {
            "mom_s":   s1,    # ① 短期动量
            "mom_m":   s2,    # ② 中期趋势
            "slope":   s3,    # ③ 趋势斜率
            "sharpe":  s4,    # ④ 波动调整
            "volume":  s5,    # ⑤ 量价配合
            "health":  s6,    # ⑥ 行业景气
        }
    }


def cross_validate_signal(indicators: dict, regime: str) -> dict:
    """
    V3.0 温和版交叉验证：
    用均值回归引擎的 calculate_score 做技术面检查
    仅返回警告标注，不改变选股结果
    """
    try:
        from mean_reversion_engine import calculate_score as mr_calc_score

        # 构建均值回归所需的 indicators dict
        close = indicators.get("close", 0)
        rsi = indicators.get("rsi", 50)
        mr_indicators = {
            "rsi":       rsi,
            "rsi_3":     rsi - 1,  # 近似
            "bias":      indicators.get("ma_deviation", 0),
            "percent_b": 0.5,   # 无布林带数据时默认中性
            "vol_ratio": indicators.get("volume_ratio", 1.0),
            "close":     close,
            "ma20":      close / (1 + indicators.get("ma_deviation", 0) / 100) if indicators.get("ma_deviation", 0) != 0 else close,
            "ma_n":      close * 0.97,  # 近似
            "rsi_slope5": indicators.get("rsi_slope5", 0),
            "kline_score": 0,
            "kline_pattern": "neutral",
        }
        result = mr_calc_score(mr_indicators)
        mr_total = result["total"]

        safety_gate = REGIME_PARAMS.get(regime, REGIME_PARAMS["RANGE"])["signal_safety_gate"]

        if mr_total < safety_gate:
            return {
                "warning": True,
                "mr_score": mr_total,
                "gate": safety_gate,
                "message": f"[WARN] 技术面警告: 均值回归评分{mr_total}<门槛{safety_gate}",
            }
        return {"warning": False, "mr_score": mr_total, "gate": safety_gate, "message": ""}
    except Exception as e:
        return {"warning": False, "mr_score": 0, "gate": 0, "message": f"交叉验证失败: {e}"}


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
    V3.0 信号生成流程：
    1. 获取Regime对应的活跃标的池
    2. 计算全部指标 + 6维动量评分
    3. 按Regime自适应权重排名
    4. 温和交叉验证（标注警告）
    5. 分散化约束
    """
    regime = env["regime"]
    params = REGIME_PARAMS.get(regime, REGIME_PARAMS["RANGE"])
    position_cap = env["final_cap"]
    stop_loss = params.get("stop_loss", -8)

    # V3.0: 根据Regime选择活跃标的池
    active_pool = get_active_pool(regime)

    all_results = []
    errors = []
    vol_values = []

    # Step 1: 计算所有标的的指标 + 6维评分
    for item in active_pool:
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

            # V3.0: 6维动量评分
            score_dict = calculate_momentum_score(ind, regime)

            # V3.0: 温和交叉验证
            xv = cross_validate_signal(ind, regime)

            vol_values.append(ind["hist_vol"])
            all_results.append({
                "code":            code.split(".")[0],
                "ts_code":         code,
                "name":            item["name"],
                "group":           item["group"],
                "max_pos":         item["max_pos"],
                "etf_type":        item.get("type", "offense"),   # V3.0
                "close":           ind["close"],
                "momentum_pct":    ind["momentum_pct"],
                "momentum_m":      ind.get("momentum_m", 0),     # V3.0
                "volume_ratio":    ind["volume_ratio"],
                "hist_vol":        ind["hist_vol"],
                "sharpe_factor":   ind.get("sharpe_factor", 0),  # V3.0
                "slope":           ind.get("slope", 0),          # V3.0
                "rsi":             ind["rsi"],
                "rsi_slope5":      ind.get("rsi_slope5", 0),     # V3.0
                "ma_deviation":    ind.get("ma_deviation", 0),   # V3.0
                "day_change":      ind["day_change"],
                "date":            ind["date"],
                # V3.0 评分
                "momentum_score":     score_dict["total"],
                "score_breakdown":    score_dict["breakdown"],
                # V3.0 交叉验证
                "xv_warning":         xv.get("warning", False),
                "xv_mr_score":        xv.get("mr_score", 0),
                "xv_message":         xv.get("message", ""),
            })
        except Exception as e:
            errors.append({"code": code, "name": item["name"], "error": str(e)})
            traceback.print_exc()

    if not all_results:
        return {"signals": [], "buy_signals": [], "sell_signals": [],
                "errors": errors, "market_overview": _empty_overview(env)}

    # Step 2: 按6维动量评分排名（降序）
    all_results.sort(key=lambda x: x["momentum_score"], reverse=True)
    for i, r in enumerate(all_results):
        r["rank"] = i + 1

    avg_vol = np.mean(vol_values) if vol_values else 30

    # Step 3: 信号生成（Regime 自适应）
    top_n = params["top_n"]
    momentum_threshold = params["momentum_threshold"]
    use_vol_filter = params["volatility_filter"]
    buy_candidates = []
    sell_signals = []

    for r in all_results:
        volume_ok = r["volume_ratio"] >= VOLUME_RATIO_MIN
        momentum_ok = r["momentum_pct"] > momentum_threshold
        rank_ok = r["rank"] <= top_n
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

    for r in all_results:
        if "suggested_position" not in r:
            r["suggested_position"] = 0
        if "signal" not in r:
            r["signal"] = "hold"

    # V3.0 增强概览
    overview = {
        "regime":           env["regime"],
        "regime_label":     env["regime_label"],
        "regime_strategy":  params.get("strategy", ""),
        "position_cap":     env["final_cap"],
        "stop_loss":        stop_loss,
        "layer1_trend":     env["layer1_trend"],
        "layer2_vix":       env["layer2_vix"],
        "layer3_crash":     env["layer3_crash"],
        "top1_momentum":    all_results[0]["momentum_pct"] if all_results else 0,
        "top1_name":        all_results[0]["name"] if all_results else "-",
        "top1_score":       all_results[0]["momentum_score"] if all_results else 0,
        "avg_momentum":     round(np.mean([r["momentum_pct"] for r in all_results]), 2),
        "buy_count":        len(buy_signals),
        "sell_count":       len(sell_signals),
        "total_suggested_pos": round(total_pos, 1),
        "total_etfs":       len(all_results),
        "pool_offense":     sum(1 for r in all_results if r["etf_type"] == "offense"),
        "pool_defense":     sum(1 for r in all_results if r["etf_type"] == "defense"),
        "xv_warnings":      sum(1 for r in all_results if r.get("xv_warning")),
        # V3.0 因子权重（供前端可视化）
        "factor_weights": {
            "MOM_S":  int(params["w_mom_s"] * 100),
            "MOM_M":  int(params["w_mom_m"] * 100),
            "SLOPE":  int(params["w_slope"] * 100),
            "SHARPE": int(params["w_sharpe"] * 100),
        },
    }

    return {
        "signals":        all_results,
        "buy_signals":    buy_signals,
        "sell_signals":   sell_signals,
        "errors":         errors,
        "market_overview": overview,
    }


def _empty_overview(env):
    return {
        "regime": env["regime"],
        "regime_label": env["regime_label"],
        "regime_strategy": "",
        "position_cap": env["final_cap"],
        "stop_loss": -8,
        "layer1_trend": env["layer1_trend"],
        "layer2_vix": env["layer2_vix"],
        "layer3_crash": env["layer3_crash"],
        "top1_momentum": 0, "top1_name": "-", "top1_score": 0,
        "avg_momentum": 0, "buy_count": 0, "sell_count": 0,
        "total_suggested_pos": 0, "total_etfs": 0,
        "pool_offense": 0, "pool_defense": 0, "xv_warnings": 0,
        "factor_weights": {"MOM_S": 35, "MOM_M": 30, "SLOPE": 20, "SHARPE": 15},
    }


# ====================================================================
#  策略主入口
# ====================================================================

def run_momentum_strategy() -> dict:
    """运行完整行业动量轮动策略 V3.0（Regime自适应因子引擎）"""
    print("[动量引擎] ========= 行业动量轮动策略 V3.0 启动 =========")

    # 1. 获取ETF数据（含防御型标的）
    etf_data = fetch_etf_data(days=60)

    # 2. 获取沪深300数据
    hs300_df = fetch_hs300_data(days=150)

    # 3. 统一 Regime 识别（与均值回归/信号评分系统使用相同算法）
    unified_regime = "RANGE"
    regime_meta = {}
    if hs300_df is not None and len(hs300_df) >= 30:
        try:
            from mean_reversion_engine import _classify_regime_from_series
            close_arr = hs300_df["close"].astype(float).values
            regime_meta = _classify_regime_from_series(close_arr)
            unified_regime = regime_meta.get("regime", "RANGE")
            print(f"[动量引擎] 统一Regime: {unified_regime} ({regime_meta.get('regime_cn', '')})")
        except Exception as e:
            print(f"[动量引擎] Regime识别失败，使用默认RANGE: {e}")

    # 4. 三层市场环境评估（Layer2 VIX + Layer3 极端风险保留独立运算）
    env = assess_market_environment(hs300_df, etf_data)

    # 5. 统一 Regime 覆盖（只替换分类，保留 VIX/极端风险的仓位约束）
    env["regime"]       = unified_regime
    env["regime_label"] = REGIME_PARAMS.get(unified_regime, REGIME_PARAMS["RANGE"])["label"]
    env["regime_cn"]    = regime_meta.get("regime_cn", "震荡")
    env["regime_icon"]  = regime_meta.get("regime_icon", "🟡")

    # 6. CRASH 熔断 + 极端风险 → 直接空仓
    if unified_regime == "CRASH" or env["layer3_crash"]:
        print("[动量引擎] ! CRASH/极端风险 ! 空仓避险")
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

    # 7. 信号生成
    result = generate_signals(etf_data, env)

    print(f"[动量引擎] 完成: {result['market_overview']['total_etfs']}只有信号, "
          f"{len(result['errors'])}只异常")
    print(f"[动量引擎] Regime:{unified_regime} "
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
    print("正在运行行业动量轮动策略 V2.0...")
    result = run_momentum_strategy()
    print(json.dumps(result, ensure_ascii=False, indent=2))

