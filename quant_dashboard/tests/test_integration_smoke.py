"""
AlphaCore V21.2 · API 集成烟雾测试
====================================
验证所有关键 API 端点在运行中的服务器上正常响应。
必须在 `pytest -m integration` 模式下运行。
"""

import pytest
import urllib.request
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://127.0.0.1:8000"


def _get(path, timeout=15):
    """GET JSON from running server"""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()), r.status


@pytest.mark.integration
class TestDecisionHubAPI:
    """决策中枢 Hub API"""

    def test_hub_returns_200(self):
        data, status = _get("/api/v1/decision/hub")
        assert status == 200

    def test_hub_has_jcs(self):
        data, _ = _get("/api/v1/decision/hub")
        assert "jcs" in data
        assert "score" in data["jcs"]
        assert 0 <= data["jcs"]["score"] <= 100

    def test_hub_has_snapshot(self):
        data, _ = _get("/api/v1/decision/hub")
        assert "snapshot" in data

    def test_hub_has_data_freshness(self):
        """V21.2: data_freshness 字段必须存在"""
        data, _ = _get("/api/v1/decision/hub")
        assert "data_freshness" in data
        freshness = data["data_freshness"]
        for key in ["dashboard", "aiae", "strategy", "global"]:
            assert key in freshness, f"Missing freshness key: {key}"
            assert "status" in freshness[key]
            assert freshness[key]["status"] in ("ok", "stale")

    def test_hub_has_action_plan(self):
        data, _ = _get("/api/v1/decision/hub")
        assert "action_plan" in data
        plan = data["action_plan"]
        assert "action_label" in plan
        assert "position_target" in plan

    def test_hub_has_global_temperature(self):
        data, _ = _get("/api/v1/decision/hub")
        assert "global_temperature" in data


@pytest.mark.integration
class TestAlertsAPI:
    """预警 API"""

    def test_alerts_returns_200(self):
        data, status = _get("/api/v1/decision/alerts?limit=20")
        assert status == 200

    def test_alerts_is_list(self):
        data, _ = _get("/api/v1/decision/alerts?limit=20")
        assert isinstance(data, (list, dict))


@pytest.mark.integration
class TestSwingGuardAPI:
    """波段守卫 API"""

    def test_swing_returns_200(self):
        data, status = _get("/api/v1/decision/swing-guard")
        assert status == 200

    def test_swing_has_data(self):
        data, _ = _get("/api/v1/decision/swing-guard")
        assert data.get("status") == "success"
        assert "data" in data

    def test_swing_has_etfs(self):
        data, _ = _get("/api/v1/decision/swing-guard")
        etfs = data.get("data", {})
        assert len(etfs) >= 5, f"Expected ≥5 ETFs, got {len(etfs)}"


@pytest.mark.integration
class TestDashboardAPI:
    """总览 Dashboard API"""

    def test_dashboard_returns_200(self):
        data, status = _get("/api/v1/dashboard-data")
        assert status == 200


@pytest.mark.integration
class TestERPTimingAPI:
    """ERP Timing API"""

    def test_erp_returns_200(self):
        data, status = _get("/api/v1/strategy/erp-timing")
        assert status == 200

    def test_erp_has_signal(self):
        data, _ = _get("/api/v1/strategy/erp-timing")
        assert data.get("status") == "success"
        inner = data.get("data", {})
        assert "signal" in inner
        sig = inner["signal"]
        assert "score" in sig
        assert "key" in sig

    def test_erp_has_dimensions(self):
        data, _ = _get("/api/v1/strategy/erp-timing")
        inner = data.get("data", {})
        assert "dimensions" in inner
        dims = inner["dimensions"]
        for d in ["erp_abs", "erp_pct", "m1_trend"]:
            assert d in dims, f"Missing dimension: {d}"


@pytest.mark.integration
class TestHealthAPI:
    """健康检查"""

    def test_health_returns_200(self):
        data, status = _get("/health")
        assert status == 200

    def test_health_has_uptime(self):
        data, _ = _get("/health")
        assert "uptime" in data or "uptime_seconds" in data or "status" in data
