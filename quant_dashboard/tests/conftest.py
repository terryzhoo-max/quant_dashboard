"""
AlphaCore · pytest fixtures (共享测试基础设施)
==============================================
"""
import sys
import os
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
