"""Correlation-cluster concentration must see through industry labels."""

import os
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd

from engines import audit_engine


def _factor_returns(seed=7, n=120):
    rng = np.random.default_rng(seed)
    a, b = rng.normal(0, 0.02, n), rng.normal(0, 0.02, n)
    cols = {}
    for i in range(5):          # 产业链 A: 半导体/PCB/科创50 式同向敞口
        cols[f"A{i}"] = a + rng.normal(0, 0.007, n)
    for i in range(3):          # 产业链 B
        cols[f"B{i}"] = b + rng.normal(0, 0.007, n)
    for i in range(2):          # 独立资产
        cols[f"I{i}"] = rng.normal(0, 0.02, n)
    return pd.DataFrame(cols, index=pd.bdate_range("2026-01-01", periods=n))


def test_clusters_group_co_moving_assets_across_labels():
    rets = _factor_returns()
    weights = {**{f"A{i}": 14.0 for i in range(5)}, **{f"B{i}": 7.0 for i in range(3)}, "I0": 5.0, "I1": 4.0}
    res = audit_engine._correlation_clusters(rets, weights, threshold=0.6, min_obs=60)
    top_codes, top_w, top_rho = res["clusters"][0]
    assert sorted(top_codes) == [f"A{i}" for i in range(5)]
    assert abs(top_w - 70.0) < 1e-9
    assert top_rho > 0.8
    assert len(res["clusters"]) == 4          # A, B, I0, I1
    assert 1.0 < res["n_eff"] < 4.0
    assert res["div_ratio"] > 1.0


def test_uncorrelated_assets_are_not_merged():
    rng = np.random.default_rng(1)
    rets = pd.DataFrame(rng.normal(0, 0.02, (120, 4)), columns=list("WXYZ"))
    res = audit_engine._correlation_clusters(rets, {c: 25.0 for c in "WXYZ"}, threshold=0.6, min_obs=60)
    assert len(res["clusters"]) == 4
    assert abs(res["n_eff"] - 4.0) < 1e-9


def test_positions_without_history_stay_separate_but_weighted():
    rets = _factor_returns()
    weights = {"A0": 30.0, "A1": 30.0, "NEW": 40.0}
    res = audit_engine._correlation_clusters(rets, weights, threshold=0.6, min_obs=60)
    assert res["uncovered"] == ["NEW"]
    assert res["clusters"][0][0] == ["NEW"] or abs(res["clusters"][0][1] - 60.0) < 1e-9
    assert sum(w for _, w, _ in res["clusters"]) == 100.0


def test_loader_masks_split_jumps():
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return
    with tempfile.TemporaryDirectory() as root:
        d = os.path.join(root, "data_lake", "daily_prices")
        os.makedirs(d)
        closes = [10.0] * 30 + [5.0] * 30          # 10转10 未复权造成的 -50% 伪跌
        pd.DataFrame({
            "trade_date": [d_.strftime("%Y%m%d") for d_ in pd.bdate_range("2026-01-01", periods=60)],
            "close": closes,
        }).to_parquet(os.path.join(d, "X.SZ.parquet"))
        with patch.object(audit_engine, "PROJECT_ROOT", root):
            rets = audit_engine._load_daily_returns(["X.SZ"], window=120)
    assert rets["X.SZ"].min() > -0.21
