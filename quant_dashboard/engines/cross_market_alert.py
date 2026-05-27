"""
AlphaCore · 跨市场 AIAE 联动预警引擎 V1.0
==========================================
监测四市场 (中/美/港/日) AIAE 状态联动, 生成跨市场风险传导预警。

传导矩阵 (基于历史相关性回归):
  US→CN: 0.45  (美股隔夜效应)
  US→HK: 0.72  (强联动)
  HK→CN: 0.35  (弱联动)
  JP→CN: 0.15  (最弱)

V1.0 2026-05-26
"""

import threading
from datetime import datetime
from typing import Dict, List, Optional


def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [CROSS_MKT] {msg}")


# 跨市场传导系数矩阵
CONTAGION_MATRIX = {
    ("US", "CN"): 0.45,
    ("US", "HK"): 0.72,
    ("HK", "CN"): 0.35,
    ("JP", "CN"): 0.15,
    ("JP", "HK"): 0.20,
    ("US", "JP"): 0.30,
}

REGION_NAMES = {"CN": "A股", "US": "美股", "JP": "日股", "HK": "港股"}


class CrossMarketAlertEngine:
    """跨市场 AIAE 联动预警引擎"""

    VERSION = "1.0"

    def __init__(self):
        _log(f"CrossMarketAlertEngine V{self.VERSION} 初始化")

    def scan_alerts(self, regimes: Dict[str, int], aiae_values: Dict[str, float] = None) -> List[Dict]:
        """
        扫描跨市场联动告警。
        
        Args:
            regimes: {"CN": 3, "US": 4, "HK": 2, "JP": 3}
            aiae_values: {"CN": 21.5, "US": 28.0, "HK": 12.0, "JP": 17.0} (可选)
        
        Returns:
            告警列表, 按严重度排序
        """
        if not regimes:
            return []

        alerts = []

        cn = regimes.get("CN", 3)
        us = regimes.get("US", 3)
        hk = regimes.get("HK", 3)
        jp = regimes.get("JP", 3)

        # ── Rule 1: 美股过热 + A股中性/偏冷 ──
        if us >= 4 and cn <= 3:
            coef = CONTAGION_MATRIX.get(("US", "CN"), 0.45)
            alerts.append({
                "id": "us_overheat_cn_neutral",
                "severity": "warning",
                "emoji": "⚠️",
                "title": "美股过热传导风险",
                "message": f"美股过热(R{us})但A股中性(R{cn}), "
                           f"历史上美股回调对A股有 {coef:.0%} 传导概率",
                "source": "US", "target": "CN",
                "contagion_coef": coef,
                "action": "关注美股回调风险, 降低A股高波动标的仓位",
            })

        # ── Rule 2: 美股冰点 + A股偏热 ──
        if us <= 2 and cn >= 4:
            alerts.append({
                "id": "us_cold_cn_hot",
                "severity": "opportunity",
                "emoji": "🟢",
                "title": "美股冰点·A股减仓窗口",
                "message": f"美股冰点(R{us})但A股偏热(R{cn}), "
                           f"A股可能滞后跟跌 — 减仓窗口",
                "source": "US", "target": "CN",
                "contagion_coef": CONTAGION_MATRIX.get(("US", "CN"), 0.45),
                "action": "A股系统减仓, 关注美股是否触底反转",
            })

        # ── Rule 3: 港股极端 ──
        if hk >= 5:
            coef = CONTAGION_MATRIX.get(("HK", "CN"), 0.35)
            alerts.append({
                "id": "hk_euphoria",
                "severity": "critical",
                "emoji": "🔴",
                "title": "港股极度过热",
                "message": f"港股极度过热(R{hk}), 对A股传导系数 {coef:.0%} — 检查港股持仓",
                "source": "HK", "target": "CN",
                "contagion_coef": coef,
                "action": "清仓港股, 降低A股与港股高相关标的",
            })
        elif hk <= 1:
            alerts.append({
                "id": "hk_extreme_fear",
                "severity": "opportunity",
                "emoji": "🟢",
                "title": "港股极度恐慌·配置窗口",
                "message": f"港股极度恐慌(R{hk}), 历史底部区域 — 可考虑左侧配置",
                "source": "HK", "target": "CN",
                "contagion_coef": CONTAGION_MATRIX.get(("HK", "CN"), 0.35),
                "action": "分批建仓港股核心标的 (如恒生科技ETF)",
            })

        # ── Rule 4: 全球同步过热 ──
        hot_count = sum(1 for r in [cn, us, hk, jp] if r >= 4)
        if hot_count >= 3:
            alerts.append({
                "id": "global_overheat",
                "severity": "critical",
                "emoji": "🔴🔴",
                "title": "全球同步过热",
                "message": f"四市场中 {hot_count} 个过热 (R≥4), 系统性风险极高",
                "source": "GLOBAL", "target": "ALL",
                "contagion_coef": 0.90,
                "action": "全面降仓至防守位, 增持现金和黄金",
            })

        # ── Rule 5: 全球同步冰点 ──
        cold_count = sum(1 for r in [cn, us, hk, jp] if r <= 2)
        if cold_count >= 3:
            alerts.append({
                "id": "global_freeze",
                "severity": "opportunity",
                "emoji": "🟢🟢",
                "title": "全球同步冰点",
                "message": f"四市场中 {cold_count} 个冰点 (R≤2), 历史级配置窗口",
                "source": "GLOBAL", "target": "ALL",
                "contagion_coef": 0.85,
                "action": "积极加仓至进攻位, 优先配置最冷市场",
            })

        # ── Rule 6: 美股Ⅴ级 (极端事件) ──
        if us >= 5:
            alerts.append({
                "id": "us_euphoria_global",
                "severity": "critical",
                "emoji": "🔴",
                "title": "美股极度过热·全球警报",
                "message": f"美股Ⅴ级(R{us}), 历史上100%后跌. "
                           f"对港股传导 {CONTAGION_MATRIX.get(('US', 'HK'), 0.72):.0%}, "
                           f"对A股传导 {CONTAGION_MATRIX.get(('US', 'CN'), 0.45):.0%}",
                "source": "US", "target": "GLOBAL",
                "contagion_coef": 0.80,
                "action": "清仓海外, A股降至防守位, 增加黄金避险",
            })

        # ── Rule 7: 方向矛盾 (一冷一热) ──
        if cn <= 2 and us >= 4:
            alerts.append({
                "id": "cn_cold_us_hot_divergence",
                "severity": "info",
                "emoji": "⚡",
                "title": "中美市场极端分化",
                "message": f"A股冰点(R{cn}) vs 美股过热(R{us}), "
                           f"市场极端分化 — 配置天平倾向A股",
                "source": "DIVERGENCE", "target": "CN",
                "contagion_coef": 0.45,
                "action": "超配A股, 低配美股, 等待均值回归",
            })

        # 按严重度排序: critical > warning > opportunity > info
        severity_order = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
        alerts.sort(key=lambda x: severity_order.get(x["severity"], 9))

        _log(f"跨市场扫描完成: CN=R{cn} US=R{us} HK=R{hk} JP=R{jp} → {len(alerts)} 个告警")
        return alerts

    def get_contagion_matrix(self) -> Dict:
        """返回传导矩阵 (供前端可视化)"""
        return {
            "matrix": {f"{s}→{t}": c for (s, t), c in CONTAGION_MATRIX.items()},
            "regions": list(REGION_NAMES.keys()),
            "region_names": REGION_NAMES,
        }


