"""AIAE fail-closed and health-status regression tests."""

import unittest
from datetime import datetime
from unittest.mock import patch

from dashboard_modules.decision.snapshot import _build_snapshot_from_cache
from services.aiae_safety import build_aiae_context, resolve_aiae_safety
from services.health_status import evaluate_aiae_context, evaluate_system_health


class TestAIAESafety(unittest.TestCase):
    def test_fallback_is_always_locked_even_with_optimistic_fields(self):
        quality, locked = resolve_aiae_safety({
            "status": "fallback",
            "data_quality_score": 100,
            "decision_locked": False,
        })

        self.assertEqual(quality, 0)
        self.assertTrue(locked)

    def test_success_without_quality_metadata_fails_closed(self):
        quality, locked = resolve_aiae_safety({"status": "success"})

        self.assertEqual(quality, 0)
        self.assertTrue(locked)

    def test_healthy_success_keeps_reported_quality(self):
        quality, locked = resolve_aiae_safety({
            "status": "success",
            "data_quality_score": 88,
            "decision_locked": False,
        })

        self.assertEqual(quality, 88)
        self.assertFalse(locked)

    def test_report_is_normalized_to_the_shared_context_contract(self):
        context = build_aiae_context({
            "status": "success",
            "updated_at": "2026/9/6 18:21:24",
            "data_quality_score": 90,
            "decision_locked": False,
            "current": {
                "regime": 3,
                "aiae_v1": 21.54,
                "regime_info": {"cn": "中性"},
                "fund_position": 83.33,
            },
            "position": {"matrix_position": 53, "decision_locked": False},
        })

        self.assertEqual(context["status"], "success")
        self.assertEqual(context["cap"], 53)
        self.assertEqual(context["regime"], 3)
        self.assertEqual(context["data_quality_score"], 90)
        self.assertFalse(context["decision_locked"])


class TestHealthStatus(unittest.TestCase):
    NOW = 2_000_000.0
    MAX_AGE = 300

    def _evaluate(self, **overrides):
        values = {
            "dashboard_ready": True,
            "dashboard_updated_at": self.NOW - 30,
            "aiae_ctx": {
                "status": "success",
                "data_quality_score": 90,
                "decision_locked": False,
                "updated_at": self.NOW - 60,
            },
            "now_ts": self.NOW,
            "dashboard_max_age_sec": self.MAX_AGE,
            "aiae_max_age_sec": 86_400,
        }
        values.update(overrides)
        return evaluate_system_health(**values)

    def test_aiae_context_contract_requires_fresh_unlocked_data(self):
        healthy = evaluate_aiae_context(
            {
                "status": "success",
                "data_quality_score": 90,
                "decision_locked": False,
                "updated_at": self.NOW - 60,
            },
            now_ts=self.NOW,
            max_age_sec=300,
        )
        stale = evaluate_aiae_context(
            {
                "status": "success",
                "data_quality_score": 90,
                "decision_locked": False,
                "updated_at": self.NOW - 301,
            },
            now_ts=self.NOW,
            max_age_sec=300,
        )

        self.assertTrue(healthy["usable"])
        self.assertFalse(stale["usable"])
        self.assertTrue(stale["decision_locked"])
        self.assertEqual(stale["reason"], "stale")

    def test_aiae_context_contract_reports_lock_reason(self):
        state = evaluate_aiae_context(
            {
                "status": "success",
                "data_quality_score": 90,
                "decision_locked": True,
                "updated_at": self.NOW - 60,
            },
            now_ts=self.NOW,
            max_age_sec=300,
        )

        self.assertFalse(state["usable"])
        self.assertEqual(state["reason"], "decision_locked")

    def test_fresh_high_quality_data_is_ok(self):
        result = self._evaluate()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reasons"], [])
        self.assertTrue(result["dashboard_fresh"])
        self.assertTrue(result["aiae_fresh"])

    def test_locked_aiae_is_degraded(self):
        result = self._evaluate(aiae_ctx={
            "status": "success",
            "data_quality_score": 90,
            "decision_locked": True,
            "updated_at": self.NOW - 60,
        })

        self.assertEqual(result["status"], "degraded")
        self.assertIn("aiae_decision_locked", result["reasons"])

    def test_legacy_context_without_status_fails_closed(self):
        result = self._evaluate(aiae_ctx={
            "data_quality_score": 90,
            "decision_locked": False,
            "updated_at": self.NOW - 60,
        })

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["data_quality_score"], 0)
        self.assertTrue(result["decision_locked"])

    def test_low_quality_aiae_is_degraded(self):
        result = self._evaluate(aiae_ctx={
            "status": "success",
            "data_quality_score": 25,
            "decision_locked": False,
            "updated_at": self.NOW - 60,
        })

        self.assertEqual(result["status"], "degraded")
        self.assertIn("aiae_low_data_quality", result["reasons"])

    def test_stale_dashboard_is_degraded(self):
        result = self._evaluate(dashboard_updated_at=self.NOW - self.MAX_AGE - 1)

        self.assertEqual(result["status"], "degraded")
        self.assertIn("dashboard_data_stale", result["reasons"])
        self.assertFalse(result["dashboard_fresh"])

    def test_stale_aiae_is_degraded(self):
        result = self._evaluate(aiae_ctx={
            "status": "success",
            "data_quality_score": 90,
            "decision_locked": False,
            "updated_at": self.NOW - 86_401,
        })

        self.assertEqual(result["status"], "degraded")
        self.assertIn("aiae_data_stale", result["reasons"])
        self.assertFalse(result["aiae_fresh"])

    def test_iso_aiae_timestamp_is_supported(self):
        result = self._evaluate(aiae_ctx={
            "status": "success",
            "data_quality_score": 90,
            "decision_locked": False,
            "updated_at": datetime.fromtimestamp(self.NOW - 60).isoformat(),
        })

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["aiae_age_sec"], 60)

    def test_engine_slash_timestamp_is_supported(self):
        now = datetime(2026, 9, 6, 18, 22, 24).timestamp()
        state = evaluate_aiae_context(
            {
                "status": "success",
                "data_quality_score": 90,
                "decision_locked": False,
                "updated_at": "2026/9/6 18:21:24",
            },
            now_ts=now,
            max_age_sec=300,
        )

        self.assertTrue(state["usable"])
        self.assertEqual(state["age_sec"], 60)

    def test_missing_dashboard_remains_starting(self):
        result = self._evaluate(
            dashboard_ready=False,
            dashboard_updated_at=None,
            aiae_ctx={},
        )

        self.assertEqual(result["status"], "starting")
        self.assertIn("dashboard_not_ready", result["reasons"])


class TestDecisionSnapshotFreshness(unittest.TestCase):
    @patch("dashboard_modules.decision.snapshot.time.time", return_value=2_000_000.0)
    @patch("services.cache_service.cache_manager")
    def test_stale_aiae_cache_locks_decision(self, cache_manager, _time):
        cache_manager.get_json.side_effect = lambda key: {
            "dashboard_data": None,
            "aiae_ctx": {
                "status": "success",
                "data_quality_score": 90,
                "decision_locked": False,
                "updated_at": 2_000_000.0 - 300_000,
                "regime": 2,
                "cap": 80,
            },
            "strategy_results": None,
        }.get(key)

        snapshot = _build_snapshot_from_cache()

        self.assertTrue(snapshot["decision_locked"])
        self.assertFalse(snapshot["aiae_fresh"])
        self.assertEqual(snapshot["aiae_unusable_reason"], "stale")


if __name__ == "__main__":
    unittest.main()
