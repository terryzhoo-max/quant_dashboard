import pytest

from services.fred_guard import (
    FredCircuitOpenError,
    FredGuard,
    FredRateLimitError,
    should_retry_fred_error,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limit_error_opens_circuit_and_blocks_next_call():
    clock = FakeClock()
    guard = FredGuard(
        min_interval_seconds=0,
        cooldown_seconds=60,
        time_fn=clock.time,
        sleep_fn=clock.sleep,
    )

    with pytest.raises(FredRateLimitError):
        guard.call("DGS10", lambda: (_ for _ in ()).throw(Exception("Too Many Requests")))

    assert guard.get_status()["state"] == "open"

    called = False

    def should_not_run():
        nonlocal called
        called = True

    with pytest.raises(FredCircuitOpenError):
        guard.call("DGS2", should_not_run)

    assert called is False


def test_successful_calls_are_serialized_by_min_interval():
    clock = FakeClock()
    guard = FredGuard(
        min_interval_seconds=2.5,
        cooldown_seconds=60,
        time_fn=clock.time,
        sleep_fn=clock.sleep,
    )

    assert guard.call("DGS10", lambda: "first") == "first"
    assert guard.call("DGS2", lambda: "second") == "second"

    assert clock.sleeps == [2.5]
    status = guard.get_status()
    assert status["total_calls"] == 2
    assert status["state"] == "closed"


def test_fred_guard_errors_are_not_retryable():
    assert should_retry_fred_error(Exception("temporary network issue")) is True
    assert should_retry_fred_error(FredRateLimitError("Too Many Requests")) is False
    assert should_retry_fred_error(
        FredCircuitOpenError("FRED circuit open for 300s after rate limit")
    ) is False


def test_process_default_fred_guard_is_conservative():
    from services.fred_guard import fred_guard

    status = fred_guard.get_status()

    assert status["min_interval_sec"] >= 3.0
    assert status["cooldown_sec"] >= 600.0


def test_warmup_retry_stops_immediately_when_fred_circuit_is_open(monkeypatch):
    from services import warmup_pipeline

    attempts = 0
    sleeps = []

    def fail_with_open_circuit():
        nonlocal attempts
        attempts += 1
        raise FredCircuitOpenError("FRED circuit open for 300s after rate limit")

    monkeypatch.setattr(warmup_pipeline.time, "sleep", sleeps.append)

    assert warmup_pipeline.with_retry(
        fail_with_open_circuit,
        "FRED_Warmup",
        max_retries=3,
        delay=60,
    ) is False
    assert attempts == 1
    assert sleeps == []
