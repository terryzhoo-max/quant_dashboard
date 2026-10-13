"""CI acceptance must be coupled to successful parameter publication."""

import unittest
from unittest.mock import patch

from services.strategy_pipeline import (
    _check_quality_gate,
    _publish_accepted_run,
    run_mr_ci,
)


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

    @patch("services.strategy_pipeline.publish_ci_parameters")
    def test_revalidated_incumbent_is_published(self, publish):
        publish.return_value = {"revision": 8}

        result = _publish_accepted_run(self._run(status="REVALIDATED"))

        publish.assert_called_once()
        self.assertEqual(result["publication"]["revision"], 8)


class TestMrDryRun(unittest.TestCase):
    @patch("services.strategy_pipeline.ac_db.save_ci_run")
    @patch("services.strategy_pipeline._publish_accepted_run")
    @patch("services.strategy_pipeline.run_frozen_oos_validation")
    @patch("strategies.mr_per_regime_optimizer.optimize_regime")
    def test_dry_run_neither_publishes_nor_persists(
        self, optimize, validate, publish, save
    ):
        optimize.return_value = {
            "params": {
                "N_trend": 90,
                "rsi_period": 14,
                "rsi_buy": 35,
                "rsi_sell": 70,
                "bias_buy": -2.0,
                "stop_loss": 0.08,
            }
        }
        metrics = {
            "sharpe": 1.0,
            "max_dd": -10.0,
            "calmar": 0.8,
            "coverage": 30.0,
            "trades": 10,
            "regime_days": 80,
        }
        validate.return_value = {
            "oos_start": "2026-03-28",
            "data_through": "2026-10-12",
            "incumbent": {"by_regime": {"RANGE": metrics}},
            "challenger": {"by_regime": {"RANGE": metrics}},
        }

        result = run_mr_ci("RANGE", dry_run=True)

        self.assertTrue(result[0]["dry_run"])
        publish.assert_not_called()
        save.assert_not_called()


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
