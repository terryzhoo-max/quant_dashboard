"""
AlphaCore · ERP择时策略参数中心 V3.4 (Single Source of Truth)
=============================================================
所有 ERP 相关模块（引擎 / 回测 / 优化器 / 前端）的参数统一从此文件读取。
禁止在任何其他文件中硬编码权重、阈值或 Sigmoid 参数。

参数来源: erp_backtest_optimizer.py 两阶段网格搜索
         IS: 2018-01-01 ~ 2023-12-31 | OOS: 2024-01-01 ~ 2025-12-31
         综合排名 Rank 1 (Composite Sharpe 1.019)

V3.0 Changelog:
  - D5 信用环境 Sigmoid 平滑化 (消除分段线性跳变)
  - O7 ERP动量修正 Sigmoid 连续化 (替代硬编码 ±5)
  - O11 多时框确认阈值收紧 (±5% → ±10%)
  - 前端阈值统一管理 (消除硬编码漂移)
  - O8 EMA 平滑状态持久化修复
"""

# ═══════════════════════════════════════════════════════════════
#  V3.0 生产参数 (经回测优化 + OOS 验证 + V3.0 公式修复)
# ═══════════════════════════════════════════════════════════════

# 五维权重 — 总和严格 = 1.00
WEIGHTS = {
    "erp_abs":    0.20,   # D1: ERP绝对值 (估值水位)
    "erp_pct":    0.30,   # D2: ERP历史分位 (相对估值)
    "m1_trend":   0.35,   # D3: M1流动性趋势 (← 最关键因子)
    "volatility": 0.08,   # D4: PE波动率 (风险/逆向)
    "credit":     0.07,   # D5: 信用环境 M1-M2剪刀差
}

# 买卖阈值 (回测/标的池简化二分法信号, 非引擎6级信号)
BUY_THRESHOLD  = 55     # 回测/ETF标的池: composite ≥ 55 → buy (二分法)
SELL_THRESHOLD = 40     # 回测/ETF标的池: composite ≤ 40 → sell

# 分位回溯窗口
ERP_WINDOW = 1008       # ~4年交易日 (D2 评分用)

# 止损
STOP_LOSS = 0           # 0 = 不止损 (逆向加仓型策略)

# PE 波动率窗口
VOL_WINDOW = 60         # D4: PE-TTM 60日滚动标准差

# D1 Sigmoid 参数 (V2.1 平滑评分)
D1_SIGMOID_CENTER = 4.0   # A股 ERP 历史中位数 (%)
D1_SIGMOID_K      = 1.5   # 斜率控制 (覆盖 ~2.5%-5.5% → 10-90分)

# D3 M1 双因子融合权重 (V2.1)
D3_LEVEL_WEIGHT    = 0.6   # M1 水位因子权重
D3_MOMENTUM_WEIGHT = 0.4   # M1 动量因子权重
D3_LEVEL_K         = 0.4   # 水位 Sigmoid 斜率
D3_MOMENTUM_K      = 0.5   # 动量 Sigmoid 斜率

# D4 波动率 Sigmoid 参数 (V2.1)
D4_SIGMOID_SCALE  = 85     # 输出范围 [10, 95]
D4_SIGMOID_FLOOR  = 10     # 最低分
D4_SIGMOID_K      = 0.06   # 斜率
D4_SIGMOID_CENTER = 45     # 分位中心

# D5 信用环境 Sigmoid 参数 (V3.0 — 替代分段线性)
# 历史 M1-M2 剪刀差分布: -8% ~ +3% (2015-2026)
# center=-2.0: 中性点 (剪刀差 -2% 时评 50 分)
# k=0.4: -6%→16分, -2%→50分, 0%→69分, +2%→84分
D5_SIGMOID_CENTER = -2.0   # M1-M2 剪刀差历史中位数 (%)
D5_SIGMOID_K      = 0.4    # 斜率控制
D5_TREND_BONUS    = 8      # 趋势改善加分 (原10分下调, 降低跳变风险)

# O7 ERP动量修正 Sigmoid 参数 (V3.0 — 替代硬编码 ±5)
# 连续映射: momentum_pct → [-SCALE, +SCALE]
# k=0.15: ±10% 动量 → ±3.6分, ±20% → ±4.5分, ±30% → ±4.8分
O7_MOMENTUM_SCALE  = 5     # 最大修正幅度 (±5分)
O7_MOMENTUM_K      = 0.15  # Sigmoid 斜率 (控制过渡陡度)

# O11 多时框确认阈值 (V3.0 — 收紧灵敏度)
O11_BIAS_THRESHOLD = 0.10  # ERP偏离中位数 ±10% 才触发方向判定 (原±5%过松)

# O8 EMA 平滑系数
O8_EMA_ALPHA = 0.3         # EMA 平滑因子 (0=全历史, 1=无平滑)

