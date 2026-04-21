"""
AlphaCore · ERP择时策略参数中心 (Single Source of Truth)
========================================================
所有 ERP 相关模块（引擎 / 回测 / 优化器）的参数统一从此文件读取。
禁止在任何其他文件中硬编码权重或阈值。

参数来源: erp_backtest_optimizer.py 两阶段网格搜索
         IS: 2018-01-01 ~ 2023-12-31 | OOS: 2024-01-01 ~ 2025-12-31
         综合排名 Rank 1 (Composite Sharpe 1.019)
"""

# ═══════════════════════════════════════════════════════════════
#  V2.1 生产参数 (经回测优化 + OOS 验证)
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

# 评分版本开关
SCORING_VERSION = "v3"     # "v2" = 原始分段线性 | "v3" = Sigmoid平滑

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

VERSION = "2.1"
OPTIMIZED_AT = "2026-04-01"
OPTIMIZER_RANK = 1
COMPOSITE_SHARPE = 1.019
BACKTEST_GRADE = {"IS": "D", "OOS": "A"}  # IS 2018-2023, OOS 2024-2025
