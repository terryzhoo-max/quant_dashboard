"""
AlphaCore · 港股 AIAE 宏观仓位策略参数中心 (Single Source of Truth)
================================================================
所有港股 AIAE 相关模块（引擎 / 前端）的参数统一从此文件读取。
禁止在 aiae_hk_engine.py 或其他文件中硬编码权重、阈值或归一化区间。

V2.0 优化依据:
  - 对标 A 股引擎 aiae_params.py V5.2 (Sigmoid + 迟滞 + 因子归因框架)
  - 港股 9 个历史关键节点 (2018-2026) 回归校准
  - AH溢价 / 南向热度 归一化区间基于 2019-2026 实际分布重标定
"""

import math

# ═══════════════════════════════════════════════════════════════
#  版本控制 & V2 开关
# ═══════════════════════════════════════════════════════════════

HK_V2_ENABLED = True   # True=V2 Sigmoid模式, False=回退到V1线性模式

VERSION = "2.0"
OPTIMIZED_AT = "2026-06-10"
OPTIMIZATION_NOTES = [
    "V1→V2: 三因子线性归一化 → Sigmoid 归一化",
    "V2 新增: Regime 迟滞带 (±0.5pt) + 缓冲带 (±1.0pt)",
    "V2 新增: Regime 内仓位平滑插值 (消除离散跳变)",
    "V2 新增: 因子贡献度诊断面板",
    "V2 新增: AIAE 历史滚动存储 (JSONL)",
    "V2 保持: 权重 50/20/30 不动, 通过 Sigmoid 改善信号质量",
    "V2 保持: 三因子结构, 因子诊断面板积累数据供 V3 精简决策",
]

# ═══════════════════════════════════════════════════════════════
#  三因子权重 (总和严格 = 1.00)
# ═══════════════════════════════════════════════════════════════
#
# Q1 决策: 保持 50/20/30 不动, 依靠 Sigmoid 改善信号质量
# 等积累 24 个月滚动数据后再做因子归因回测

W_CORE = 0.50   # 证券化率 (月频 M2 + 日频市值) — 核心信号
W_SB   = 0.20   # 南向热度 (日频自动 Tushare) — 增量资金流
W_AH   = 0.30   # AH溢价 (日频 yfinance+Tushare) — 估值偏差

assert abs(W_CORE + W_SB + W_AH - 1.0) < 1e-9, \
    f"三因子权重总和 ≠ 1.0: {W_CORE + W_SB + W_AH}"

# ═══════════════════════════════════════════════════════════════
#  Sigmoid 归一化参数
# ═══════════════════════════════════════════════════════════════
#
# 通用归一化输出区间: [NORM_MIN, NORM_MAX]
# 每个因子的 center/k 基于历史分布独立标定

NORM_MIN = 6.0    # AIAE 等效最小值 (对应极度恐慌)
NORM_MAX = 30.0   # AIAE 等效最大值 (对应极度过热)

# ──── Core 因子 (证券化率 ratio = HSI_MktCap / CN_M2) ────
# 历史锚点校准 (scipy.optimize 最小二乘拟合):
#   ratio=0.06 (极端底部)            → Sigmoid 输出 ≈6.6% (Regime Ⅰ 深处)
#   ratio=0.08 (2022-10 HSI 14800)   → Sigmoid 输出 ≈7.5% (Regime Ⅰ)
#   ratio=0.10 (2024-01 HSI 15300)   → Sigmoid 输出 ≈9.4% (Regime Ⅱ)
#   ratio=0.14 (中位数, HSI ~22000)  → Sigmoid 输出 ≈18.0% (Regime Ⅲ 中部)
#   ratio=0.20 (2018-01 HSI 33500)   → Sigmoid 输出 ≈28.5% (Regime Ⅴ)
CORE_SIGMOID_CENTER = 0.14
CORE_SIGMOID_K      = 45.0

# ──── 南向热度 (sb_heat = 南向12M累计 / HSI总市值 × 100%) ────
# 历史实际分布 (2019-2026): 中位数 ~0.8%, P10=0.1%, P90=2.0%
# 旧线性区间 [0-5%] 上限过宽, 90%数据挤在下部 → 区分度丧失
# Sigmoid 校准 (scipy.optimize):
#   heat=0.03% → 10.8 (当前值, 接近恐慌下界)
#   heat=0.8%  → 18.0 (中性)
#   heat=2.0%  → 27.5 (过热信号)
SB_SIGMOID_CENTER = 0.8
SB_SIGMOID_K      = 1.8

