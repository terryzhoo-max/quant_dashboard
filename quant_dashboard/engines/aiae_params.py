"""
AlphaCore · AIAE 宏观仓位策略参数中心 (Single Source of Truth)
================================================================
所有 AIAE 相关模块（引擎 / 回测 / 前端）的参数统一从此文件读取。
禁止在任何其他文件中硬编码权重、阈值或归一化区间。

V3.0 优化依据:
  - 历史 8 个关键节点 (2005-2026) 100% 命中率验证
  - 基金仓位/融资热度归一化区间基于 2019-2026 实际分布重标定
  - Sigmoid 归一化与 ERP 引擎 V2.1 评分体系对齐
"""

import math

# ═══════════════════════════════════════════════════════════════
#  V3.0 核心公式参数
# ═══════════════════════════════════════════════════════════════

# ──── 三维融合权重 (总和严格 = 1.00) ────
# 原始 V2.0: [0.50, 0.30, 0.20]
# V3.0 优化: 降低季频基金仓位权重 (0.30→0.20)，提升日频融资热度 (0.20→0.25)
W_AIAE_SIMPLE  = 0.55   # AIAE_简 (月频M2 + 日频市值) — 核心信号，历史验证最强
W_FUND_POS     = 0.20   # 基金仓位 (季频手动) — 滞后因子，降权
W_MARGIN_HEAT  = 0.25   # 融资热度 (日频自动) — 唯一高频因子，升权

assert abs(W_AIAE_SIMPLE + W_FUND_POS + W_MARGIN_HEAT - 1.0) < 1e-9, \
    f"三维权重总和 ≠ 1.0: {W_AIAE_SIMPLE + W_FUND_POS + W_MARGIN_HEAT}"

# ──── 基金仓位 Sigmoid 归一化参数 ────
# 历史实际分布: 68-92% (2019-2026 偏股型基金)
# 旧区间 60-95% 过宽，底部/顶部区分能力丧失
FUND_SIGMOID_CENTER = 80.0   # 偏股基金仓位中位数 (%)
FUND_SIGMOID_K      = 0.15   # 斜率: 68%→11.4 AIAE等效, 80%→20.0, 92%→28.6
# 有效贡献区间: W_FUND_POS × [sigmoid(68%), sigmoid(92%)] = [2.28, 5.72] AIAE pt
# 即基金仓位从极低(68%)到极高(92%)对 AIAE_V1 的影响幅度 ≈ 3.4pt

# ──── 融资热度 Sigmoid 归一化参数 ────
# 历史实际分布: 1.2-3.5% (2019-2026, 杠杆监管趋严后)
# 旧区间 1-4% 上限几乎触不到，顶部信号钝化
MARGIN_SIGMOID_CENTER = 2.2  # 融资占比中位数 (%)
MARGIN_SIGMOID_K      = 2.5  # 斜率: 1.2%→9.8 AIAE等效, 2.2%→20.0, 3.5%→31.1
# 有效贡献区间: W_MARGIN_HEAT × [sigmoid(1.2%), sigmoid(3.5%)] = [2.46, 7.78] AIAE pt
# 即融资热度从极低(1.2%)到极高(3.5%)对 AIAE_V1 的影响幅度 ≈ 5.3pt

# ──── 归一化输出区间 ────
NORM_MIN = 8.0    # AIAE 等效最小值 (对应极度恐慌)
NORM_MAX = 32.0   # AIAE 等效最大值 (对应极度过热)

# ═══════════════════════════════════════════════════════════════
#  五档分界线
# ═══════════════════════════════════════════════════════════════

# 原始 V2.0: [12, 16, 24, 32]
# V3.0 优化: 基于历史 AIAE 分位数重划
#   Ⅰ<12.5: 2005(8.2), 2008(10.1) 仍安全落入
#   Ⅱ 12.5-17: V3 Sigmoid 下 2018(V1=12.9%) 保持 Ⅱ级
#   Ⅲ 17-23: 当前估算 22.3% 保持 Ⅲ级
#   Ⅳ 23-30: 2021(28.9) 保持 Ⅳ级
#   Ⅴ>30: 2015(38.7), 2007(42.5) 更早触发清仓
REGIME_THRESHOLDS = [12.5, 17, 23, 30]  # [Ⅰ/Ⅱ, Ⅱ/Ⅲ, Ⅲ/Ⅳ, Ⅳ/Ⅴ]

# 分界线平滑缓冲带 (±BUFFER 内做线性插值, 消除仓位跳变)
# 前提约束: BUFFER < min(相邻分界线间距) / 2, 否则缓冲带重叠
REGIME_SMOOTH_BUFFER = 1.5  # AIAE 百分点

# V3.1: Regime 判定迟滞带 (防止边界微幅波动导致 R3⇌R4 反复跳变)
# 上行跨越需 threshold + H, 下行回落需 threshold - H
REGIME_HYSTERESIS = 0.5  # AIAE 百分点

