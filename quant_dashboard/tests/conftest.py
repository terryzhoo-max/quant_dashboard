"""
AlphaCore · pytest fixtures (共享测试基础设施)
==============================================
"""
import sys
import os
from datetime import datetime
import pytest

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def vix_low():
    """低 VIX 场景 (极度平静)"""
    return 12.5

@pytest.fixture
def vix_normal():
    """正常 VIX 场景"""
    return 20.0

@pytest.fixture
def vix_alert():
    """高 VIX 场景 (高度警觉)"""
    return 28.0

@pytest.fixture
def vix_crisis():
    """极端 VIX 场景 (恐慌)"""
    return 42.0

@pytest.fixture
def mock_aiae_ctx():
    """模拟 AIAE 上下文 (Regime III 均衡)"""
    return {
        "status": "success",
        "updated_at": datetime.now().isoformat(),
        "data_quality_score": 90,
        "decision_locked": False,
        "regime": 3,
        "cap": 65,
        "aiae_v1": 22.0,
        "erp_tier": "neutral",
        "erp_val": 4.5,
        "erp_label": "中性",
        "regime_info": {
            "emoji": "⚖️",
            "cn": "均衡配置",
            "color": "#3b82f6",
            "action": "结构性配置",
            "desc": "核心+卫星",
            "position": "50-65%",
            "range": "15-28%",
        },
        "margin_heat": 2.0,
        "slope": 0.5,
        "slope_direction": "flat",
        "fund_position": 78,
    }


@pytest.fixture(autouse=True)
def _neutral_market_vol_overlay(monkeypatch):
    """测试隔离: 默认把市场波动刹车设为中性, 避免读取本机真实行情/状态文件。

    需要验证刹车行为的测试直接调用 services.vol_regime 的纯函数,
    或自行 monkeypatch current_overlay / get_vol_overlay。
    """
    try:
        from services import vol_regime
    except Exception:
        yield
        return
    neutral = {"status": "ok", "factor": 1.0, "brake_on": False}
    monkeypatch.setattr(vol_regime, "get_vol_overlay", lambda today=None: dict(neutral))
    monkeypatch.setattr(vol_regime, "get_vol_adjustment_factor", lambda: 1.0)
    monkeypatch.setattr(vol_regime, "current_overlay", lambda: dict(neutral))
    yield
