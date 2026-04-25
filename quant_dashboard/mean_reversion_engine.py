"""
AlphaCore · 均值回归 V4.2 自适应参数引擎
==========================================
特性：
- 按实时 Regime 动态加载三套专属参数
- 无需重启服务器（读取 mr_per_regime_params.json）
- BULL 状态：均值回归仓位上限 35%，超跌补仓逻辑
- 60天自动重优化检测
- V4.2 新增：RSI动量方向（Δ RSI₅）+ K线形态识别（7维度100分制）
"""

import pandas as pd
import numpy as np
import tushare as ts
import json
import os
import time
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            x = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if x == retries:
                        raise
                    time.sleep(backoff_in_seconds * (2 ** x))
                    x += 1
        return wrapper
    return decorator

from config import TUSHARE_TOKEN
DAILY_PRICE_DIR = "data_lake/daily_prices"
PARAMS_FILE     = "mr_per_regime_params.json"

# 默认回退参数（若 JSON 不存在）
# stop_loss：正数表示止损幅度，如 0.05 = 浮亏 > 5% 触发止损（V4.3统一正数约定）
FALLBACK_PARAMS = {
    "BEAR":  {"N_trend": 40, "rsi_period": 14, "rsi_buy": 45, "rsi_sell": 65, "bias_buy": -3.0, "stop_loss": 0.05},
    "RANGE": {"N_trend": 90, "rsi_period": 14, "rsi_buy": 40, "rsi_sell": 70, "bias_buy": -2.0, "stop_loss": 0.07},
    "BULL":  {"N_trend": 120,"rsi_period": 14, "rsi_buy": 45, "rsi_sell": 75, "bias_buy": -1.5, "stop_loss": 0.06},
}

# 各态仓位上限
REGIME_POS_CAP = {
    "BEAR":  0.65,   # 熊市：均值回归主战，65%
    "RANGE": 0.80,   # 震荡：全力均值回归，80%
    "BULL":  0.35,   # 牛市：超跌补仓逻辑，35%（防止过度交易）
    "CRASH": 0.00,   # 崩盘：完全禁入
}

# 信号评分入场门槛（100分制·按 Regime 自适应）
REGIME_SCORE_GATE = {
    "BEAR":  78,    # 熊市严格（防接飞刀）
    "RANGE": 68,    # 震荡标准
    "BULL":  60,    # 牛市宽松（回调即机会）
    "CRASH": 999,   # CRASH 禁入
}

