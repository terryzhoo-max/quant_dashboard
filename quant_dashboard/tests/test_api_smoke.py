"""
AlphaCore · API 冒烟测试
=========================
使用 FastAPI TestClient 验证核心 API 端点可达性
不依赖 Tushare/FRED 等外部服务

运行方式: python -m pytest tests/test_api_smoke.py -v
(需独立运行，不与 unit tests 混跑，避免 APScheduler 线程冲突)
"""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    """创建 TestClient (scope=module 避免重复启动)"""
    import os
    os.environ["AC_TESTING"] = "1"  # 标记测试环境
    # 延迟导入避免 top-level side effects
    from main import app
    c = TestClient(app)
    yield c
    # 清理: 停止 scheduler 避免线程泄漏
    if hasattr(app.state, "scheduler") and app.state.scheduler.running:
        app.state.scheduler.shutdown(wait=False)
    os.environ.pop("AC_TESTING", None)


class TestStaticRoutes:
    """静态页面路由"""

    def test_root_redirect(self, client):
        resp = client.get("/", follow_redirects=False)
        # 可能是 200 (直接返回 index.html) 或 307 redirect
        assert resp.status_code in (200, 307)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("ok", "starting")


class TestDashboardAPI:
    """量化总览 API"""

    def test_dashboard_data(self, client):
        resp = client.get("/api/v1/dashboard-data")
        assert resp.status_code == 200
        data = resp.json()
        # 初始可能无缓存，返回 calculating 状态
        assert data.get("status") in ("success", "calculating", "warming_up")


class TestRouterRegistration:
    """验证 router 正确注册 (不返回 404)"""

    def test_market_regime_reachable(self, client):
        """GET /api/v1/market/regime 应返回 200 (不再 404)"""
        resp = client.get("/api/v1/market/regime")
        # 可能返回 200 (成功) 或 500 (Tushare 未连接)，但不应是 404
        assert resp.status_code != 404, f"market/regime 仍然 404! Batch 1 修复未生效"

    def test_industry_tracking_reachable(self, client):
        """GET /api/v1/industry-tracking 应返回 200 (不再 404)"""
        resp = client.get("/api/v1/industry-tracking")
        assert resp.status_code != 404, f"industry-tracking 仍然 404!"

    def test_factor_analysis_method(self, client):
        """POST /api/v1/factor-analysis 应返回 200/422 (不再 405)"""
        resp = client.post("/api/v1/factor-analysis", json={
            "factor_name": "roe",
            "stock_pool": "top30",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31"
        })
        # 422 (validation) 或 200 (成功) 或 500 (数据源不可用) 都可以，但不应是 405
        assert resp.status_code != 405, f"factor-analysis 仍然 405!"

    def test_erp_timing_reachable(self, client):
        resp = client.get("/api/v1/strategy/erp-timing")
        assert resp.status_code != 404

    def test_aiae_report_reachable(self, client):
        resp = client.get("/api/v1/aiae/report")
        assert resp.status_code != 404


class TestOpenAPISchema:
    """验证 OpenAPI 文档可用"""

    def test_docs(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        # 验证关键路径存在于 schema 中
        paths = list(schema["paths"].keys())
        assert "/api/v1/dashboard-data" in paths
