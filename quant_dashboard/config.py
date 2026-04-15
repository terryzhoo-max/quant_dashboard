"""
AlphaCore · 全局配置中心
========================
V5.0: 将所有引擎中的分散常量统一管理
使用方式:
    from config import TUSHARE_TOKEN, CACHE_TTL_INTRADAY
"""

# ── Tushare API ──
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"

# ── FRED API (VIX / 国债收益率 / M1 / 美股宏观) ──
FRED_API_KEY = "eadf412d4f0e8ccd2bb3993b357bdca6"

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

# ═══════════════════════════════════════════════════════
#  审计引擎 V4.0 · 带枪保安架构
# ═══════════════════════════════════════════════════════

# ── 审计阈值 (统一管理，消灭硬编码) ──
AUDIT_CONFIG = {
    # 风控红线 (V5.1: 个股/ETF 差异化止损)
    "stop_loss_stock": -10.0,           # 个股止损红线 (%) — 个股波动大, 容忍度更高
    "stop_loss_etf": -8.0,              # ETF止损红线 (%) — ETF波动小, 纪律更严
    "single_position_limit": 20.0,      # 单票集中度上限 (%) ← 与 PortfolioEngine.POSITION_LIMIT 同步
    "sector_limit": 40.0,               # 行业集中度上限 (%)
    "total_position_cap": 90.0,         # 总仓位上限 (%)
    "min_holdings": 5,                  # 最少持仓数

    # 数据新鲜度阈值
    "daily_stale_warn_days": 3,         # 日线过期 ≤N天 = 警告
    "daily_stale_fail_days": 5,         # 日线过期 >N天 = 失败
    "fina_fresh_days": 90,              # 财务数据新鲜期 (季度更新)
    "erp_stale_warn_days": 3,
    "erp_stale_fail_days": 7,

    # 策略参数新鲜期
    "strategy_fresh_days": 30,          # ≤30天 = 新鲜
    "strategy_stale_days": 60,          # >60天 = 过期
}

# ── 执行器配置 (带枪保安核心) ──
AUDIT_ENFORCER = {
    "enabled": True,                     # 总开关
    "auto_stop_loss": True,              # 止损强制卖出
    "block_trade_on_stale_data": True,   # 数据过期阻止买入
    "stale_data_block_days": 5,          # 阻断阈值 (天)
}

# ── 静音/降级配置 ──
AUDIT_MUTE = {
    "muted_checks": [],                  # 被静音的检查项名称列表
    "degraded_mode": False,              # 降级模式: fail → warn (不触发 enforcer)
    "mute_until": None,                  # 静音到期时间 (ISO格式, 过期自动解除)
}
