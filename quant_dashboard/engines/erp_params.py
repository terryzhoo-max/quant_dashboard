"""
AlphaCore · ERP择时策略参数中心 V3.0 (Single Source of Truth)
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

# 买卖阈值
BUY_THRESHOLD  = 55     # 综合得分 ≥ 55 → 买入信号
SELL_THRESHOLD = 40     # 综合得分 ≤ 40 → 卖出信号

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

VERSION = "3.0"
OPTIMIZED_AT = "2026-04-21"
OPTIMIZER_RANK = 1
COMPOSITE_SHARPE = 1.019
BACKTEST_GRADE = {"IS": "D", "OOS": "A"}  # IS 2018-2023, OOS 2024-2025
V3_CHANGELOG = [
    "D5 信用环境 Sigmoid 平滑化 (center=-2.0, k=0.4)",
    "O7 ERP动量修正 Sigmoid 连续化 (scale=5, k=0.15)",
    "O11 多时框确认阈值收紧 (±5% → ±10%)",
    "O8 EMA 平滑状态持久化",
    "前端阈值统一管理 (FRONTEND_ERP_BULLISH/BEARISH)",
]