MR_POOL = [
    {"code": "510500.SH", "name": "中证500ETF",      "max_pos": 15, "defensive": False},
    {"code": "512100.SH", "name": "中证1000ETF",     "max_pos": 15, "defensive": False},
    {"code": "510300.SH", "name": "沪深300ETF",      "max_pos": 15, "defensive": True},
    {"code": "159915.SZ", "name": "创业板ETF",        "max_pos": 10, "defensive": False},
    {"code": "159949.SZ", "name": "创业板50ETF",      "max_pos": 10, "defensive": False},
    {"code": "588000.SH", "name": "科创50ETF",        "max_pos": 10, "defensive": False},
    {"code": "159781.SZ", "name": "科创创业ETF",      "max_pos": 8,  "defensive": False},
    {"code": "512480.SH", "name": "半导体ETF",        "max_pos": 8,  "defensive": False},
    {"code": "588200.SH", "name": "科创芯片ETF",      "max_pos": 7,  "defensive": False},
    {"code": "159995.SZ", "name": "芯片ETF",          "max_pos": 7,  "defensive": False},
    {"code": "159516.SZ", "name": "半导体设备ETF",    "max_pos": 6,  "defensive": False},
    {"code": "588220.SH", "name": "科创100ETF",       "max_pos": 8,  "defensive": False},
    {"code": "515000.SH", "name": "科技ETF",          "max_pos": 6,  "defensive": False},
    {"code": "515070.SH", "name": "人工智能AIETF",    "max_pos": 6,  "defensive": False},
    {"code": "159819.SZ", "name": "人工智能ETF",      "max_pos": 6,  "defensive": False},
    {"code": "515880.SH", "name": "通信ETF",          "max_pos": 6,  "defensive": False},
    {"code": "562500.SH", "name": "机器人ETF",        "max_pos": 5,  "defensive": False},
    {"code": "512400.SH", "name": "有色金属ETF",      "max_pos": 6,  "defensive": False},
    {"code": "516160.SH", "name": "新能源ETF",        "max_pos": 7,  "defensive": False},
    {"code": "515790.SH", "name": "光伏ETF",          "max_pos": 7,  "defensive": False},
    {"code": "562550.SH", "name": "绿电ETF",          "max_pos": 5,  "defensive": False},
    {"code": "159870.SZ", "name": "化工ETF",          "max_pos": 5,  "defensive": False},
    {"code": "512560.SH", "name": "军工ETF",          "max_pos": 7,  "defensive": True},
    {"code": "159218.SZ", "name": "卫星ETF",          "max_pos": 5,  "defensive": False},
    {"code": "159326.SZ", "name": "电网设备ETF",      "max_pos": 5,  "defensive": True},
    {"code": "159869.SZ", "name": "游戏ETF",          "max_pos": 5,  "defensive": False},
    {"code": "159851.SZ", "name": "金融科技ETF",      "max_pos": 5,  "defensive": False},
    {"code": "159941.SZ", "name": "纳指ETF",          "max_pos": 8,  "defensive": True},
    {"code": "513500.SH", "name": "标普500ETF",       "max_pos": 8,  "defensive": True},
    {"code": "515100.SH", "name": "红利低波100ETF",   "max_pos": 5,  "defensive": True},
    {"code": "159545.SZ", "name": "恒生红利低波ETF",  "max_pos": 5,  "defensive": True},
    {"code": "513130.SH", "name": "恒生科技ETF",      "max_pos": 5,  "defensive": False},
    {"code": "513970.SH", "name": "恒生消费ETF",      "max_pos": 5,  "defensive": False},
    {"code": "513090.SH", "name": "香港证券ETF",      "max_pos": 5,  "defensive": False},
    {"code": "513120.SH", "name": "港股创新药ETF",    "max_pos": 5,  "defensive": False},
]


# ─── 动态参数加载（运行时，无需重启） ─────────────────────────────────────────

