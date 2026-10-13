"""Frozen out-of-sample evidence for mean-reversion parameter publication."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from engines.mean_reversion_engine import _classify_regime_from_series


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICE_DIR = PROJECT_ROOT / "data_lake" / "daily_prices"
BENCHMARK_CODE = "510300.SH"
OOS_START = date(2026, 3, 28)
MR_REGIMES = ("BEAR", "RANGE", "BULL")
MAX_TOTAL_POSITION = 0.85
RISK_FREE_RATE = 0.02
MIN_REGIME_DAYS = 60
MIN_TRADES = 5
ABSOLUTE_GATES = {
    "sharpe": 0.5,
    "max_dd": -25.0,
    "calmar": 0.3,
    "coverage": 15.0,
}
REGRESSION_TOLERANCE = 0.10


def classify_regimes(benchmark: pd.Series) -> pd.Series:
    """Classify each day using only the benchmark prefix available that day."""
    clean = benchmark.dropna().sort_index().astype(float)
    labels: list[str] = []
    values = clean.to_numpy()
    for end in range(1, len(values) + 1):
        if end < 120:
            labels.append("RANGE")
        else:
            labels.append(_classify_regime_from_series(values[:end])["regime"])
    return pd.Series(labels, index=clean.index, name="regime", dtype="object")


def _wilder_rsi(prices: pd.Series, period: int) -> pd.Series:
    values = prices.to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    if len(values) <= period:
        return pd.Series(result, index=prices.index)
    delta = np.diff(values, prepend=values[0])
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.full(len(values), np.nan)
    avg_loss = np.full(len(values), np.nan)
    avg_gain[period] = gains[1 : period + 1].mean()
    avg_loss[period] = losses[1 : period + 1].mean()
    for idx in range(period + 1, len(values)):
        avg_gain[idx] = (avg_gain[idx - 1] * (period - 1) + gains[idx]) / period
        avg_loss[idx] = (avg_loss[idx - 1] * (period - 1) + losses[idx]) / period
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(avg_loss < 1e-8, 100.0, avg_gain / avg_loss)
        result = 100.0 - 100.0 / (1.0 + ratio)
    return pd.Series(result, index=prices.index)


def _lag_positions(desired: pd.DataFrame) -> pd.DataFrame:
    """Execute close-derived signals on the following trading day."""
    return desired.shift(1).fillna(0.0)


def _signal_for_asset(
    prices: pd.Series,
    labels: pd.Series,
    params_by_regime: Mapping[str, Mapping[str, float]],
) -> tuple[pd.Series, dict[str, int]]:
    prices = prices.ffill().astype(float)
    ma_cache = {
        int(params["N_trend"]): prices.rolling(
            int(params["N_trend"]), min_periods=int(params["N_trend"])
        ).mean()
        for params in params_by_regime.values()
    }
    rsi_cache = {
        int(params["rsi_period"]): _wilder_rsi(
            prices, int(params["rsi_period"])
        )
        for params in params_by_regime.values()
    }
    signal = pd.Series(0.0, index=prices.index)
    entries = {state: 0 for state in MR_REGIMES}
    in_position = False
    entry_price = 0.0

    for idx in range(1, len(prices)):
        regime = str(labels.iloc[idx])
        price = float(prices.iloc[idx])
        if not math.isfinite(price):
            signal.iloc[idx] = signal.iloc[idx - 1]
            continue
        if regime == "CRASH":
            in_position = False
            continue
        params = params_by_regime[regime]
        ma = float(ma_cache[int(params["N_trend"])].iloc[idx])
        rsi = float(rsi_cache[int(params["rsi_period"])].iloc[idx])
        if not math.isfinite(ma) or not math.isfinite(rsi):
            signal.iloc[idx] = 1.0 if in_position else 0.0
            continue
        bias = (price - ma) / ma * 100.0 if ma > 0 else float("nan")
        if in_position:
            cumulative_return = price / entry_price - 1.0
            should_exit = (
                rsi >= float(params["rsi_sell"])
                or cumulative_return < -abs(float(params["stop_loss"]))
                or price < ma * 0.97
            )
            if should_exit:
                in_position = False
            else:
                signal.iloc[idx] = 1.0
        else:
            trend_ok = price > ma
            buy_trigger = (
                rsi <= float(params["rsi_buy"])
                or bias <= float(params["bias_buy"])
            )
            if trend_ok and buy_trigger:
                in_position = True
                entry_price = price
                signal.iloc[idx] = 1.0
                entries[regime] += 1
    return signal, entries


def _metrics(
    returns: pd.Series,
    weights: pd.DataFrame,
    trades: int,
) -> dict:
    returns = returns.fillna(0.0).astype(float)
    if returns.empty:
        return {
            "sharpe": 0.0,
            "max_dd": 0.0,
            "calmar": 0.0,
            "coverage": 0.0,
            "trades": int(trades),
            "total_trades": int(trades),
        }
    equity = (1.0 + returns).cumprod()
    max_drawdown = float(((equity - equity.cummax()) / equity.cummax()).min())
    std = float(returns.std(ddof=1))
    sharpe = (
        float((returns.mean() - RISK_FREE_RATE / 252.0) / std * np.sqrt(252))
        if std > 1e-12
        else 0.0
    )
    annual_return = float(equity.iloc[-1] ** (252.0 / len(equity)) - 1.0)
    calmar = annual_return / abs(max_drawdown) if abs(max_drawdown) > 1e-12 else 0.0
    coverage = float((weights.sum(axis=1) > 0.01).mean() * 100.0)
    return {
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_drawdown * 100.0, 2),
        "max_drawdown": round(max_drawdown, 6),
        "calmar": round(float(calmar), 3),
        "coverage": round(coverage, 1),
        "trades": int(trades),
        "total_trades": int(trades),
        "annual_return": round(annual_return * 100.0, 2),
    }


def run_parameter_set(
    *,
    prices: pd.DataFrame,
    benchmark: pd.Series,
    params_by_regime: Mapping[str, Mapping[str, float]],
    oos_start: date | str = OOS_START,
    cost_rate: float = 0.001,
    regime_labels: pd.Series | None = None,
) -> dict:
    """Backtest one complete regime parameter set on a frozen OOS window."""
    start = pd.Timestamp(oos_start)
    shared_index = prices.index.intersection(benchmark.dropna().index).sort_values()
    if shared_index.empty:
        raise ValueError("prices and benchmark have no shared dates")
    price_frame = prices.reindex(shared_index).sort_index()
    benchmark = benchmark.reindex(shared_index).ffill()
    labels = (
        regime_labels.reindex(shared_index)
        if regime_labels is not None
        else classify_regimes(benchmark).reindex(shared_index)
    )
    if not set(MR_REGIMES).issubset(params_by_regime):
        raise ValueError("parameter set must cover BEAR, RANGE, and BULL")

    desired = pd.DataFrame(0.0, index=shared_index, columns=price_frame.columns)
    trades_by_regime = {state: 0 for state in MR_REGIMES}
    for code in price_frame.columns:
        signal, entries = _signal_for_asset(
            price_frame[code], labels, params_by_regime
        )
        desired[code] = signal
        for state in MR_REGIMES:
            trades_by_regime[state] += entries[state]

    executed = _lag_positions(desired)
    raw_weights = executed * 0.10
    row_sum = raw_weights.sum(axis=1)
    scale = pd.Series(
        np.where(row_sum > MAX_TOTAL_POSITION, MAX_TOTAL_POSITION / row_sum, 1.0),
        index=shared_index,
    ).replace([np.inf, -np.inf], 1.0)
    weights = raw_weights.mul(scale, axis=0)
    asset_returns = price_frame.pct_change(fill_method=None).fillna(0.0)
    gross_returns = (weights * asset_returns).sum(axis=1)
    turnover = weights.diff().abs().fillna(weights.abs()).sum(axis=1)
    net_returns = gross_returns - turnover * float(cost_rate)

    evaluation_mask = shared_index >= start
    if not evaluation_mask.any():
        raise ValueError("OOS start is later than available data")
    eval_returns = net_returns.loc[evaluation_mask]
    eval_weights = weights.loc[evaluation_mask]
    eval_labels = labels.loc[evaluation_mask]
    result = {
        "oos_start": eval_returns.index[0].date().isoformat(),
        "data_through": eval_returns.index[-1].date().isoformat(),
        "cost_rate": float(cost_rate),
        "portfolio": _metrics(
            eval_returns,
            eval_weights,
            sum(trades_by_regime.values()),
        ),
        "by_regime": {},
    }
    for state in MR_REGIMES:
        mask = eval_labels == state
        metrics = _metrics(
            eval_returns.loc[mask],
            eval_weights.loc[mask],
            trades_by_regime[state],
        )
        metrics["regime_days"] = int(mask.sum())
        result["by_regime"][state] = metrics
    return result


def compare_incumbent_and_challenger(
    *,
    prices: pd.DataFrame,
    benchmark: pd.Series,
    incumbent: Mapping[str, Mapping[str, float]],
    challenger: Mapping[str, Mapping[str, float]],
    oos_start: date | str = OOS_START,
    cost_rate: float = 0.001,
) -> dict:
    labels = classify_regimes(benchmark.reindex(prices.index).ffill())
    incumbent_result = run_parameter_set(
        prices=prices,
        benchmark=benchmark,
        params_by_regime=incumbent,
        oos_start=oos_start,
        cost_rate=cost_rate,
        regime_labels=labels,
    )
    challenger_result = run_parameter_set(
        prices=prices,
        benchmark=benchmark,
        params_by_regime=challenger,
        oos_start=oos_start,
        cost_rate=cost_rate,
        regime_labels=labels,
    )
    if (
        incumbent_result["oos_start"] != challenger_result["oos_start"]
        or incumbent_result["data_through"] != challenger_result["data_through"]
    ):
        raise AssertionError("candidate validation windows differ")
    return {
        "oos_start": incumbent_result["oos_start"],
        "data_through": incumbent_result["data_through"],
        "incumbent": incumbent_result,
        "challenger": challenger_result,
    }


def _passes_absolute_gates(metrics: Mapping[str, float]) -> bool:
    return (
        float(metrics.get("sharpe", 0.0)) >= ABSOLUTE_GATES["sharpe"]
        and float(metrics.get("max_dd", -100.0)) >= ABSOLUTE_GATES["max_dd"]
        and float(metrics.get("calmar", 0.0)) >= ABSOLUTE_GATES["calmar"]
        and float(metrics.get("coverage", 0.0)) >= ABSOLUTE_GATES["coverage"]
        and int(metrics.get("trades", 0)) >= MIN_TRADES
    )


def _no_material_regression(
    incumbent: Mapping[str, float], challenger: Mapping[str, float]
) -> bool:
    incumbent_sharpe = float(incumbent.get("sharpe", 0.0))
    if incumbent_sharpe > 0 and float(challenger.get("sharpe", 0.0)) < (
        incumbent_sharpe * (1.0 - REGRESSION_TOLERANCE)
    ):
        return False
    incumbent_calmar = float(incumbent.get("calmar", 0.0))
    if incumbent_calmar > 0 and float(challenger.get("calmar", 0.0)) < (
        incumbent_calmar * (1.0 - REGRESSION_TOLERANCE)
    ):
        return False
    return True


def compare_regime(incumbent: Mapping[str, float], challenger: Mapping[str, float]) -> dict:
    if min(
        int(incumbent.get("regime_days", 0)),
        int(challenger.get("regime_days", 0)),
    ) < MIN_REGIME_DAYS:
        return {"decision": "INSUFFICIENT_EVIDENCE", "reason": "regime_days"}
    if max(
        int(incumbent.get("trades", 0)),
        int(challenger.get("trades", 0)),
    ) < MIN_TRADES:
        return {"decision": "INSUFFICIENT_EVIDENCE", "reason": "trades"}
    incumbent_passes = _passes_absolute_gates(incumbent)
    challenger_passes = _passes_absolute_gates(challenger)
    if challenger_passes and _no_material_regression(incumbent, challenger):
        return {"decision": "ACCEPT_CHALLENGER", "reason": "all_gates_passed"}
    if incumbent_passes:
        return {
            "decision": "REVALIDATE_INCUMBENT",
            "reason": "incumbent_remains_valid",
        }
    return {"decision": "REJECT", "reason": "absolute_gates_failed"}


def _read_price_file(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    if "trade_date" not in frame:
        raise ValueError(f"{path.name} has no trade_date")
    price_column = "adj_close" if "adj_close" in frame else "close"
    dates = pd.to_datetime(
        frame["trade_date"].astype(str).str[:8], format="%Y%m%d"
    )
    return pd.Series(
        frame[price_column].astype(float).to_numpy(),
        index=dates,
        name=path.stem,
    ).sort_index()


def load_frozen_oos_data(
    *,
    price_dir: Path | str = DEFAULT_PRICE_DIR,
    oos_start: date | str = OOS_START,
) -> tuple[pd.DataFrame, pd.Series]:
    """Load local-only prices and cap all series at their common latest date."""
    directory = Path(price_dir)
    files = sorted(directory.glob("*.parquet"))
    series = {}
    for path in files:
        try:
            values = _read_price_file(path)
        except (KeyError, TypeError, ValueError):
            continue
        if len(values) >= 120:
            series[path.stem] = values
    if BENCHMARK_CODE not in series:
        raise FileNotFoundError(f"missing benchmark {BENCHMARK_CODE}")
    common_latest = min(values.index.max() for values in series.values())
    warmup_start = pd.Timestamp(oos_start) - pd.Timedelta(days=400)
    frame = pd.DataFrame(series).sort_index()
    frame = frame.loc[(frame.index >= warmup_start) & (frame.index <= common_latest)]
    benchmark = frame.pop(BENCHMARK_CODE).ffill()
    frame = frame.ffill()
    usable = [column for column in frame if frame[column].notna().sum() >= 120]
    if not usable:
        raise ValueError("no assets have enough frozen OOS history")
    return frame[usable], benchmark


def run_frozen_oos_validation(
    *,
    incumbent: Mapping[str, Mapping[str, float]],
    challenger: Mapping[str, Mapping[str, float]],
    price_dir: Path | str = DEFAULT_PRICE_DIR,
    oos_start: date | str = OOS_START,
    cost_rate: float = 0.001,
) -> dict:
    prices, benchmark = load_frozen_oos_data(
        price_dir=price_dir, oos_start=oos_start
    )
    return compare_incumbent_and_challenger(
        prices=prices,
        benchmark=benchmark,
        incumbent=incumbent,
        challenger=challenger,
        oos_start=oos_start,
        cost_rate=cost_rate,
    )
