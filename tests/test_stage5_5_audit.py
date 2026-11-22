"""Stage 5.5 historical data and transaction-cost audit tests."""
from datetime import datetime, timedelta, timezone

from backend.stage55 import audit_bar_integrity, reconcile_trade_costs


def sample_bars(count=5):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    return [{
        "t":(start+timedelta(minutes=5*i)).isoformat().replace("+00:00","Z"),
        "o":100+i,"h":102+i,"l":99+i,"c":101+i,"v":10+i
    } for i in range(count)]


def test_stage55_accepts_clean_five_minute_bars():
    report=audit_bar_integrity(sample_bars())
    assert report["structural_integrity_passed"] is True
    assert report["duplicate_timestamps"] == 0
    assert report["estimated_missing_5m_intervals"] == 0


def test_stage55_detects_duplicate_and_invalid_ohlc():
    data=sample_bars()
    data[2]=dict(data[1])
    data[3]["h"]=data[3]["l"]-1
    report=audit_bar_integrity(data)
    assert report["duplicate_timestamps"] == 1
    assert report["invalid_ohlc_bars"] == 1
    assert report["structural_integrity_passed"] is False


def test_stage55_detects_missing_five_minute_intervals():
    data=sample_bars()
    data.pop(2)
    report=audit_bar_integrity(data)
    assert report["estimated_missing_5m_intervals"] == 1
    assert report["observed_gap_count"] == 1


def test_stage55_reconciles_costs_without_double_counting_slippage():
    trades=[{
        "gross_pnl_usd":1.0,"estimated_fees_usd":0.1,
        "estimated_slippage_usd":0.04,"net_pnl_usd":0.9
    }]
    metrics={
        "gross_pnl_usd":1.0,"estimated_fees_usd":0.1,
        "estimated_slippage_usd":0.04,"net_pnl_usd":0.9
    }
    result=reconcile_trade_costs(trades,metrics)
    assert result["reconciliation_passed"] is True
    assert result["net_equals_gross_minus_fees"] is True
    assert result["estimated_slippage_usd"] == 0.04
