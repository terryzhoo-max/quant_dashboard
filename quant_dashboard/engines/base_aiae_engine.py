"""
AlphaCore AIAE 引擎基类
=======================
Sprint 2 · P3: 提取 AIAE 4 引擎家族的共性逻辑到基类。

设计原则:
  - 100% 相同的方法 → 基类直接实现 (concrete)
  - 逻辑相同但阈值/参数不同 → 通过类属性参数化
  - 根本性不同的方法 → @abstractmethod 由子类实现

子类只需覆盖:
  - 类属性 (REGION, VERSION, REGIME_THRESHOLDS, POSITION_MATRIX, ...)
  - 数据获取方法 (_fetch_xxx)
  - 市场特有的核心计算 (compute_aiae_core / compute_aiae_simple)

Sprint 3 目标: 逐个引擎迁移到继承此基类
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger("alphacore.engines.base_aiae")


class BaseAIAEEngine(ABC):
    """AIAE 引擎基类 — 多市场共用逻辑的参数化实现。

    子类配置清单 (class-level attributes):
        REGION: str             — 市场标识 (CN/US/JP/HK)
        VERSION: str            — 引擎版本号
        REGIME_THRESHOLDS: list — 5 档 AIAE 阈值 [t1, t2, t3, t4] (4 个分界点)
        POSITION_MATRIX: dict   — {erp_level: [pos_r1, pos_r2, ..., pos_r5]}
        POSITION_MATRIX_DEFAULT_ROW: str — 矩阵默认行键
        SUB_STRATEGY_TABLE: dict — 子策略分配表 {regime: {...}}

    生命周期:
        __init__ → refresh → generate_report
    """

    # ─── 子类必须覆盖的类属性 ───
    REGION: str = ""
    VERSION: str = "1.0"
    REGIME_THRESHOLDS: List[float] = [15, 20, 25, 30]  # 4 个分界点 → 5 档
    POSITION_MATRIX: Dict[str, List[int]] = {}
    POSITION_MATRIX_DEFAULT_ROW: str = "erp_1_3"
    SUB_STRATEGY_TABLE: Dict[int, Dict] = {}
    SLOPE_SIGNAL_THRESHOLD: float = 3.0  # 斜率报警阈值 (JP=2.0, CN=3.0)

    # ─── 参数化: compute_slope ───
    def compute_slope(self, current: float, previous: float) -> Dict:
        """计算斜率方向 — 结构一致, 阈值由 SLOPE_SIGNAL_THRESHOLD 参数化。

        子类可覆盖以自定义 signal 格式 (如 JP 使用 dict 格式的 signal)。
        """
        if previous is None or previous == 0:
            return {"slope": 0, "direction": "flat", "signal": None}
        slope = current - previous
        direction = "rising" if slope > 0 else ("falling" if slope < 0 else "flat")
        signal = None
        if abs(slope) > self.SLOPE_SIGNAL_THRESHOLD:
            signal = "accelerating" if slope > 0 else "decelerating"
        return {"slope": round(slope, 2), "direction": direction, "signal": signal}

    # ─── 参数化: classify_regime ───
    def classify_regime(self, aiae_value: float, **kwargs) -> int:
        """AIAE 值 → 档位 (1-5)。

        阈值由子类的 REGIME_THRESHOLDS 提供。
        子类可覆盖此方法以添加迟滞逻辑 (如 A 股的 prev_regime 平滑)。
        """
        t = self.REGIME_THRESHOLDS
        if aiae_value < t[0]:
            return 1
        elif aiae_value < t[1]:
            return 2
        elif aiae_value < t[2]:
            return 3
        elif aiae_value < t[3]:
            return 4
        else:
            return 5

    # ─── 参数化: get_position_from_matrix ───
    def get_position_from_matrix(self, regime: int, erp_level: str, **kwargs) -> int:
        """AIAE × ERP 交叉查表 → 建议仓位。

        矩阵由子类的 POSITION_MATRIX 提供。
        """
        matrix = self.POSITION_MATRIX
        default_key = self.POSITION_MATRIX_DEFAULT_ROW
        row = matrix.get(erp_level, matrix.get(default_key, [50] * 5))
        idx = min(regime - 1, 4)
        return row[idx]

    # ─── 参数化: classify_erp_level ───
    @abstractmethod
    def classify_erp_level(self, erp_score: float) -> str:
        """ERP 评分 → ERP 档位标签 (子类定义各市场的分级逻辑)。"""
        ...

    # ─── 参数化: allocate_sub_strategies ───
    @abstractmethod
    def allocate_sub_strategies(self, regime: int, total_position: int = 0) -> Dict:
        """按 regime 分配子策略权重。

        各市场 ETF 标的池和返回格式不同 (JP 返回含 name/pct/position 的对象),
        因此设为 abstractmethod。
        """
        ...

    # ─── 市场特有: 子类必须实现 ───
    @abstractmethod
    def compute_aiae_core(self, *args, **kwargs) -> Dict:
        """核心 AIAE 值计算 (每个市场的数据源和公式不同)。"""
        ...

    @abstractmethod
    def generate_report(self) -> Dict:
        """生成完整报告 (子类组装市场特有的数据结构)。"""
        ...

    @abstractmethod
    def generate_signals(self, regime: int, **kwargs) -> List[Dict]:
        """生成 ETF 信号列表 (各市场标的池不同)。"""
        ...

    @abstractmethod
    def refresh(self) -> Dict:
        """刷新引擎缓存并重新计算 (子类控制缓存策略)。"""
        ...

    @abstractmethod
    def get_chart_data(self) -> Dict:
        """获取图表可视化数据 (各市场维度不同)。"""
        ...

    # ─── 降级: 子类实现 ───
    @abstractmethod
    def _fallback_report(self, reason: str = "") -> Dict:
        """降级报告 — 各市场降级数据结构不同 (含市场特有字段)。"""
        ...

    # ─── 交叉验证: 子类实现 ───
    @abstractmethod
    def _cross_validate(self, regime: int, erp_value: float) -> Dict:
        """AIAE × ERP 交叉验证。

        各市场交叉验证逻辑差异大:
        - CN: primary/secondary 一致性对比
        - JP/HK/US: regime × erp_value 矩阵判决
        """
        ...