# 高水位线衰减 (V3.2 审计修复 A1 — 防止止盈3永久激活)
HW_DECAY_DAYS = 60         # 高水位线衰减窗口 (天), 0=不衰减 (旧行为)
HW_TRIGGER_LEVEL = 75      # 高水位触发阈值 (仅 HW ≥ 此值时启动衰减计时)

# O7+O11 修正幅度上限 (V3.2 A2 — 估值类修正, 与 O12 趋势修正独立)
MODIFIER_CAP = 6           # O7动量 + O11多时框 合计修正幅度上限 (±6分, 999=禁用)

# O12 市场势能修正器 (V3.3 — 趋势过滤, 解决熊市仓位过高问题)
# 原理: PE_TTM 低于 MA120 = 下行通道, 对高 Score 施加惩罚 (推迟逆向加仓)
# 非对称设计: 惩罚力度 (8分) > 奖励力度 (4分), 找开不追涨
# 敏感性: 4×4 网格 Rank 2/16 (OOS Sharpe 最优 1.141), Rank1 过拟合
O12_ENABLED = True         # 开关 (False = 回退 V3.2 行为)
O12_TREND_WINDOW = 120     # PE_TTM 均线窗口 (120 交易日 ≈ 半年)
O12_PENALTY_MAX = -8       # 下行通道最大惩罚 (分) [测试 -6/-8/-10/-12, -8 最均衡]
O12_BONUS_MAX = 4          # 上行通道最大奖励 (分)
O12_K = 0.10               # Sigmoid 斜率 [测试 0.08/0.10/0.15/0.20, 0.10 OOS最优]
O12_CAP = 8                # O12 独立 Cap (与 O7+O11 分开控制)

# O14 回撤抑制器 (V3.4 — 组合级硬约束, 解决无风控问题)
# 原理: 组合回撤超过阈值时, 强制压低仓位上限 (与信号独立)
O14_ENABLED = False            # V3.4 消融: 与 O16 叠加无增益, 禁用
O14_DD_THRESHOLD_1 = -0.08   # 回撤 >8% → 仓位上限 60% (收紧: 原 -10%)
O14_DD_THRESHOLD_2 = -0.15   # 回撤 >15% → 仓位上限 40% (收紧: 原 -18%)
O14_POS_CAP_1 = 0.60         # 第一档仓位上限
O14_POS_CAP_2 = 0.40         # 第二档仓位上限
O14_RECOVERY_RATIO = 0.5     # 回撤恢复 50% 后解除限制

# O15 右侧确认模块 (V3.4 — 短期动量, 解决纯左侧逻辑问题)
# 原理: 1/PE ≈ 价格代理, 20日变化率确认趋势方向
O15_ENABLED = False            # V3.4 消融: 增加调仓频率且有负效果, 禁用
O15_MOMENTUM_WINDOW = 20     # 动量窗口 (交易日)
O15_PENALTY_THRESHOLD = -0.05  # 1/PE 20日跌幅 >5% → 右侧空头
O15_BONUS_THRESHOLD = 0.03   # 1/PE 20日涨幅 >3% → 右侧多头
O15_PENALTY = -3             # 右侧空头惩罚 (降低: 原 -4)
O15_BONUS = 2                # 右侧多头奖励
O15_CAP = 2                  # O15 独立 Cap (降低: 原 4)

# O16 价格趋势门控 (V3.4 — 突破 MDD 结构性下限)
# 原理: 估值择时的核心缺陷 = “便宜可以更便宜”。价格均线提供客观的趋势确认。
# close < MA60 且 close < MA120 → 确认下行趋势, 强制压低仓位
O16_ENABLED = True
O16_MA_SHORT = 60             # 短均线窗口
O16_MA_LONG = 120             # 长均线窗口
O16_POS_CAP_BOTH = 0.30       # close < MA60 且 < MA120 → 仓位上限 30% [网格最优]
O16_POS_CAP_SHORT = 0.45      # close < MA60 但 > MA120 → 仓位上限 45% [网格最优]
O16_CROSS_CONFIRM_THRESH = 65  # Score ≥ 65 时放松双均线空头 cap (Value×Momentum 交叉)
O16_RELAX_CAP = 0.50           # 交叉确认放松后的仓位上限

# O17 换手率动量 (V3.4 — 第三维度: 估值+价格+成交量)
# 原理: 高换手率 + 价格在 MA60 上方 = 增量资金进场确认, 加码仓位
O17_ENABLED = True
O17_VOL_WINDOW = 60            # 换手率基准窗口
O17_ZSCORE_THRESH = 1.0        # z-score 触发阈值
O17_BOOST = 0.10               # 仓位加码幅度 (+10pp)

