"""Stage 5.13 temporal stability regression tests."""
from datetime import datetime, timedelta, timezone

from backend.stage513 import _cohorts, _summarize, run_stage513_temporal_stability_audit


def sample_bars(count=6000):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(count):
        phase = (i // 900) % 4
        drift = 0.7 if phase == 0 else -0.55 if phase == 1 else 0.03 if phase == 2 else 0.12
        close = 50000 + i * drift + ((i % 19) - 9) * (2.5 if phase in (0, 1) else 0.8)
        out.append({
            "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
            "o": close - 0.5, "h": close + 2.5, "l": close - 2.5,
            "c": close, "v": 100 + (i % 11) * 4,
        })
    return out


def test_stage513_summarizes_trade_sample_and_losing_streak():
    trades = [
        {"net_pnl_usd": 1.0}, {"net_pnl_usd": -0.5},
        {"net_pnl_usd": -0.2}, {"net_pnl_usd": 0.3},
    ]
    report = _summarize(trades)
    assert report["trades"] == 4
    assert report["longest_losing_streak"] == 2
    assert report["minimum_30_trade_sample_met"] is False
    assert report["net_pnl_usd"] == 0.6


def test_stage513_assigns_each_trade_to_one_chronological_cohort():
    bars = sample_bars(6000)
    trades = [
        {"entry_time": bars[100]["t"], "net_pnl_usd": -1},
        {"entry_time": bars[3000]["t"], "net_pnl_usd": 2},
        {"entry_time": bars[5900]["t"], "net_pnl_usd": -0.5},
    ]
    report = _cohorts(trades, bars)
    assert [x["trades"] for x in report["cohorts"]] == [1, 1, 1]
    assert report["summary"]["populated_cohorts"] == 3
    assert report["summary"]["positive_net_cohorts"] == 1
    assert report["summary"]["all_three_cohorts_have_30_trades"] is False


def test_stage513_full_report_keeps_holdout_sealed_and_execution_off():
    report = run_stage513_temporal_stability_audit(sample_bars(), requested_bars=6000)
    assert report["stage"] == "5.13"
    assert report["status"] == "TRAINING_TEMPORAL_STABILITY_AUDIT_NOT_VALIDATED"
    assert report["training_bars"] == 3600
    assert len(report["candidate"]["cohorts"]) == 3
    assert len(report["baseline"]["cohorts"]) == 3
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False


def test_stage513_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage513_temporal_stability_audit(sample_bars(3000), requested_bars=3000)
