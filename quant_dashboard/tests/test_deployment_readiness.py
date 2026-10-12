"""Deployment readiness must be separate from trading-data health."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from services.deployment_readiness import evaluate_deployment_readiness


ROOT = Path(__file__).parents[1]


def _health_payload(*, status="ok", dashboard_status="ready", dashboard_fresh=True):
    return {
        "status": status,
        "health_reasons": [],
        "freshness": {"dashboard": {"fresh": dashboard_fresh}},
        "engines": {"dashboard": {"status": dashboard_status}},
    }


class TestDeploymentReadiness(unittest.TestCase):
    def test_healthy_service_is_ready(self):
        result = evaluate_deployment_readiness(_health_payload())

        self.assertTrue(result["ready"])
        self.assertEqual(result["mode"], "healthy")

    def test_safe_business_degradation_does_not_block_deployment(self):
        payload = _health_payload(status="degraded")
        payload["health_reasons"] = ["industry_data_locked"]

        result = evaluate_deployment_readiness(payload)

        self.assertTrue(result["ready"])
        self.assertEqual(result["mode"], "safe_degraded")
        self.assertEqual(result["health_reasons"], ["industry_data_locked"])

    def test_starting_service_is_not_ready(self):
        payload = _health_payload(
            status="starting",
            dashboard_status="cold",
            dashboard_fresh=False,
        )
        payload["health_reasons"] = ["dashboard_not_ready"]

        result = evaluate_deployment_readiness(payload)

        self.assertFalse(result["ready"])
        self.assertEqual(result["mode"], "not_ready")

    def test_stale_dashboard_is_not_ready_even_when_service_is_degraded(self):
        payload = _health_payload(
            status="degraded",
            dashboard_status="stale",
            dashboard_fresh=False,
        )
        payload["health_reasons"] = ["dashboard_data_stale"]

        result = evaluate_deployment_readiness(payload)

        self.assertFalse(result["ready"])

    def test_cli_emits_machine_readable_decision(self):
        payload = _health_payload(status="degraded")
        payload["health_reasons"] = ["aiae_decision_locked"]

        completed = subprocess.run(
            [sys.executable, "-m", "services.deployment_readiness"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            cwd=ROOT,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["mode"], "safe_degraded")


if __name__ == "__main__":
    unittest.main()
