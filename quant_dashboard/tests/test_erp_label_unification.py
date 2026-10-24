"""Homepage ERP label must use the same valuation zone as the ERP chart."""

from unittest.mock import MagicMock, patch


def _report(zone, label, erp=6.13, pct=76.2):
    snap = {"erp_value": erp, "erp_percentile": pct}
    if zone is not None:
        snap.update(valuation_zone=zone, valuation_zone_label=label)
    return {"status": "success", "current_snapshot": snap,
            "signal": {"key": "hold", "label": "标配持有", "score": 68.1}}


def _real_erp(report):
    from dashboard_modules import market_temp
    eng = MagicMock()
    eng.compute_signal.return_value = report
    with patch.object(market_temp, "get_erp_engine", return_value=eng):
        return market_temp.get_real_erp_data()


def test_label_uses_valuation_zone():
    out = _real_erp(_report("over", "超配区"))
    assert out["valuation_label"] == "超配区"          # 旧规则会给出 "极度低估"
    assert out["valuation_zone"] == "over"
    assert out["valuation_source"] == "pit_zone"


def test_label_falls_back_to_legacy_blend_without_zone():
    out = _real_erp(_report(None, None))
    assert out["valuation_label"] == "极度低估"
    assert out["valuation_source"] == "legacy_blend"
