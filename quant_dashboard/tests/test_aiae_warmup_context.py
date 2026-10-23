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
    monkeypatch.setattr(warmup_pipeline, "current_overlay", lambda: {"status": "ok", "factor": 1.0})
    monkeypatch.setattr(
        warmup_pipeline.cache_manager,
        "set_json",
        lambda key, value, ttl_seconds=None: writes.update({key: value}),
    )

    warmup_pipeline.warmup_aiae_cache()

    assert writes["aiae_ctx"]["cap"] == 53
    assert writes["aiae_ctx"]["decision_locked"] is False


def test_aiae_warmup_publishes_vol_adjusted_cap(monkeypatch):
    """波动率刹车生效时, 发布的 cap 是有效上限, base_cap 保留 AIAE 原值。"""
    report = {
        "status": "success",
        "updated_at": "2026/9/6 18:21:24",
        "data_quality_score": 90,
        "decision_locked": False,
        "current": {"regime": 3, "aiae_v1": 21.54, "regime_info": {"cn": "中性"}},
        "position": {"matrix_position": 60, "decision_locked": False},
    }

    class FakeEngine:
        def refresh(self):
            return None

        def generate_report(self):
            return report

    writes = {}
    monkeypatch.setattr(aiae_engine, "get_aiae_engine", lambda: FakeEngine())
    monkeypatch.setattr(
        warmup_pipeline, "current_overlay",
        lambda: {"status": "ok", "factor": 0.8, "brake_on": True, "ratio": 2.5, "trigger_ratio": 2.0},
    )
    monkeypatch.setattr(
        warmup_pipeline.cache_manager,
        "set_json",
        lambda key, value, ttl_seconds=None: writes.update({key: value}),
    )

    warmup_pipeline.warmup_aiae_cache()

    ctx = writes["aiae_ctx"]
    assert ctx["base_cap"] == 60
    assert ctx["cap"] == 48
    assert ctx["vol_overlay"]["brake_on"] is True