# ──── AH 溢价指数 (ah_index, 100=A/H平价) ────
# 历史实际分布 (2019-2026): 中位数 ~132, P10=110, P90=155
# k < 0 实现反向映射: AH越高 = H股越便宜 = AIAE越低 (利好加仓)
# Sigmoid 校准 (scipy.optimize, 降低因子主导度):
#   AH=105 → ~26.5 (H股偏贵, 接近过热)
#   AH=113 → ~24.7 (当前值, 偏热但不极端)
#   AH=132.5 → ~18.0 (中性)
#   AH=160 → ~9.5 (H股极度低估)
AH_SIGMOID_CENTER = 132.5
AH_SIGMOID_K      = -0.064

# ═══════════════════════════════════════════════════════════════
#  V1 线性归一化参数 (回退模式使用)
# ═══════════════════════════════════════════════════════════════

V1_CORE_RATIO_LOW   = 0.08   # ratio 线性映射下界
V1_CORE_RATIO_HIGH  = 0.20   # ratio 线性映射上界
V1_CORE_AIAE_LOW    = 6.0    # 映射到 AIAE 6%
V1_CORE_AIAE_HIGH   = 28.0   # 映射到 AIAE 28%
V1_CORE_CLAMP_MIN   = 4.0
V1_CORE_CLAMP_MAX   = 35.0

V1_SB_HEAT_MAX      = 5.0    # 南向热度归一化上限
V1_SB_NORM_LOW      = 10.0   # 归一化输出下界
V1_SB_NORM_HIGH     = 30.0   # 归一化输出上界

V1_AH_INDEX_LOW     = 105.0  # AH 溢价映射下界
V1_AH_INDEX_HIGH    = 160.0  # AH 溢价映射上界
V1_AH_AIAE_LOW      = 10.0   # AH=160 → 10% (低估)
V1_AH_AIAE_HIGH     = 30.0   # AH=105 → 30% (过热)

# ═══════════════════════════════════════════════════════════════
#  五档分界线
# ═══════════════════════════════════════════════════════════════
#
# 港股校准 (比 A 股下移 4-5%):
#   Ⅰ <8%:   2022-10 HSI 14800 极底
#   Ⅱ 8-12%: 2024-01 HSI 15300
#   Ⅲ 12-18%: 常态区间
#   Ⅳ 18-25%: 2021-02 HSI 31000 / 2024-09 国庆牛市
#   Ⅴ >25%:  2018-01 HSI 33500

HK_REGIME_THRESHOLDS = [8, 12, 18, 25]   # [Ⅰ/Ⅱ, Ⅱ/Ⅲ, Ⅲ/Ⅳ, Ⅳ/Ⅴ]

# V2 分界线平滑缓冲带 (±BUFFER 内做线性插值, 消除仓位跳变)
# 前提约束: BUFFER < min(相邻分界线间距) / 2
HK_REGIME_SMOOTH_BUFFER = 1.0   # AIAE 百分点

# V2 Regime 判定迟滞带 (防止边界微幅波动导致频繁换挡)
# 上行跨越需 threshold + H, 下行回落需 threshold - H
HK_REGIME_HYSTERESIS = 0.5     # AIAE 百分点

_min_gap = min(HK_REGIME_THRESHOLDS[i+1] - HK_REGIME_THRESHOLDS[i]
               for i in range(len(HK_REGIME_THRESHOLDS)-1))
assert HK_REGIME_SMOOTH_BUFFER < _min_gap / 2, \
    f"HK_REGIME_SMOOTH_BUFFER({HK_REGIME_SMOOTH_BUFFER}) 必须 < 最小分界线间距({_min_gap})/2={_min_gap/2}"

# ═══════════════════════════════════════════════════════════════
#  仓位矩阵
# ═══════════════════════════════════════════════════════════════

# 行: ERP 水位, 列: AIAE 档位 (1-5)
POSITION_MATRIX_HK = {
    "erp_gt8":  [95, 85, 70, 45, 20],
    "erp_6_8":  [90, 80, 65, 40, 15],
    "erp_4_6":  [85, 70, 55, 30, 10],
    "erp_lt4":  [75, 60, 40, 20,  5],
}

