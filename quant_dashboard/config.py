"""
AlphaCore · 全局配置中心
========================
V5.0: 将所有引擎中的分散常量统一管理
使用方式:
    from config import TUSHARE_TOKEN, CACHE_TTL_INTRADAY
"""

# ── Tushare API ──
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"

# ── 数据缓存 TTL ──
CACHE_TTL_INTRADAY    = 300       # 盘中5分钟（09:30-15:00 工作日）
CACHE_TTL_AFTERHOURS  = 3600      # 盘后1小时
CACHE_TTL_WEEKEND     = 86400     # 周末24小时

# ── Regime 判断参数（统一算法：_classify_regime_from_series）──
REGIME_MA_PERIOD   = 120     # MA120 作为趋势锚定
REGIME_SLOPE_DAYS  = 5       # 计算 MA120 斜率的周期
REGIME_RET20_BULL  = 0.05    # 20日涨幅 > 5% → BULL 倾向
REGIME_DIP_THRESH  = -0.03   # 3日 < -3% → CRASH 检测阈值
REGIME_MIN_DATA    = 300     # 最少需要 300 个交易日数据

# ── 各 Regime 仓位上限（均值回归策略）──
MR_POS_CAP = {
    "BEAR":  0.65,
    "RANGE": 0.80,
    "BULL":  0.35,
    "CRASH": 0.00,
}

# ── 信号评分入场门槛（100分制）──
MR_SCORE_GATE = {
    "BEAR":  78,
    "RANGE": 68,
    "BULL":  60,
    "CRASH": 999,
}

# ── 止损幅度（负数，浮亏超过该值触发）──
MR_STOP_LOSS = {
    "BEAR":  -0.05,   # 熊市：浮亏 5% 止损
    "RANGE": -0.07,   # 震荡：浮亏 7% 止损
    "BULL":  -0.06,   # 牛市：浮亏 6% 止损
    "CRASH": -0.03,   # CRASH：浮亏 3% 即止
}

# ── 动量轮动策略参数 ──
MOMENTUM_LOOKBACK   = 20      # N日动量回看期
MOMENTUM_VOL_MIN    = 0.8     # 量比最低要求
MOMENTUM_GROUP_CAP  = 40      # 单行业组仓位上限 (%)
MOMENTUM_MIN_HOLD   = 3       # 最少持仓数量

# ── 前端 API ──
API_BASE_URL = "http://127.0.0.1:8000"

# ── mr_per_regime_params.json 路径 ──
MR_PARAMS_FILE = "mr_per_regime_params.json"

# ── 自动重优化周期（天）──
MR_REOPTIMIZE_DAYS = 60