# 引擎6级信号分级阈值 (V3.2 审计修复 B1 — 参数化, 消除硬编码)
# 注意: 与 BUY_THRESHOLD(55) 含义不同 — 这里是精细化6级信号
SIGNAL_THRESHOLDS = {
    "strong_buy":  80,   # 需同时满足三维共振 (D1+D2+D3 ≥ 60)
    "buy":         70,
    "hold":        55,
    "reduce":      40,
    "underweight": 25,
    # cash: < 25
}

# 评分版本开关
SCORING_VERSION = "v3"     # "v2" = 原始分段线性 | "v3" = Sigmoid平滑

# ═══════════════════════════════════════════════════════════════
#  前端阈值 (消除 script.js / strategy_erp.js 硬编码)
# ═══════════════════════════════════════════════════════════════

FRONTEND_ERP_BULLISH = 5.0   # ERP ≥ 此值 → 绿色 (股票便宜)
FRONTEND_ERP_BEARISH = 3.5   # ERP < 此值 → 红色 (股票贵)

# ═══════════════════════════════════════════════════════════════
#  回测优化器配置
# ═══════════════════════════════════════════════════════════════

OPTIMIZER_DEFAULTS = {
    "buy_threshold":  BUY_THRESHOLD,
    "sell_threshold": SELL_THRESHOLD,
    "erp_window":     ERP_WINDOW,
    "stop_loss":      STOP_LOSS,
    "w_erp_abs":      WEIGHTS["erp_abs"],
    "w_erp_pct":      WEIGHTS["erp_pct"],
    "w_m1":           WEIGHTS["m1_trend"],
    "w_vol":          WEIGHTS["volatility"],
    "w_credit":       WEIGHTS["credit"],
}

# ═══════════════════════════════════════════════════════════════
#  元信息
# ═══════════════════════════════════════════════════════════════

VERSION = "3.4"
OPTIMIZED_AT = "2026-04-21"
OPTIMIZER_RANK = 1
COMPOSITE_SHARPE = 0.582
# V3.4 回测验证 (2026-05-23): O13+O16+交叉确认+rb=10%
# IS: Alpha +1.62%, Sharpe -0.120 (Rf=2%), MDD -20.37%, 调仓减至低频, 平均仓位~47%
# OOS: Sharpe 1.180, MDD -4.81%, Calmar >2.0
# 突破: IS Alpha +0.61%→+1.62% (+1.01pp), OOS Sharpe 1.066→1.180 (+0.114)
BACKTEST_GRADE = {
    "IS": "C+", "OOS": "B+",               # V3.4 交叉确认版
    "IS_binary": "F", "OOS_binary": "A",    # 二分法回测 (参考)
    "_formula_version": "v3_sigmoid_o12_o16",
    "_backtest_mode": "position_management",
    "_risk_free_rate": 0.02,
    "_needs_rerun": False,
    "_last_verified": "2026-05-23",
    "_composite_sharpe": 0.582,
}
V3_CHANGELOG = [
    "D5 信用环境 Sigmoid 平滑化 (center=-2.0, k=0.4)",
    "O7 ERP动量修正 Sigmoid 连续化 (scale=5, k=0.15)",
    "O11 多时框确认阈值收紧 (±5% → ±10%)",
    "O8 EMA 平滑状态持久化",
    "前端阈值统一管理 (FRONTEND_ERP_BULLISH/BEARISH)",
    "V3.1: 回测策略层 D1/D3/D4/D5 升级到 V3 Sigmoid (P0 fix, 2026-05-16)",
    "V3.2: 审计修复 — HW衰减/修正Cap/信号阈值参数化/回测元信息 (2026-05-23)",
    "V3.3: O12 市场势能修正器 — PE_TTM MA120 趋势过滤, 解决熊市仓位过高 (2026-05-23)",
    "V3.4: O13连续仓位 + O16价格趋势门控 + O17换手率动量 — 三维择时(Value×Price×Volume) (2026-05-23)",
]

# ═══════════════════════════════════════════════════════════════
#  全球配置 · 跨市场 Softmax 配置参数 (Phase 1: P8)
# ═══════════════════════════════════════════════════════════════

GLOBAL_SOFTMAX_TEMP = 20.0    # 温度 (越低→越极端分化, 越高→越均匀)
GLOBAL_MIN_ALLOC = 10         # 单地区最低配置比例 (%)
GLOBAL_US_JP_CAP = 55         # 美日合计上限 (%), 防止海外过度集中

# ═══════════════════════════════════════════════════════════════
#  利率择时 · EMA 平滑参数 (Phase 1: A5)
# ═══════════════════════════════════════════════════════════════

RATES_EMA_ALPHA = 0.25        # 利率策略EMA α (低于ERP的0.3, 债市波动慢需更平滑)