_min_gap = min(REGIME_THRESHOLDS[i+1] - REGIME_THRESHOLDS[i] for i in range(len(REGIME_THRESHOLDS)-1))
assert REGIME_SMOOTH_BUFFER < _min_gap / 2, \
    f"REGIME_SMOOTH_BUFFER({REGIME_SMOOTH_BUFFER}) 必须 < 最小分界线间距({_min_gap})/2={_min_gap/2}"

# ═══════════════════════════════════════════════════════════════
#  仓位矩阵 (V3.0 微调)
# ═══════════════════════════════════════════════════════════════

# 行: ERP 水位, 列: AIAE 档位 (1-5)
# V3.0: Ⅴ级仓位从 [20,15,10,5] 全面下调至 [15,10,5,0]，强化极端保护
POSITION_MATRIX = {
    "erp_gt6":  [95, 85, 65, 40, 15],  # ERP > 6%
    "erp_4_6":  [90, 80, 60, 35, 10],  # ERP 4-6%
    "erp_2_4":  [85, 70, 50, 25,  5],  # ERP 2-4%
    "erp_lt2":  [75, 55, 35, 15,  0],  # ERP < 2%
}

# ═══════════════════════════════════════════════════════════════
#  子策略配额矩阵
# ═══════════════════════════════════════════════════════════════

SUB_STRATEGY_ALLOC = {
    1: {"mr": 37, "div": 18, "mom": 22, "gem": 10, "erp": 13},  # Ⅰ级: 进攻满配, GEM低配(牛市追强价值最小)
    2: {"mr": 32, "div": 23, "mom": 20, "gem": 12, "erp": 13},  # Ⅱ级: 标准建仓, GEM开始提供战术对冲
    3: {"mr": 22, "div": 26, "mom": 20, "gem": 15, "erp": 17},  # Ⅲ级: 均衡持有, GEM标准配置
    4: {"mr":  8, "div": 42, "mom": 10, "gem": 18, "erp": 22},  # Ⅳ级: 系统减仓, GEM升权(绝对动量过滤价值凸显)
    5: {"mr":  0, "div": 65, "mom":  0, "gem": 15, "erp": 20},  # Ⅴ级: 清仓防守, GEM保留(自动持有现金/黄金)
}

for _regime, _alloc in SUB_STRATEGY_ALLOC.items():
    _row_sum = sum(_alloc.values())
    assert _row_sum == 100, f"SUB_STRATEGY_ALLOC[{_regime}] 行和={_row_sum}, 应为100"

# ═══════════════════════════════════════════════════════════════
#  告警阈值
# ═══════════════════════════════════════════════════════════════

# 融资热度告警
MARGIN_HEAT_WARN   = 3.0    # ≥ 此值显示"偏高"信号
MARGIN_HEAT_DANGER = 3.5    # ≥ 此值显示"散户杠杆"信号
MARGIN_HEAT_LOW    = 1.5    # ≤ 此值显示"杠杆出清"信号

# 斜率告警
SLOPE_ACCEL_UP    = 1.5     # > 此值触发"加速上行"警告
SLOPE_ACCEL_DOWN  = -1.5    # < 此值触发"加速下行"机会

# 市值合理性区间 (万亿)
MV_BOUNDS_MIN = 30.0
MV_BOUNDS_MAX = 300.0

# M2 合理性区间 (万亿)
M2_BOUNDS_MIN = 200.0
M2_BOUNDS_MAX = 600.0

# ═══════════════════════════════════════════════════════════════
#  Sigmoid 工具函数
# ═══════════════════════════════════════════════════════════════

def sigmoid_normalize(value: float, center: float, k: float,
                      out_min: float = NORM_MIN, out_max: float = NORM_MAX) -> float:
    """Sigmoid 平滑归一化
    
    Args:
        value:  输入值 (如基金仓位 80%, 融资热度 2.2%)
        center: 中心值 (输出 50% 分位的锚点)
        k:      斜率 (越大 → 过渡越陡)
        out_min/out_max: 输出区间
    
    Returns:
        归一化后的 AIAE 等效值 [out_min, out_max]
    """
    x = (value - center) * k
    # 防溢出
    x = max(-20, min(20, x))
    sig = 1.0 / (1.0 + math.exp(-x))
    return out_min + (out_max - out_min) * sig


def smooth_position(pos_low: int, pos_high: int, 
                    aiae_value: float, threshold: float, 
                    buffer: float = REGIME_SMOOTH_BUFFER) -> int:
    """分界线平滑插值 (消除仓位跳变)
    
    当 AIAE 值在 [threshold - buffer, threshold + buffer] 内时,
    在 pos_high 和 pos_low 之间线性插值。
    
    Args:
        pos_low:  低档仓位 (AIAE 高 → 仓位低)
        pos_high: 高档仓位 (AIAE 低 → 仓位高)
        aiae_value: 当前 AIAE 值
        threshold:  档位分界线
        buffer:     缓冲带半宽
    
    Returns:
        平滑后的仓位建议 (整数%)
    """
    lower = threshold - buffer
    upper = threshold + buffer
    
    if aiae_value <= lower:
        return pos_high
    elif aiae_value >= upper:
        return pos_low
    else:
        # 线性插值
        ratio = (aiae_value - lower) / (upper - lower)
        return round(pos_high + (pos_low - pos_high) * ratio)


