"""
AlphaCore P3-B · 自适应轮询器单元测试
========================================
"""

import pytest
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

from services.realtime_poller import (
    MarketSession,
    VIXJumpDetector,
    AdaptivePoller,
)


# ═══════════════════════════════════════════════════
#  交易时段判定
# ═══════════════════════════════════════════════════

class TestMarketSession:
    def test_a_share_morning(self):
        dt = datetime(2026, 5, 15, 10, 30)  # Thursday 10:30
        assert MarketSession.is_a_share_session(dt) is True

    def test_a_share_afternoon(self):
        dt = datetime(2026, 5, 15, 14, 50)  # Thursday 14:50
        assert MarketSession.is_a_share_session(dt) is True

    def test_a_share_closed(self):
        dt = datetime(2026, 5, 15, 16, 0)  # Thursday 16:00
        assert MarketSession.is_a_share_session(dt) is False

    def test_weekend(self):
        dt = datetime(2026, 5, 17, 10, 30)  # Saturday
        assert MarketSession.is_a_share_session(dt) is False

    def test_us_session_night(self):
        dt = datetime(2026, 5, 15, 22, 0)  # Thursday 22:00 Beijing
        assert MarketSession.is_us_session(dt) is True

    def test_us_session_early_morning(self):
        dt = datetime(2026, 5, 15, 3, 0)  # Thursday 03:00 Beijing
        assert MarketSession.is_us_session(dt) is True

    def test_us_session_daytime(self):
        dt = datetime(2026, 5, 15, 12, 0)  # Thursday noon
        assert MarketSession.is_us_session(dt) is False

    def test_polling_interval_a_share(self):
        dt = datetime(2026, 5, 15, 10, 30)
        assert MarketSession.get_polling_interval(dt) == 30

    def test_polling_interval_us(self):
        dt = datetime(2026, 5, 15, 22, 0)
        assert MarketSession.get_polling_interval(dt) == 60

    def test_polling_interval_closed(self):
        dt = datetime(2026, 5, 15, 17, 0)
        assert MarketSession.get_polling_interval(dt) == 300

    def test_polling_interval_weekend(self):
        dt = datetime(2026, 5, 17, 12, 0)
        assert MarketSession.get_polling_interval(dt) == 900


# ═══════════════════════════════════════════════════
#  VIX 跳变检测
# ═══════════════════════════════════════════════════

class TestVIXJumpDetector:
    def test_first_reading_no_jump(self):
        det = VIXJumpDetector(threshold_pct=5.0)
        assert det.check(18.5) is False

    def test_small_change_no_jump(self):
        det = VIXJumpDetector(threshold_pct=5.0)
        det.check(20.0)
        assert det.check(20.5) is False  # 2.5% < 5%

    def test_large_jump_triggers(self):
        det = VIXJumpDetector(threshold_pct=5.0, cooldown_seconds=0)
        det.check(20.0)
        assert det.check(22.0) is True  # 10% > 5%

    def test_cooldown_prevents_double_trigger(self):
        det = VIXJumpDetector(threshold_pct=5.0, cooldown_seconds=9999)
        det.check(20.0)
        det.check(22.0)  # triggers
        assert det.check(25.0) is False  # in cooldown

    def test_negative_jump_triggers(self):
        det = VIXJumpDetector(threshold_pct=5.0, cooldown_seconds=0)
        det.check(25.0)
        assert det.check(22.0) is True  # -12% > 5%

    def test_zero_vix_ignored(self):
        det = VIXJumpDetector()
        assert det.check(0) is False
        assert det.check(None) is False

    def test_get_status(self):
        det = VIXJumpDetector(threshold_pct=5.0)
        det.check(18.5)
        status = det.get_status()
        assert status["last_vix"] == 18.5
        assert status["threshold_pct"] == 5.0


# ═══════════════════════════════════════════════════
#  自适应轮询器
# ═══════════════════════════════════════════════════

class TestAdaptivePoller:
    def test_tick_calls_fn(self):
        mock_fn = MagicMock()
        poller = AdaptivePoller(tick_fn=mock_fn)
        poller._last_tick_time = 0  # force execution
        poller.tick()
        mock_fn.assert_called_once()
        assert poller._tick_count == 1

    def test_skip_when_interval_not_reached(self):
        mock_fn = MagicMock()
        poller = AdaptivePoller(tick_fn=mock_fn)
        poller._last_tick_time = time.time()  # just ticked
        poller.tick()
        mock_fn.assert_not_called()
        assert poller._skip_count == 1

    def test_error_counting(self):
        mock_fn = MagicMock(side_effect=RuntimeError("boom"))
        poller = AdaptivePoller(tick_fn=mock_fn)
        poller._last_tick_time = 0
        poller.tick()
        assert poller._consecutive_errors == 1
        assert poller._tick_count == 0

    def test_error_resets_on_success(self):
        call_count = [0]
        def flaky():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise RuntimeError("fail")
        
        poller = AdaptivePoller(tick_fn=flaky)
        poller._last_tick_time = 0
        poller.tick()  # fail 1
        assert poller._consecutive_errors == 1
        
        poller._last_tick_time = 0
        poller.tick()  # fail 2
        assert poller._consecutive_errors == 2
        
        poller._last_tick_time = 0
        poller.tick()  # success
        assert poller._consecutive_errors == 0

    def test_emergency_triggered_on_vix_jump(self):
        mock_fn = MagicMock()
        mock_emergency = MagicMock()
        poller = AdaptivePoller(tick_fn=mock_fn, emergency_fn=mock_emergency,
                               vix_threshold=5.0)
        poller._last_tick_time = 0
        
        # Mock VIX cache
        with patch.object(poller, '_get_current_vix', side_effect=[20.0]):
            poller.tick()
        
        # Set up VIX detector with previous value
        poller.vix_detector._last_vix = 20.0
        poller._last_tick_time = 0
        poller.vix_detector._last_trigger_time = 0
        
        with patch.object(poller, '_get_current_vix', return_value=25.0):
            poller.tick()
        
        mock_emergency.assert_called_once()
        assert poller._emergency_count == 1

    def test_get_status(self):
        poller = AdaptivePoller(tick_fn=lambda: None)
        status = poller.get_status()
        assert "current_interval" in status
        assert "session" in status
        assert "stats" in status
        assert "vix_detector" in status

    def test_degraded_mode_on_max_errors(self):
        """连续错误超过阈值后进入降频模式"""
        mock_fn = MagicMock(side_effect=RuntimeError("fail"))
        poller = AdaptivePoller(tick_fn=mock_fn, max_consecutive_errors=3)
        
        for _ in range(5):
            poller._last_tick_time = 0
            poller.tick()
        
        assert poller._consecutive_errors == 5
        
        # Now the poller should skip (degraded mode)
        poller._last_tick_time = time.time() - 10  # recent
        mock_fn.reset_mock()
        poller.tick()
        mock_fn.assert_not_called()  # skipped due to degraded
