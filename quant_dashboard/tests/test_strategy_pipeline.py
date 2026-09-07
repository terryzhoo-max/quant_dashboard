"""CI acceptance must be coupled to successful parameter publication."""

import unittest
from unittest.mock import patch

from services.strategy_pipeline import _check_quality_gate, _publish_accepted_run


class TestAcceptedRunPublication(unittest.TestCase):
    def _run(self, status="ACCEPT"):
        return {
            "run_id": "ci-1",
            "strategy": "mr",
            "regime": "RANGE",
            "status": status,
            "quality_gate": [],
            "diff_summary": "candidate",
            "new_params": {"N_trend": 90},
        }

    @patch("services.strategy_pipeline.publish_ci_parameters")
    def test_accept_remains_accept_only_after_successful_publish(self, publish):
        publish.return_value = {"revision": 7}

        result = _publish_accepted_run(self._run())

        self.assertEqual(result["status"], "ACCEPT")
        self.assertEqual(result["publication"]["revision"], 7)
        self.assertTrue(result["quality_gate"][-1]["passed"])

    @patch("services.strategy_pipeline.publish_ci_parameters")
    def test_publish_failure_changes_accept_to_error(self, publish):
        publish.side_effect = OSError("disk full")

        result = _publish_accepted_run(self._run())

        self.assertEqual(result["status"], "ERROR")
        self.assertFalse(result["quality_gate"][-1]["passed"])
        self.assertIn("disk full", result["diff_summary"])

    @patch("services.strategy_pipeline.publish_ci_parameters")
    def test_review_is_not_published(self, publish):
        result = _publish_accepted_run(self._run(status="REVIEW"))

        publish.assert_not_called()
        self.assertEqual(result["status"], "REVIEW")


class TestQualityGate(unittest.TestCase):
    def test_zero_trade_candidate_fails_quality_gate(self):
        checks = _check_quality_gate({
            "sharpe_ratio": 1.2,
            "max_drawdown": -0.05,
            "calmar_ratio": 1.0,
            "total_trades": 0,
        })

        trade_check = next(check for check in checks if check["rule"].startswith("Trades"))
        self.assertFalse(trade_check["passed"])


if __name__ == "__main__":
    unittest.main()