# ═══════════════════════════════════════════════════════════════
#  V5.0 精简双因子模式  (AIAE_简 + ERP)
# ═══════════════════════════════════════════════════════════════
#
# V5 回测验证 (2015-2026, 137个月):
#   V4(3因子): CAGR=2.8% MDD=-9.5% Sharpe=0.17
#   V5(2因子): CAGR=4.4% MDD=-14.4% Sharpe=0.36
#
# 因子归因结论:
#   fund_pos  → +11bps (可忽略)，margin_heat → -46bps (负贡献)
#   ERP       → +33bps (正贡献)
#   决策: 去掉 fund_pos 和 margin 两个无效因子
#
# 阈值标定方法: 137个月 AIAE_简 百分位 P10/P30/P70/P90
#   AIAE_简 实际值域: 21.1% ~ 33.1%，mean=25.4%, std=2.2%

V5_ENABLED = True  # True=使用V5精简模式, False=回退到V3三因子模式

# V5.2 五档阈值 (H1回测优化: 拉宽间距消除噪声换挡)
# 回测对比 (2015-2026, 137月):
#   旧 [22.8, 24.0, 26.5, 28.3] → 换挡31次, R2占16.8%, 仓位波动21.3%
#   新 [22.0, 24.0, 27.0, 29.0] → 换挡25次(-19%), R2占21.9%(+30%), 仓位波动17.2%(-19%)
#   极端事件识别: 6个关键转折点判定完全一致 (无损)
V5_REGIME_THRESHOLDS = [22.0, 24.0, 27.0, 29.0]
#   R1: <22.0% (极度低估, 2018贸战底21.45%/2024-01极低估)
#   R2: 22.0-24.0% (低估, 2020-03疫情23.34%/2024-09政策底24.08%)
#   R3: 24.0-27.0% (中性, 2022-04调整底24.87%)
#   R4: 27.0-29.0% (高估, 2015-07股灾续26.93%)
#   R5: >29.0% (极度高估, 2015-06杠杆牛30.66%/2021-02抱团)

# V5 仓位矩阵 (R1 仓位上限调整为80%，控制 MDD ≤ -12%)
V5_POSITION_MATRIX = {
    "erp_gt6":  [80, 75, 65, 40, 15],  # ERP > 6%  (R1: 95→80)
    "erp_4_6":  [75, 70, 60, 35, 10],  # ERP 4-6%  (R1: 90→75)
    "erp_2_4":  [70, 60, 50, 25,  5],  # ERP 2-4%  (R1: 85→70)
    "erp_lt2":  [60, 50, 35, 15,  0],  # ERP < 2%  (R1: 75→60)
}

# V5.2 迟滞带 (保持0.5, 回测验证方案C最优)
V5_REGIME_HYSTERESIS = 0.5

# V5.2 缓冲带 (min_gap=2.0pt, buffer=0.8 < 2.0/2=1.0 满足约束)
V5_REGIME_SMOOTH_BUFFER = 0.8  # V5.2优化: 间距拉宽后缓冲带可适当加宽，仓位过渡更平滑

_v5_min_gap = min(V5_REGIME_THRESHOLDS[i+1] - V5_REGIME_THRESHOLDS[i]
                  for i in range(len(V5_REGIME_THRESHOLDS)-1))
assert V5_REGIME_SMOOTH_BUFFER < _v5_min_gap / 2, \
    f"V5_REGIME_SMOOTH_BUFFER({V5_REGIME_SMOOTH_BUFFER}) 必须 < 最小间距({_v5_min_gap})/2"


# ═══════════════════════════════════════════════════════════════
#  元信息
# ═══════════════════════════════════════════════════════════════

VERSION = "5.2"
OPTIMIZED_AT = "2026-06-01"
OPTIMIZATION_NOTES = [
    "V3→V5: 基于因子归因去掉 fund_pos(-46bps) 和 margin_heat(+11bps)",
    "V5 使用 AIAE_简 直接百分位分档 + ERP 交叉矩阵",
    "V5.0 阈值: [22.8, 24.0, 26.5, 28.3] (P10/P30/P70/P90)",
    "V5.2 H1优化: 阈值拉宽至 [22.0, 24.0, 27.0, 29.0] (方案C)",
    "V5.2 回测: 换挡-19%, R2+30%, 仓位波动-19%, 极端事件无损",
    "V5.2 缓冲带 0.5→0.8 (间距拉宽后平滑过渡更好)",
    "V5 R1 仓位上限 80% (原95%)，控制 MDD",
    "V5 回测 Sharpe=0.36 (V4=0.17, 翻倍提升)",
    "Legacy: V3 三因子参数保留，V5_ENABLED=False 可回退",
]