# 子策略配额
SUB_STRATEGY_ALLOC_HK = {
    1: {"hsi": 30, "hstech": 45, "dividend": 25},
    2: {"hsi": 35, "hstech": 35, "dividend": 30},
    3: {"hsi": 30, "hstech": 30, "dividend": 40},
    4: {"hsi": 20, "hstech": 15, "dividend": 65},
    5: {"hsi": 10, "hstech":  0, "dividend": 90},
}

for _regime, _alloc in SUB_STRATEGY_ALLOC_HK.items():
    _row_sum = sum(_alloc.values())
    assert _row_sum == 100, f"SUB_STRATEGY_ALLOC_HK[{_regime}] 行和={_row_sum}, 应为100"

# ═══════════════════════════════════════════════════════════════
#  五档状态定义 (元数据)
# ═══════════════════════════════════════════════════════════════

REGIMES_HK = {
    1: {"name": "Ⅰ · EXTREME FEAR", "cn": "极度恐慌", "range": "<8%",
        "color": "#10b981", "emoji": "🟢", "position": "90-95%", "pos_min": 90, "pos_max": 95,
        "action": "满配进攻", "desc": "2022年10月底部级别 · 分3批建仓"},
    2: {"name": "Ⅱ · LOW ALLOCATION", "cn": "低配置区", "range": "8-12%",
        "color": "#3b82f6", "emoji": "🔵", "position": "70-85%", "pos_min": 70, "pos_max": 85,
        "action": "标准建仓", "desc": "2024年1月底部 · 耐心持有"},
    3: {"name": "Ⅲ · NEUTRAL", "cn": "中性均衡", "range": "12-18%",
        "color": "#eab308", "emoji": "🟡", "position": "50-65%", "pos_min": 50, "pos_max": 65,
        "action": "均衡持有", "desc": "常态运行 · 有纪律地持有"},
    4: {"name": "Ⅳ · GETTING HOT", "cn": "偏热区域", "range": "18-25%",
        "color": "#f97316", "emoji": "🟠", "position": "25-40%", "pos_min": 25, "pos_max": 40,
        "action": "系统减仓", "desc": "2024年9月牛市 · 每周减5%"},
    5: {"name": "Ⅴ · EUPHORIA", "cn": "极度过热", "range": ">25%",
        "color": "#ef4444", "emoji": "🔴", "position": "0-15%", "pos_min": 0, "pos_max": 15,
        "action": "清仓防守", "desc": "2018年1月级别 · 3天清仓"},
}

# ═══════════════════════════════════════════════════════════════
#  告警阈值
# ═══════════════════════════════════════════════════════════════

# 南向资金
SB_WARN_WEEKLY_HIGH   = 40.0   # 周净买 > 此值(亿RMB): 南向强劲流入
SB_WARN_WEEKLY_LOW    = -20.0  # 周净买 < 此值: 南向大幅流出
SB_HEAT_CLAMP_MAX     = 5.0    # 热度异常上限 (防 MktCap 脏数据)
SB_HEAT_CLAMP_FALLBACK = 1.5   # 钳制后的兜底值

# AH 溢价
AH_WARN_HIGH = 150.0   # AH > 此值: H股显著折价 (opportunity)
AH_WARN_LOW  = 105.0   # AH < 此值: H股偏贵 (warning)

# 斜率
SLOPE_ACCEL_UP   = 2.0    # > 此值触发 "加速上行" 警告
SLOPE_ACCEL_DOWN = -2.0   # < 此值触发 "加速下行" 机会

# 因子贡献度平衡
FACTOR_DOMINANCE_WARN_PCT = 0.45  # 单因子贡献占比超此阈值触发告警

# ═══════════════════════════════════════════════════════════════
#  Sigmoid 工具函数
# ═══════════════════════════════════════════════════════════════

def sigmoid_normalize(value: float, center: float, k: float,
                      out_min: float = NORM_MIN, out_max: float = NORM_MAX) -> float:
    """Sigmoid 平滑归一化

    Args:
        value:  输入值 (如 ratio 0.14, 南向热度 0.8%, AH指数 132)
        center: 中心值 (输出 50% 分位的锚点)
        k:      斜率 (越大 → 过渡越陡; k<0 实现反向映射)
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
                    buffer: float = HK_REGIME_SMOOTH_BUFFER) -> int:
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
        ratio = (aiae_value - lower) / (upper - lower)
        return round(pos_high + (pos_low - pos_high) * ratio)