# ===== 引擎单例 =====
_cross_instance = None
_cross_lock = threading.Lock()


def get_cross_alert_engine() -> CrossMarketAlertEngine:
    global _cross_instance
    if _cross_instance is None:
        with _cross_lock:
            if _cross_instance is None:
                _cross_instance = CrossMarketAlertEngine()
    return _cross_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  Cross-Market Alert Engine V1.0 · Self-Test")
    print("=" * 60)

    engine = CrossMarketAlertEngine()

    # 场景1: 美股过热 + A股中性
    print("\n[场景1] 美股过热 + A股中性")
    alerts = engine.scan_alerts({"CN": 3, "US": 4, "HK": 2, "JP": 3})
    for a in alerts:
        print(f"  {a['emoji']} [{a['severity']}] {a['title']}")
        print(f"     {a['message']}")

    # 场景2: 全球同步过热
    print("\n[场景2] 全球同步过热")
    alerts = engine.scan_alerts({"CN": 4, "US": 5, "HK": 4, "JP": 3})
    for a in alerts:
        print(f"  {a['emoji']} [{a['severity']}] {a['title']}")

    # 场景3: 全球冰点
    print("\n[场景3] 全球同步冰点")
    alerts = engine.scan_alerts({"CN": 1, "US": 2, "HK": 1, "JP": 2})
    for a in alerts:
        print(f"  {a['emoji']} [{a['severity']}] {a['title']}")

    # 场景4: 无告警
    print("\n[场景4] 全部中性 (无告警)")
    alerts = engine.scan_alerts({"CN": 3, "US": 3, "HK": 3, "JP": 3})
    print(f"  告警数: {len(alerts)}")

    print(f"\n{'='*60}")
