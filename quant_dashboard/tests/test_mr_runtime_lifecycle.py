"""Runtime MR entries fail closed without suppressing position exits."""

import pytest

from engines.mean_reversion_engine import generate_signal


def _indicators(**overrides):
    values = {
        "close": 100.0,
        "ma20": 95.0,
        "ma_n": 90.0,
        "rsi": 20.0,
        "bias": -3.0,
        "percent_b": 0.2,
        "regime": "RANGE",
        "score_gate": 68,
        "allow_new_entries": False,
        "lifecycle_reason": "validation_expired",
        "regime_params": {
            "rsi_buy": 30,
            "rsi_sell": 65,
            "bias_buy": -2.5,
            "stop_loss": 0.10,
        },
    }
    values.update(overrides)
    return values


def test_stale_lifecycle_blocks_new_buy():
    assert generate_signal(_indicators(), score=90) == "no_entry"


@pytest.mark.parametrize(
    ("overrides", "score", "expected"),
    [
        ({"cost_price": 120.0}, 90, "stop_loss"),
        ({"rsi": 80.0}, 90, "sell"),
        ({"rsi": 50.0, "percent_b": 0.8, "ma20": 95.0}, 90, "sell_half"),
        ({"rsi": 50.0, "percent_b": 0.2, "ma20": 110.0}, 20, "sell_weak"),
    ],
)
def test_stale_lifecycle_does_not_block_exit(overrides, score, expected):
    assert generate_signal(_indicators(**overrides), score=score) == expected


def test_validated_lifecycle_allows_buy():
    indicators = _indicators(
        allow_new_entries=True,
        lifecycle_reason="lifecycle_validated",
    )

    assert generate_signal(indicators, score=90) == "buy"
