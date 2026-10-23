"""跟踪止盈 / 历史成交导入 API (只挂载本路由, 临时目录隔离真实数据)"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tests.test_trade_import import ROWS, tdx_bytes  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    import services.trade_import as ti
    import services.trailing_stop_service as svc
    from routers import trailing

    monkeypatch.setattr(ti, "LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(svc, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(svc, "STORE_PATH", str(tmp_path / "store.json"))
    monkeypatch.setattr(svc, "SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(svc, "ensure_prices_async", lambda codes, **k: {"started": False, "reason": "test"})
    monkeypatch.setattr(svc, "default_bars_loader", lambda code: None)
    monkeypatch.setattr(svc, "_market_context", lambda: ("RANGE", None))
    (tmp_path / "store.json").write_text(json.dumps({
        "import_date": "2026-10-22",
        "positions": {"002156.SZ": {"name": "通富微电", "amount": 400, "cost": 59.6}},
    }), encoding="utf-8")
    app = FastAPI()
    app.include_router(trailing.router)
    return TestClient(app)


def test_import_then_report(client):
    r = client.post("/api/v1/portfolio/trades/import", files={"file": ("h.txt", tdx_bytes(ROWS), "text/plain")}).json()
    assert r["status"] == "success" and r["data"]["added"] == 7
    rec = {x["ts_code"]: x for x in r["data"]["reconciliation"]}
    assert rec["002156.SZ"]["anchor_date"] == "2026-09-02"

    again = client.post("/api/v1/portfolio/trades/import", files={"file": ("h.txt", tdx_bytes(ROWS), "text/plain")}).json()
    assert again["data"]["added"] == 0 and again["data"]["duplicates"] == 7

    rep = client.get("/api/v1/portfolio/trailing-stops").json()
    assert rep["status"] == "success"
    assert rep["data"]["positions"][0]["anchor_date"] == "2026-09-02"
    assert client.get("/api/v1/portfolio/trades").json()["data"]["count"] == 7


def test_corrupted_upload_is_rejected(client):
    broken = tdx_bytes(ROWS).decode("utf-8", errors="replace").encode("utf-8")
    r = client.post("/api/v1/portfolio/trades/import", files={"file": ("bad.txt", broken, "text/plain")}).json()
    assert r["status"] == "error" and r["code"] == "ERR_ENCODING_CORRUPTED"


def test_rebaseline_requires_reason(client):
    r = client.post("/api/v1/portfolio/trailing-stops/002156.SZ/rebaseline", json={"reason": ""}).json()
    assert r["status"] == "error"
    s = client.post("/api/v1/portfolio/trailing-stops/002156.SZ/sleeve", json={"sleeve": "core"}).json()
    assert s["status"] == "success" and s["data"]["sleeve"] == "core"
