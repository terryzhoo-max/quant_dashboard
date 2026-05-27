"""
AlphaCore · AIAE 因子趋势追踪引擎 V1.0
=========================================
追踪 AIAE V1 三因子贡献值的时序变化, 供前端堆叠面积图展示。

数据来源:
  - 每日 generate_report() 运行时, 将 decomposition 写入 SQLite
  - 历史读取: 从 factor_history 表读取

V1.0 2026-05-26
"""

import os
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional

from services.logger import get_logger

logger = get_logger("factor_trend")

CACHE_DIR = "data_lake"
FACTOR_HISTORY_FILE = os.path.join(CACHE_DIR, "aiae_factor_history.json")


class FactorTrendEngine:
    """AIAE 因子贡献趋势追踪引擎"""

    VERSION = "1.0"
    MAX_HISTORY_DAYS = 180

    def __init__(self):
        self._history = self._load_history()
        logger.info(f"FactorTrendEngine V{self.VERSION} 初始化, 历史 {len(self._history)} 条")

    def _load_history(self) -> List[dict]:
        """加载磁盘历史"""
        if os.path.exists(FACTOR_HISTORY_FILE):
            try:
                with open(FACTOR_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception as e:
                logger.warning(f"因子历史加载失败: {e}")
        return []

    def _save_history(self):
        """持久化到磁盘"""
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = FACTOR_HISTORY_FILE + ".tmp"
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._history[-self.MAX_HISTORY_DAYS:], f,
                         ensure_ascii=False, indent=2)
            os.replace(tmp, FACTOR_HISTORY_FILE)
        except Exception as e:
            logger.warning(f"因子历史保存失败: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)

    def record_snapshot(self, decomposition: dict, aiae_v1: float = None,
                        regime: int = None, hf_delta: float = None):
        """
        记录一个时间点的因子分解快照。
        
        Args:
            decomposition: compute_aiae_v1_decomposed() 的 decomposition 字段
            aiae_v1: AIAE V1 总值
            regime: 当前档位
            hf_delta: HF 代理偏移量 (可选)
        """
        if not decomposition:
            return

        today = datetime.now().strftime("%Y-%m-%d")

        # 检查是否已有今日记录 → 覆盖
        self._history = [h for h in self._history if h.get("date") != today]

        snapshot = {
            "date": today,
            "aiae_v1": aiae_v1,
            "regime": regime,
            "hf_delta": hf_delta,
            "factors": {},
            "recorded_at": datetime.now().isoformat(),
        }

        for factor_key, factor_data in decomposition.items():
            if isinstance(factor_data, dict):
                snapshot["factors"][factor_key] = {
                    "raw": factor_data.get("raw"),
                    "normalized": factor_data.get("normalized"),
                    "weight": factor_data.get("weight"),
                    "contribution": factor_data.get("contribution"),
                }

        self._history.append(snapshot)

        # 裁剪
        if len(self._history) > self.MAX_HISTORY_DAYS:
            self._history = self._history[-self.MAX_HISTORY_DAYS:]

        self._save_history()
        logger.info(f"因子快照已记录: {today} (AIAE={aiae_v1}, 历史共 {len(self._history)} 条)")

    def get_trend_data(self, days: int = 60) -> dict:
        """
        获取因子趋势数据 (供堆叠面积图)。
        
        Returns:
            {
                "dates": ["2026-04-01", ...],
                "series": {
                    "aiae_simple": {"label": "...", "values": [...]},
                    "fund_position": {"label": "...", "values": [...]},
                    "margin_heat": {"label": "...", "values": [...]},
                },
                "totals": [...],
                "regimes": [...],
                "hf_deltas": [...],
            }
        """
        recent = self._history[-days:] if len(self._history) > days else self._history

        if not recent:
            return {
                "status": "no_data",
                "message": "因子历史为空, 需等待系统运行至少 1 天",
                "days_available": 0,
            }

        dates = []
        totals = []
        regimes = []
        hf_deltas = []

        # 发现所有因子 key
        factor_keys = set()
        for snap in recent:
            for k in snap.get("factors", {}):
                factor_keys.add(k)

        series = {k: {"label": "", "values": []} for k in factor_keys}

        LABELS = {
            "aiae_simple": "AIAE_简 (证券化率)",
            "fund_position": "基金仓位",
            "margin_heat": "融资热度",
        }

        for snap in recent:
            dates.append(snap["date"])
            totals.append(snap.get("aiae_v1"))
            regimes.append(snap.get("regime"))
            hf_deltas.append(snap.get("hf_delta"))

            factors = snap.get("factors", {})
            for k in factor_keys:
                f = factors.get(k, {})
                series[k]["values"].append(f.get("contribution"))
                if not series[k]["label"]:
                    series[k]["label"] = LABELS.get(k, k)

        return {
            "status": "success",
            "days_available": len(recent),
            "dates": dates,
            "series": series,
            "totals": totals,
            "regimes": regimes,
            "hf_deltas": hf_deltas,
        }

    def get_latest_snapshot(self) -> Optional[dict]:
        """获取最新因子快照"""
        return self._history[-1] if self._history else None


# ===== 引擎单例 =====
_ft_instance = None
_ft_lock = threading.Lock()


def get_factor_trend_engine() -> FactorTrendEngine:
    global _ft_instance
    if _ft_instance is None:
        with _ft_lock:
            if _ft_instance is None:
                _ft_instance = FactorTrendEngine()
    return _ft_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  Factor Trend Engine V1.0 · Self-Test")
    print("=" * 60)

    engine = FactorTrendEngine()

    # 模拟记录一条
    mock_decomp = {
        "aiae_simple": {
            "label": "AIAE_简 (证券化率)",
            "raw": 21.5, "normalized": 21.5, "weight": 0.55,
            "contribution": 11.82, "frequency": "月频",
        },
        "fund_position": {
            "label": "基金仓位 (Sigmoid)",
            "raw": 82.0, "normalized": 0.73, "weight": 0.20,
            "contribution": 3.72, "frequency": "季频",
        },
        "margin_heat": {
            "label": "融资热度 (Sigmoid)",
            "raw": 1.05, "normalized": 0.52, "weight": 0.25,
            "contribution": 5.21, "frequency": "日频",
        },
    }
    engine.record_snapshot(mock_decomp, aiae_v1=20.75, regime=3, hf_delta=0.42)

    # 读取趋势
    trend = engine.get_trend_data(days=30)
    print(f"\n  数据状态: {trend['status']}")
    print(f"  可用天数: {trend.get('days_available', 0)}")
    if trend["status"] == "success":
        print(f"  因子: {list(trend['series'].keys())}")
        latest = engine.get_latest_snapshot()
        if latest:
            print(f"  最新日期: {latest['date']}")
            for k, v in latest.get("factors", {}).items():
                print(f"    {k}: contribution={v.get('contribution')}")

    print(f"\n{'='*60}")
