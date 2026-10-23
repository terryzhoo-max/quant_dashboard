"""Market-hour logic must use Beijing time regardless of the server's timezone."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.market_clock import CN_TZ, cn_now


def test_cn_now_is_utc_plus_8():
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = cn_now() - utc
    assert abs(delta - timedelta(hours=8)) < timedelta(seconds=5)


def test_cache_ttl_uses_beijing_clock():
    from services import cache_store
    with patch("services.cache_store.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 23, 10, 0, tzinfo=CN_TZ)  # 周五 北京 10:00 盘中
        assert cache_store.get_cache_ttl() == 300
        mock_dt.now.assert_called_with(CN_TZ)


def test_is_market_hours_uses_beijing_clock():
    from services import cache_service
    with patch("services.cache_service._datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 23, 22, 50, tzinfo=CN_TZ)  # 北京 22:50 = 芝加哥 09:50
        assert cache_service.is_market_hours() == "after"
        mock_dt.now.assert_called_with(CN_TZ)


def test_poller_default_clock_is_beijing():
    from services import realtime_poller
    with patch("services.realtime_poller.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 23, 22, 50, tzinfo=CN_TZ)
        assert realtime_poller.MarketSession.is_a_share_session() is False
        mock_dt.now.assert_called_with(CN_TZ)


def _cny_with(fred, disk):
    import dashboard_modules.fetch_macro as fm
    with patch.object(fm.requests, "get", side_effect=fm.requests.exceptions.RequestException("down")), \
         patch.object(fm, "_load_cny_disk", return_value=None), \
         patch.object(fm, "_fetch_cny_ecb", return_value=None), \
         patch.object(fm, "_fetch_cny_fred", return_value=fred), \
         patch.object(fm, "_cny_disk_observation", return_value=disk), \
         patch.object(fm, "_save_cny_disk") as saved:
        return fm.fetch_cny_for_dashboard(), saved


def test_cny_prefers_newer_cached_ecb_over_older_fred():
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rate, saved = _cny_with((6.6861, week_ago), (6.6702, today, "ecb:EUR_REFERENCE"))
    assert rate == 6.6702
    saved.assert_not_called()      # 不得用更旧的 FRED 观测覆盖缓存


def test_cny_uses_fred_when_it_is_newer_than_cache():
    today = datetime.now().isoformat()
    old = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
    rate, saved = _cny_with((6.69, today), (6.70, old, "ecb:EUR_REFERENCE"))
    assert rate == 6.69
    saved.assert_called_once()
