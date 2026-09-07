"""AIAE warmup must publish its safety context before dashboard warmup."""

import aiae_engine

from services import warmup_pipeline


def test_aiae_warmup_publishes_shared_context(monkeypatch):
    report = {
        "status": "success",
        "updated_at": "2026/9/6 18:21:24",
        "data_quality_score": 90,
        "decision_locked": False,
        "current": {"regime": 3, "aiae_v1": 21.54, "regime_info": {"cn": "中性"}},
        "position": {"matrix_position": 53, "decision_locked": False},
    }

    class FakeEngine:
        def refresh(self):
            return None

        def generate_report(self):
            return report

    writes = {}
    monkeypatch.setattr(aiae_engine, "get_aiae_engine", lambda: FakeEngine())
    monkeypatch.setattr(
        warmup_pipeline.cache_manager,
        "set_json",
        lambda key, value, ttl_seconds=None: writes.update({key: value}),
    )

    warmup_pipeline.warmup_aiae_cache()

    assert writes["aiae_ctx"]["cap"] == 53
    assert writes["aiae_ctx"]["decision_locked"] is False