def load_regime_params(regime: str = None) -> dict:
    """
    从 mr_per_regime_params.json 读取指定 Regime 的最优参数。
    文件更新后无需重启服务器——每次调用都重新读文件。
    若文件不存在，返回内置默认参数。
    """
    if not os.path.exists(PARAMS_FILE):
        return FALLBACK_PARAMS.get(regime or "RANGE", FALLBACK_PARAMS["RANGE"])
    try:
        with open(PARAMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if regime:
            reg_data = data.get("regimes", {}).get(regime, {})
            return reg_data.get("params", FALLBACK_PARAMS.get(regime, FALLBACK_PARAMS["RANGE"]))
        return data
    except Exception as e:
        print(f"[WARN] 读取参数文件失败：{e}，使用默认参数")
        return FALLBACK_PARAMS.get(regime or "RANGE", FALLBACK_PARAMS["RANGE"])


def needs_reoptimize() -> bool:
    """检查是否超过60天未重优化"""
    if not os.path.exists(PARAMS_FILE):
        return True
    try:
        with open(PARAMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        next_date = pd.to_datetime(data.get("next_optimize_after", "2000-01-01"))
        return pd.Timestamp.now() >= next_date
    except:
        return True


def get_all_regime_params() -> dict:
    """返回三态完整参数摘要（供API和前端使用）"""
    if not os.path.exists(PARAMS_FILE):
        return {
            "BEAR":  {"params": FALLBACK_PARAMS["BEAR"],  "optimized_at": "N/A", "score": 0},
            "RANGE": {"params": FALLBACK_PARAMS["RANGE"], "optimized_at": "N/A", "score": 0},
            "BULL":  {"params": FALLBACK_PARAMS["BULL"],  "optimized_at": "N/A", "score": 0},
        }
    try:
        with open(PARAMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            r: {
                "params":       v.get("params", {}),
                "desc":         v.get("desc", ""),
                "optimized_at": v.get("optimized_at", "N/A"),
                "combined_score": v.get("combined_score", 0),
                "train_alpha":  v.get("train_kpi", {}).get("alpha"),
                "valid_alpha":  v.get("valid_kpi", {}).get("alpha"),
                "pos_cap":      REGIME_POS_CAP.get(r, 0.65),
                "score_gate":   REGIME_SCORE_GATE.get(r, 68),
            }
            for r, v in data.get("regimes", {}).items()
        }
    except:
        return {}


# ─── 市场状态识别（统一算法，与信号评分系统保持一致） ────────────────────────

def _classify_regime_from_series(close_arr) -> dict:
    """
    统一 Regime 分类算法（所有模块公用）：
      - CRASH: 3日跌幅 > 7%
      - BULL:  close > MA120 AND slope5 > 0 AND ret20 > 0%
      - RANGE: close > MA120（均线走平）OR（close < MA120 AND ret5 > +3%，超跌反弹）
      - BEAR:  close < MA120 AND ret5 <= 3%
    """
    import numpy as np
    close = np.array(close_arr, dtype=float)
    n = len(close)

    # CRASH 检测
    ret3 = (close[-1] / close[-4] - 1) if n >= 4 else 0
    if ret3 < -0.07:
        return {"regime": "CRASH", "regime_cn": "崩盘警戒",
                "regime_color": "#ef4444", "regime_icon": "🚨"}

    ma120 = close[-120:].mean() if n >= 120 else close.mean()
    ma60  = close[-60:].mean()  if n >= 60  else close.mean()
    ma120_s = np.array([close[max(0,i-119):i+1].mean() for i in range(max(0,n-6), n)])
    slope5 = float(np.polyfit(np.arange(len(ma120_s), dtype=float), ma120_s, 1)[0]) \
             if len(ma120_s) >= 2 else 0.0
    ret5  = float((close[-1] / close[-6]  - 1) * 100) if n >= 6  else 0.0
    ret20 = float((close[-1] / close[-21] - 1) * 100) if n >= 21 else 0.0
    cur   = float(close[-1])
    above = cur > ma120

    if above and slope5 > 0 and ret20 > 0:
        regime, regime_cn, rc, ri = "BULL",  "牛市",    "#10b981", "🟢"
    elif above:
        regime, regime_cn, rc, ri = "RANGE", "震荡市",  "#fbbf24", "🟡"
    elif not above and ret5 > 3:
        regime, regime_cn, rc, ri = "RANGE", "震荡反弹","#fb923c", "🟠"
    else:
        regime, regime_cn, rc, ri = "BEAR",  "熊市",    "#ef4444", "🔴"

    return {
        "regime":       regime,
        "regime_cn":    regime_cn,
        "regime_color": rc,
        "regime_icon":  ri,
        "ma60":         round(float(ma60), 2),
        "ma120":        round(float(ma120), 2),
        "slope5":       round(float(slope5), 4),
        "ret5":         round(float(ret5), 2),
        "ret20":        round(float(ret20), 2),
        "above_ma120":  bool(above),   # ← 强制转为 Python bool，避免 numpy.bool_ 序列化失败
    }


@retry_with_backoff(retries=3, backoff_in_seconds=2)
def detect_regime() -> dict:
    """
    实时识别市场状态（CSI300 指数，000300.SH）
    使用统一三重条件算法，与信号评分系统 /api/v1/market/regime 完全一致。
    加入了指数退避重试，防止网络抖动导致的误判。
    返回：{"regime": ..., "params": {...}, "pos_cap": ..., "score_gate": ...}
    """
    try:
        pro = ts.pro_api(token=TUSHARE_TOKEN)

        end_dt   = datetime.now().strftime("%Y%m%d")
        start_dt = (datetime.now() - pd.Timedelta(days=300)).strftime("%Y%m%d")

        df = pro.index_daily(ts_code="000300.SH", start_date=start_dt, end_date=end_dt,
                             fields="trade_date,close,pct_chg")
        if df is None or df.empty:
            raise ValueError("000300.SH 数据为空")

        df = df.sort_values("trade_date").reset_index(drop=True)
        close_arr = df["close"].astype(float).values

        info    = _classify_regime_from_series(close_arr)
        regime  = info["regime"]
        params  = load_regime_params(regime)
        pos_cap = REGIME_POS_CAP.get(regime, 0.65)
        score_gate = REGIME_SCORE_GATE.get(regime, 68)

        return {
            "regime":      regime,
            "regime_cn":   info["regime_cn"],
            "regime_color": info["regime_color"],
            "regime_icon": info["regime_icon"],
            "params":      params,
            "pos_cap":     pos_cap,
            "score_gate":  score_gate,
            "csi300":      round(float(close_arr[-1]), 2),
            "ma120":       info["ma120"],
            "ma60":        info["ma60"],
            "slope5":      info["slope5"],
            "ret5":        info["ret5"],
            "ret20":       info["ret20"],
            "above_ma120": info["above_ma120"],
            "needs_reoptimize": needs_reoptimize(),
        }
    except Exception as e:
        return {
            "regime":     "RANGE",
            "regime_cn":  "震荡市",
            "params":     FALLBACK_PARAMS["RANGE"],
            "pos_cap":    0.70,
            "score_gate": 68,
            "error":      str(e),
        }



# ─── 核心策略计算 ─────────────────────────────────────────────────────────────

def calculate_indicators(df: pd.DataFrame, regime_info: dict = None) -> dict:
    close  = df["close"]
    volume = df["vol"] if "vol" in df.columns else df["volume"]

    # V4.2: regime_info 可外部注入，避免循环内重复调用 API
    if regime_info is None:
        regime_info = detect_regime()
    p = regime_info["params"]
    N = p.get("N_trend", 90)
    rsi_p = p.get("rsi_period", 14)

    ma20 = close.rolling(20).mean()
    ma_n = close.rolling(N).mean()   # 趋势均线（Regime专属）
    boll_std   = close.rolling(20).std()
    boll_upper = ma20 + 2 * boll_std
    boll_lower = ma20 - 2 * boll_std
    boll_diff  = boll_upper - boll_lower
    
    # 修复除零错误：当波动为 0 时，boll_diff可能为0甚至NaN
    percent_b  = np.where(
        boll_diff > 1e-6,
        (close - boll_lower) / np.where(boll_diff > 1e-6, boll_diff, 1e-6),
        0.5
    )

    # RSI（Wilder 平滑，用 Regime 指定周期）
    delta    = close.diff(1)
    gain     = delta.where(delta > 0, 0.0)
    loss     = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=rsi_p, min_periods=rsi_p, adjust=False).mean()
    avg_loss = loss.ewm(span=rsi_p, min_periods=rsi_p, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, 0.001)
    rsi      = 100 - (100 / (1 + rs))

    # 保留 RSI(3) 辅助展示
    avg_g3 = gain.rolling(3).mean()
    avg_l3 = loss.rolling(3).mean()
    rsi_3  = 100 - (100 / (1 + avg_g3 / avg_l3.replace(0, 0.001)))

    # BIAS 相对趋势均线
    bias      = (close - ma_n) / ma_n * 100
    deviation = ((close - ma20) / ma20).abs() * 100

    vol_ma5   = volume.rolling(5).mean()
    vol_ratio = (volume / vol_ma5.replace(0, 1)).clip(0, 10)

    # V4.2 新增 ①：RSI 5日动量斜率（判断超卖是否开始反转）
    rsi_slope5 = 0.0
    if len(rsi.dropna()) >= 6:
        rsi_slope5 = float(rsi.iloc[-1] - rsi.iloc[-6])

    # V4.2 新增 ②：K线形态识别（锤子线 / 十字星 / 下影线）
    kline_pattern = "neutral"
    kline_score_val = 0
    if "open" in df.columns and "high" in df.columns and "low" in df.columns:
        lw = df.iloc[-1]
        rng = lw["high"] - lw["low"]
        if rng > 1e-6:
            body_ratio   = abs(lw["open"] - lw["close"]) / rng
            lower_shadow = (min(lw["open"], lw["close"]) - lw["low"]) / rng
            if lower_shadow >= 0.6 and body_ratio <= 0.3:
                kline_pattern = "hammer";    kline_score_val = 5
            elif lower_shadow >= 0.4:
                kline_pattern = "shadow";    kline_score_val = 3
            elif body_ratio <= 0.15:
                kline_pattern = "doji";      kline_score_val = 2

    latest = df.iloc[-1]
    return {
        "close":           float(latest["close"]),
        "ma20":            float(ma20.iloc[-1]) if not ma20.isnull().all() else 0,
        "ma_n":            float(ma_n.iloc[-1]) if not ma_n.isnull().all() else 0,
        "ma60":            float(close.rolling(60).mean().iloc[-1]),
        "boll_upper":      float(boll_upper.iloc[-1]) if not boll_upper.isnull().all() else 0,
        "boll_lower":      float(boll_lower.iloc[-1]) if not boll_lower.isnull().all() else 0,
        "percent_b":       float(percent_b[-1]) if hasattr(percent_b, '__len__') else 0,
        "rsi":             float(rsi.iloc[-1]) if not rsi.isnull().all() else 50,
        "rsi_3":           float(rsi_3.iloc[-1]) if not rsi_3.isnull().all() else 50,
        "rsi_slope5":      round(rsi_slope5, 2),          # V4.2 新增
        "bias":            float(bias.iloc[-1]) if not bias.isnull().all() else 0,
        "deviation":       float(deviation.iloc[-1]) if not deviation.isnull().all() else 0,
        "vol_ratio":       float(vol_ratio.iloc[-1]) if not vol_ratio.isnull().all() else 1,
        "kline_pattern":   kline_pattern,                  # V4.2 新增
        "kline_score":     kline_score_val,                # V4.2 新增
        "regime":          regime_info["regime"],
        "regime_params":   p,
        "pos_cap":         regime_info["pos_cap"],
        "score_gate":      regime_info["score_gate"],
        "needs_reopt":     regime_info.get("needs_reoptimize", False),
    }


def _sigmoid_score(x, center, steepness, max_score):
    """V4.3 通用Sigmoid映射：center=半分位, steepness=斜率（正值=越小x越高分）"""
    return float(max_score / (1 + np.exp(steepness * (x - center))))


def calculate_score(indicators: dict) -> dict:
    """
    V4.3 评分：7维度100分制 · Sigmoid连续映射（消除断崖效应）
    升级：① ~ ⑥ 全部从离散阶梯升级为Sigmoid连续函数
    保留：⑦ K线形态（离散分类本身不适合连续化）
    """
    p = indicators.get("regime_params", FALLBACK_PARAMS["RANGE"])
    rsi_buy_opt  = p.get("rsi_buy", 40)
    bias_buy_opt = p.get("bias_buy", -2.0)

    rsi        = indicators["rsi"]
    bias       = indicators["bias"]
    pb         = indicators["percent_b"]
    vr         = indicators["vol_ratio"]
    close      = indicators["close"]
    ma_n       = indicators["ma_n"]
    rsi_slope5 = indicators.get("rsi_slope5", 0.0)
    kline_sc   = indicators.get("kline_score", 0)

    # ① RSI 超卖深度（0-25）—— Sigmoid：以 rsi_buy_opt+5 为中心，RSI越低分越高
    s1 = _sigmoid_score(rsi, center=rsi_buy_opt + 5, steepness=0.3, max_score=25)

    # ② RSI 动量方向（0-15）—— 反向Sigmoid：slope越大越好（底部反转信号）
    s2 = float(15 / (1 + np.exp(-1.5 * (rsi_slope5 - 1.5))))

    # ③ BIAS 乖离率（0-20）—— Sigmoid：以 bias_buy_opt*0.6 为中心，BIAS越负分越高
    s3 = _sigmoid_score(bias, center=bias_buy_opt * 0.6, steepness=0.8, max_score=20)

    # ④ 布林带 %B（0-15）—— Sigmoid：%B越低分越高
    s4 = _sigmoid_score(pb, center=0.25, steepness=8.0, max_score=15)

    # ⑤ 成交量信号（0-10）—— V型Sigmoid：恐慌放量 OR 绝望缩量都给高分
    s5_high = float(10 / (1 + np.exp(-3.0 * (vr - 1.8))))   # 放量信号
    s5_low  = float(10 / (1 + np.exp(5.0 * (vr - 0.55))))   # 缩量信号
    s5_mid  = 3.0 if 0.8 <= vr <= 1.3 else 0.0               # 平量中性
    s5 = max(s5_high, s5_low, s5_mid)

    # ⑥ 趋势位置（0-10）—— Sigmoid：close vs ma_n 的百分比偏离
    trend_pct = (close / ma_n - 1) * 100 if ma_n > 0 else 0
    s6 = float(10 / (1 + np.exp(-1.5 * (trend_pct + 1))))

    # ⑦ K线形态（0-5）—— 保持离散（形态分类天然离散）
    s7 = min(5, kline_sc)

    total = min(100, round(s1 + s2 + s3 + s4 + s5 + s6 + s7))

    return {
        "total":       total,
        "breakdown": {
            "rsi_depth":   round(s1, 1),   # ① RSI超卖深度
            "rsi_momentum":round(s2, 1),   # ② RSI动量方向
            "bias":        round(s3, 1),   # ③ BIAS乖离率
            "boll":        round(s4, 1),   # ④ 布林带%B
            "volume":      round(s5, 1),   # ⑤ 成交量
            "trend":       round(s6, 1),   # ⑥ 趋势位置
            "kline":       round(s7, 1),   # ⑦ K线形态
        }
    }


def generate_signal(indicators: dict, score: int) -> str:
    """
    V4.3 信号生成 — score 为总分整数，从 Regime 专属参数读取阈值
    升级：trend_ok 按 Regime 差异化宽度 + stop_loss 正负兼容
    """
    p = indicators.get("regime_params", FALLBACK_PARAMS["RANGE"])

    close    = indicators["close"]
    ma20     = indicators["ma20"]
    ma_n     = indicators["ma_n"]
    rsi      = indicators["rsi"]
    bias     = indicators["bias"]
    pb       = indicators["percent_b"]
    regime   = indicators.get("regime", "RANGE")
    score_gate = indicators.get("score_gate", 68)

    rsi_buy  = p["rsi_buy"]
    rsi_sell = p["rsi_sell"]
    bias_buy = p["bias_buy"]
    sl       = abs(p.get("stop_loss", 0.07))   # V4.3: abs() 兼容正负号

    # CRASH：全面禁入
    if regime == "CRASH":
        return "no_entry"
    if regime == "BULL" and score < score_gate:
        return "hold"

    # V4.3: stop_loss 统一用 abs 比较
    cost_price = indicators.get("cost_price")
    if cost_price and cost_price > 0:
        ret = (close / cost_price) - 1
        if ret <= -sl:
            return "stop_loss"

    # V4.3: trend_ok 按 Regime 差异化宽度
    #   BEAR: 允许5%偏离（熊市超跌是主战场，不能过滤掉）
    #   RANGE: 标准（必须站上均线）
    #   BULL: 收紧（必须站上均线2%以上，确认趋势后才做回归）
    if regime == "BEAR":
        trend_ok = close > ma_n * 0.95
    elif regime == "BULL":
        trend_ok = close > ma_n * 1.02
    else:
        trend_ok = close > ma_n

    if trend_ok and (rsi <= rsi_buy or bias <= bias_buy) and score >= score_gate:
        return "buy"

    if rsi >= rsi_sell:
        return "sell"

    if close >= ma20 and pb > 0.6:
        return "sell_half"

    if score < score_gate * 0.75:
        return "sell_weak"

    return "hold"


def _fetch_and_calc_mr(code, regime_info, start_date, end_date, pro):
    """并发拉取与计算单只ETF的原子函数"""
    try:
        cache_file = f"data_lake/daily_prices/{code}.parquet"
        df = None
        # 尝试API获取
        try:
            df = pro.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                df.to_parquet(cache_file) # 缓存
        except Exception as api_e:
            # API失败，尝试本地缓存托底
            if os.path.exists(cache_file):
                df = pd.read_parquet(cache_file)
            else:
                raise ValueError(f"无API数据且无本地缓存: {api_e}")
                
        if df is None or df.empty:
            return {"ts_code": code, "signal": "error", "error": "数据为空"}

        indicators  = calculate_indicators(df, regime_info=regime_info)
        score_dict  = calculate_score(indicators)
        score       = score_dict["total"]
        breakdown   = score_dict["breakdown"]
        signal      = generate_signal(indicators, score)

        name = next((e["name"] for e in MR_POOL if e["code"] == code), code)
        return {
            "ts_code":       code,
            "name":          name,
            "signal":        signal,
            "signal_score":  score,
            "score_breakdown": breakdown,       # V4.2 新增明细
            "rsi":           round(indicators["rsi"], 1),
            "rsi_3":         round(indicators["rsi_3"], 1),
            "rsi_slope5":    round(indicators.get("rsi_slope5", 0), 2),  # V4.2
            "kline_pattern": indicators.get("kline_pattern", "neutral"), # V4.2
            "bias":          round(indicators["bias"], 2),
            "percent_b":     round(indicators["percent_b"], 3),
            "vol_ratio":     round(indicators["vol_ratio"], 2),
            "close":         round(indicators["close"], 3),
            "ma20":          round(indicators["ma20"], 3),
            "ma_n":          round(indicators["ma_n"], 3),
            "regime":        indicators["regime"],
            "regime_params": indicators["regime_params"],
            "pos_cap":       indicators["pos_cap"],
            "score_gate":    indicators["score_gate"],
            "needs_reopt":   indicators["needs_reopt"],
        }
    except Exception as e:
        name = next((e["name"] for e in MR_POOL if e["code"] == code), code)
        return {
            "ts_code": code, "name": name,
            "signal": "error", "signal_score": 0,
            "error": str(e),
        }

def run_strategy(ts_codes: list = None, regime_override: str = None) -> list:
    """主策略入口 — V5.0 并发版本"""
    pro = ts.pro_api(token=TUSHARE_TOKEN)

    pool = ts_codes if ts_codes else [e["code"] for e in MR_POOL]
    results = []
    end_date   = datetime.now().strftime("%Y%m%d")
    start_date = "20230101"

    # V4.2: Regime 只识别一次
    regime_info = detect_regime()

    # V5.0: 使用线程池并发抓取与计算
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_fetch_and_calc_mr, code, regime_info, start_date, end_date, pro) for code in pool]
        for future in as_completed(futures):
            results.append(future.result())

    return sorted(results, key=lambda x: x.get("signal_score", 0), reverse=True)
