"""
AlphaCore ERP 引擎基类
======================
Sprint 2 · P3: 提取 ERP 4 引擎家族的共性逻辑到基类。

设计原则:
  - D1 (绝对水平) / D2 (分位数) 评分: 100% 相同 → concrete
  - momentum_modifier / smooth_composite: 100% 相同 → concrete
  - D3-D5 维度评分: 各市场数据源不同 → abstractmethod
  - compute_signal 主流程: 结构相同 → 模板方法

子类只需覆盖:
  - 类属性 (REGION, VERSION, DIMENSIONS, ...)
  - 数据获取方法 (_fetch_xxx)
  - D3-D5 市场特有维度评分

Sprint 3 目标: 逐个引擎迁移到继承此基类
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
import logging
import numpy as np

logger = logging.getLogger("alphacore.engines.base_erp")


class BaseERPEngine(ABC):
    """ERP 择时引擎基类 — 多市场共用逻辑的参数化实现。

    子类配置清单 (class-level attributes):
        REGION: str             — 市场标识 (CN/US/JP/HK)
        VERSION: str            — 引擎版本号
        ERP_WINDOW: int         — ERP 分位数回溯窗口 (默认 252)
        EMA_SPAN: int           — 复合评分 EMA 平滑跨度 (默认 5)
        D1_THRESHOLDS: dict     — D1 绝对水平评分阈值
        D2_PERCENTILE_MAP: list — D2 分位数到评分的映射
        TRADE_RULES: dict       — {signal_key: {label, color, emoji, ...}}
        DIMENSIONS: list        — 评分维度列表 (如 ["d1","d2","d3","d4","d5"])

    主流程:
        compute_signal → _score_d1 + _score_d2 + _score_d3..d5 → _smooth_composite
                       → _generate_trade_rules → _generate_alerts → build result
    """

    # ─── 子类必须覆盖的类属性 ───
    REGION: str = ""
    VERSION: str = "1.0"
    ERP_WINDOW: int = 252
    EMA_SPAN: int = 5
    D1_THRESHOLDS: Dict = {
        "strong_buy": 6.0,
        "buy": 4.0,
        "neutral_high": 2.5,
        "neutral_low": 1.0,
        "sell": 0.0,
    }
    D2_PERCENTILE_MAP: List = []  # 子类提供
    TRADE_RULES: Dict = {}        # 子类提供
    DIMENSIONS: List[str] = ["d1_erp_abs", "d2_erp_pct"]

    # ─── 100% 相同: _score_d1_erp_absolute ───
    def _score_d1_erp_absolute(self, erp_value: float) -> Tuple[float, Dict]:
        """D1 维度: ERP 绝对水平评分 (4 引擎完全一致)。

        使用分段线性映射: ERP 绝对值 → 0-100 评分。
        阈值由子类的 D1_THRESHOLDS 提供。
        """
        t = self.D1_THRESHOLDS
        if erp_value >= t["strong_buy"]:
            score = min(100, 70 + (erp_value - t["strong_buy"]) * 5)
        elif erp_value >= t["buy"]:
            score = 55 + (erp_value - t["buy"]) / (t["strong_buy"] - t["buy"]) * 15
        elif erp_value >= t["neutral_high"]:
            score = 45 + (erp_value - t["neutral_high"]) / (t["buy"] - t["neutral_high"]) * 10
        elif erp_value >= t["neutral_low"]:
            score = 35 + (erp_value - t["neutral_low"]) / (t["neutral_high"] - t["neutral_low"]) * 10
        elif erp_value >= t["sell"]:
            score = 20 + (erp_value - t["sell"]) / (t["neutral_low"] - t["sell"]) * 15
        else:
            score = max(0, 20 + erp_value * 5)

        info = {
            "erp_value": round(erp_value, 4),
            "score": round(score, 1),
            "level": (
                "极度低估" if score >= 70 else
                "低估" if score >= 55 else
                "中性偏低" if score >= 45 else
                "中性" if score >= 35 else
                "偏贵" if score >= 20 else
                "高估"
            ),
        }
        return round(score, 1), info

    # ─── 100% 相同: _score_d2_erp_percentile ───
    def _score_d2_erp_percentile(self, erp_value: float,
                                  erp_series: Any) -> Tuple[float, Dict]:
        """D2 维度: ERP 历史分位数评分 (4 引擎完全一致)。

        使用 ERP 值在历史序列中的百分位排名映射到评分。
        """
        if erp_series is None or len(erp_series) < 30:
            return 50.0, {"percentile": 50, "score": 50, "status": "数据不足"}

        try:
            arr = np.array(erp_series, dtype=float)
            arr = arr[~np.isnan(arr)]
            if len(arr) < 30:
                return 50.0, {"percentile": 50, "score": 50, "status": "有效数据不足"}

            percentile = float(np.mean(arr <= erp_value) * 100)

            # 分位数 → 评分映射 (越高分位 = ERP 越被低估 = 越值得买)
            if percentile >= 90:
                score = 85 + (percentile - 90) * 1.5
            elif percentile >= 70:
                score = 60 + (percentile - 70) * 1.25
            elif percentile >= 50:
                score = 45 + (percentile - 50) * 0.75
            elif percentile >= 30:
                score = 30 + (percentile - 30) * 0.75
            else:
                score = max(5, percentile)

            info = {
                "percentile": round(percentile, 1),
                "score": round(score, 1),
                "window": len(arr),
                "status": "正常",
            }
            return round(score, 1), info
        except Exception as e:
            logger.warning("[%s] D2 计算异常: %s", self.REGION, e)
            return 50.0, {"percentile": 50, "score": 50, "status": f"异常: {e}"}

    # ─── 100% 相同: _erp_momentum_modifier ───
    def _erp_momentum_modifier(self, erp_series: Any,
                                lookback: int = 20) -> Tuple[float, Dict]:
        """ERP 动量修正因子 (4 引擎完全一致)。

        检测 ERP 近期趋势方向，对复合评分做 ±5 的修正。
        """
        if erp_series is None or len(erp_series) < lookback + 5:
            return 0.0, {"momentum": 0, "direction": "flat", "status": "数据不足"}

        try:
            recent = np.array(erp_series[-lookback:], dtype=float)
            recent = recent[~np.isnan(recent)]
            if len(recent) < 10:
                return 0.0, {"momentum": 0, "direction": "flat", "status": "有效数据不足"}

            slope = np.polyfit(np.arange(len(recent)), recent, 1)[0]
            # 标准化到 ±5 范围
            modifier = np.clip(slope * 50, -5, 5)
            direction = "rising" if modifier > 1 else ("falling" if modifier < -1 else "flat")

            info = {
                "momentum": round(float(modifier), 2),
                "slope": round(float(slope), 6),
                "direction": direction,
            }
            return round(float(modifier), 2), info
        except Exception as e:
            logger.warning("[%s] 动量修正异常: %s", self.REGION, e)
            return 0.0, {"momentum": 0, "direction": "error", "status": str(e)}

    # ─── 100% 相同: _smooth_composite ───
    def _smooth_composite(self, raw_score: float,
                           history: List[float] = None) -> float:
        """EMA 平滑复合评分 (4 引擎完全一致)。

        使用 EMA_SPAN 控制平滑窗口。
        """
        if history is None or len(history) < 2:
            return round(raw_score, 1)

        try:
            alpha = 2.0 / (self.EMA_SPAN + 1)
            smoothed = history[-1]
            smoothed = alpha * raw_score + (1 - alpha) * smoothed
            return round(np.clip(smoothed, 0, 100), 1)
        except Exception:
            return round(raw_score, 1)

    # ─── 通用降级: _fallback_signal ───
    def _fallback_signal(self, error: Exception = None) -> Dict:
        """通用降级信号。子类可覆盖以添加市场特有的降级数据。"""
        return {
            "status": "fallback",
            "region": self.REGION,
            "version": self.VERSION,
            "signal": {
                "score": 50,
                "key": "hold",
                "label": "中性 (降级)",
                "color": "#94a3b8",
                "emoji": "⚪",
            },
            "current_snapshot": {"erp_value": 0},
            "error": str(error) if error else "数据不可用，使用降级值",
        }

    # ─── 子类必须实现的抽象方法 ───
    @abstractmethod
    def _compute_erp_series(self) -> Any:
        """计算 ERP 时间序列 (各市场数据源完全不同)。"""
        ...

    @abstractmethod
    def _score_market_dimensions(self, **kwargs) -> List[Tuple[str, float, Dict]]:
        """计算 D3-D5 市场特有维度评分。

        返回 [(dim_name, score, info_dict), ...] 列表。
        """
        ...

    @abstractmethod
    def compute_signal(self) -> Dict:
        """主计算流程: 组装所有维度 → 复合评分 → 交易规则。"""
        ...

    @abstractmethod
    def generate_report(self) -> Dict:
        """生成完整报告 (子类组装市场特有的数据结构)。"""
        ...

    @abstractmethod
    def get_erp_chart_data(self) -> Dict:
        """获取 ERP 图表可视化数据。"""
        ...

    @abstractmethod
    def _generate_trade_rules(self, score: float) -> Dict:
        """基于复合评分生成交易规则 (各市场阈值和标签不同)。"""
        ...

    @abstractmethod
    def _generate_alerts(self, **kwargs) -> List[Dict]:
        """生成预警信号列表 (各市场触发条件不同)。"""
        ...

    @abstractmethod
    def _build_diagnosis(self, **kwargs) -> Dict:
        """构建诊断报告 (各市场特有指标)。"""
        ...
