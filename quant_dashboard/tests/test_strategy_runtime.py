"""Production strategy-parameter contract and CI publication tests."""

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from services import strategy_params
from services.strategy_params import (
    DEFAULT_RUNTIME_CONFIG,
    get_erp_params,
    get_mr_params,
    get_position_cap,
    get_regime_rules,
    get_score_gate,
    get_single_position_cap,
    get_stop_loss,
    get_industry_validation_rules,
    get_industry_execution_rules,
    get_mr_lifecycle,
    publish_ci_parameters,
    validate_runtime_config,
)


class TestRuntimeParameterContract(unittest.TestCase):
    def test_default_config_is_valid_and_uses_one_unit_convention(self):
        validate_runtime_config(DEFAULT_RUNTIME_CONFIG)

        self.assertEqual(get_regime_rules()["ma_period"], 120)
        self.assertEqual(get_position_cap("mr", "RANGE"), 80)
        self.assertEqual(get_position_cap("mr", "RANGE", as_ratio=True), 0.8)
        self.assertEqual(get_stop_loss("momentum", "BEAR"), 0.05)
        self.assertEqual(get_score_gate("momentum", "BEAR"), 75)
        self.assertEqual(get_single_position_cap("momentum", "BEAR"), 12)
        validation = get_industry_validation_rules()
        execution = get_industry_execution_rules()
        self.assertEqual(validation["holding_days"], 20)
        self.assertEqual(
            validation["universe_history_path"],
            "config/industry_universe_history.json",
        )
        self.assertTrue(
            validation["promotion"]["require_point_in_time_universe"]
        )
        self.assertEqual(
            validation["regime_lifecycle"],
            {"BEAR": "disabled", "RANGE": "disabled", "BULL": "shadow", "CRASH": "disabled"},
        )
        self.assertEqual(execution["amount_unit"], "thousand_cny")
        self.assertEqual(execution["liquidity_lookback_days"], 20)
        self.assertEqual(execution["min_median_turnover_cny"], 50_000_000)
        self.assertEqual(execution["max_participation_rate"], 0.02)
        self.assertTrue(execution["pretrade_quote_required"])
        self.assertEqual(execution["constituent_max_age_days"], 45)
        self.assertEqual(execution["constituent_top_n"], 5)
        self.assertEqual(execution["constituent_weight_sum_bounds_pct"], [95, 105])

    def test_momentum_execution_limits_are_complete_and_fail_closed_in_crash(self):
        self.assertEqual(get_score_gate("momentum", "CRASH"), 999)
        self.assertEqual(get_position_cap("momentum", "CRASH"), 0)
        self.assertEqual(get_single_position_cap("momentum", "CRASH"), 0)

    def test_industry_validation_contract_rejects_unsafe_promotion_rules(self):
        invalid = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        invalid["strategies"]["momentum"]["validation"]["promotion"][
            "min_oos_win_rate"
        ] = 1.5

        with self.assertRaises(ValueError):
            validate_runtime_config(invalid)

    def test_industry_validation_rejects_weak_per_regime_contract(self):
        invalid = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        invalid["strategies"]["momentum"]["validation"]["promotion"][
            "min_regime_win_rate"
        ] = -0.1

        with self.assertRaises(ValueError):
            validate_runtime_config(invalid)

    def test_industry_validation_rejects_unknown_regime_lifecycle_state(self):
        invalid = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        invalid["strategies"]["momentum"]["validation"]["regime_lifecycle"][
            "BULL"
        ] = "live-ish"

        with self.assertRaises(ValueError):
            validate_runtime_config(invalid)

    def test_industry_execution_contract_rejects_unsafe_participation_rate(self):
        invalid = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        invalid["strategies"]["momentum"]["execution"][
            "max_participation_rate"
        ] = 0.5

        with self.assertRaises(ValueError):
            validate_runtime_config(invalid)

    def test_mr_parameters_use_canonical_trend_key_and_stop_loss(self):
        params = get_mr_params("RANGE")

        self.assertIn("N_trend", params)
        self.assertNotIn("ma_trend", params)
        self.assertEqual(params["stop_loss"], get_stop_loss("mr", "RANGE"))

    def test_mr_lifecycle_marks_expired_validation_stale(self):
        config = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        config["strategies"]["mr"]["lifecycle"]["BEAR"].update({
            "status": "validated",
            "next_validate_after": "2026-09-26T00:00:00+08:00",
        })

        with patch.object(strategy_params, "load_runtime_config", return_value=config):
            lifecycle = get_mr_lifecycle(
                "BEAR",
                as_of=datetime(2026, 10, 13, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

        self.assertEqual(lifecycle["configured_status"], "validated")
        self.assertEqual(lifecycle["status"], "stale")
        self.assertFalse(lifecycle["allow_new_entries"])
        self.assertEqual(lifecycle["reason"], "validation_expired")

    def test_mr_lifecycle_allows_entries_only_when_effectively_validated(self):
        config = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        config["strategies"]["mr"]["lifecycle"]["RANGE"].update({
            "status": "validated",
            "next_validate_after": "2026-12-12T00:00:00+08:00",
        })

        with patch.object(strategy_params, "load_runtime_config", return_value=config):
            lifecycle = get_mr_lifecycle(
                "RANGE",
                as_of=datetime(2026, 10, 13, tzinfo=ZoneInfo("Asia/Shanghai")),
            )

        self.assertEqual(lifecycle["status"], "validated")
        self.assertTrue(lifecycle["allow_new_entries"])
        self.assertEqual(lifecycle["reason"], "lifecycle_validated")

    def test_mr_lifecycle_contract_requires_all_trading_regimes(self):
        invalid = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        del invalid["strategies"]["mr"]["lifecycle"]["BULL"]

        with self.assertRaisesRegex(ValueError, "lifecycle must cover"):
            validate_runtime_config(invalid)

    def test_erp_weights_are_normalized(self):
        params = get_erp_params()
        weight_keys = ("w_erp_abs", "w_erp_pct", "w_m1", "w_vol", "w_credit")

        self.assertAlmostEqual(sum(params[key] for key in weight_keys), 1.0, places=8)

    def test_erp_runtime_module_reloads_published_values(self):
        import erp_params

        params = erp_params.reload_runtime_params()

        self.assertEqual(erp_params.BUY_THRESHOLD, params["buy_threshold"])
        self.assertEqual(erp_params.ERP_WINDOW, params["erp_window"])
        self.assertEqual(erp_params.WEIGHTS["m1_trend"], params["w_m1"])


class TestCIParameterPublication(unittest.TestCase):
    def _write_baseline(self, path: Path):
        path.write_text(
            json.dumps(DEFAULT_RUNTIME_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_mr_publication_is_atomic_versioned_and_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "strategy_runtime.json"
            self._write_baseline(target)
            old_data = json.loads(target.read_text(encoding="utf-8"))
            old_momentum = copy.deepcopy(old_data["strategies"]["momentum"])

            result = publish_ci_parameters({
                "run_id": "mr-test-1",
                "strategy": "mr",
                "regime": "RANGE",
                "new_params": {
                    "ma_trend": 90,
                    "rsi_period": 12,
                    "rsi_buy": 28,
                    "rsi_sell": 68,
                    "bias_buy": -2.2,
                    "stop_loss": 0.08,
                },
            }, path=target)

            published = json.loads(target.read_text(encoding="utf-8"))
            mr_params = published["strategies"]["mr"]["regimes"]["RANGE"]["params"]
            self.assertEqual(result["revision"], old_data["revision"] + 1)
            self.assertEqual(mr_params["N_trend"], 90)
            self.assertNotIn("ma_trend", mr_params)
            self.assertNotIn("stop_loss", mr_params)
            self.assertEqual(
                published["strategies"]["mr"]["stop_losses"]["RANGE"],
                0.08,
            )
            self.assertEqual(published["strategies"]["momentum"], old_momentum)
            self.assertTrue(target.with_suffix(target.suffix + ".bak").exists())

            repeated = publish_ci_parameters({
                "run_id": "mr-test-1",
                "strategy": "mr",
                "regime": "RANGE",
                "new_params": {
                    "N_trend": 90,
                    "rsi_period": 12,
                    "rsi_buy": 28,
                    "rsi_sell": 68,
                    "bias_buy": -2.2,
                    "stop_loss": 0.08,
                },
            }, path=target)
            self.assertTrue(repeated["already_published"])
            self.assertEqual(repeated["revision"], result["revision"])

    def test_invalid_publication_leaves_runtime_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "strategy_runtime.json"
            self._write_baseline(target)
            before = target.read_bytes()

            with self.assertRaises(ValueError):
                publish_ci_parameters({
                    "run_id": "erp-bad",
                    "strategy": "erp",
                    "new_params": {
                        "buy_threshold": 75,
                        "sell_threshold": 45,
                        "erp_window": 1008,
                        "stop_loss": 0,
                        "w_erp_abs": 0.9,
                        "w_erp_pct": 0.3,
                        "w_m1": 0.3,
                        "w_vol": 0.1,
                        "w_credit": 0.1,
                    },
                }, path=target)

            self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
