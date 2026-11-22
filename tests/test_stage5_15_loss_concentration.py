"""Stage 5.15 loss concentration investigation regression tests."""
from datetime import datetime, timedelta, timezone

from backend.stage515 import _group_for, _investigate, run_stage515_loss_concentration_investigation


def sample_bars(count=12000):
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


def test_stage515_classifies_using_frozen_stage512_thresholds():
    assert _group_for({"breakout_volume_ratio": None}) == "FEATURE_UNAVAILABLE"
    assert _group_for({"breakout_volume_ratio": 1.2}) == "BREAKOUT_VOLUME_BELOW_1_5"
    assert _group_for({"breakout_volume_ratio": 2, "breakout_displacement_atr": 0.1}) == "WEAK_BREAKOUT_DISPLACEMENT"
    assert _group_for({"breakout_volume_ratio": 2, "breakout_displacement_atr": 0.2, "pullback_reclaim_distance_atr": 0.7}) == "LATE_RECLAIM_DISTANCE"
    assert _group_for({"breakout_volume_ratio": 2, "breakout_displacement_atr": 0.2, "pullback_reclaim_distance_atr": 0.3}) == "STANDARD_SETUP"


def test_stage515_accounts_loss_groups_and_fee_erased_winners():
    bars = sample_bars(120)
    trades = [
        {"entry_time": bars[20]["t"], "exit_time": bars[25]["t"], "exit_reason": "STOP_LOSS", "gross_pnl_usd": -0.10, "estimated_fees_usd": 0.02, "net_pnl_usd": -0.12},
        {"entry_time": bars[40]["t"], "exit_time": bars[45]["t"], "exit_reason": "TAKE_PROFIT", "gross_pnl_usd": 0.01, "estimated_fees_usd": 0.02, "net_pnl_usd": -0.01},
    ]
    features = [None] * len(bars)
    features[19] = {"breakout_volume_ratio": 1.0}
    features[39] = {"breakout_volume_ratio": 2.0, "breakout_displacement_atr": 0.2, "pullback_reclaim_distance_atr": 0.2}
    report = _investigate(trades, bars, features)
    assert report["summary"]["trades"] == 2
    assert report["summary"]["stop_loss_trades"] == 1
    assert report["summary"]["winners_erased_by_fees"] == 1
    assert len(report["entry_quality_by_exit_reason"]) == 2
    assert report["largest_negative_groups"][0]["group"] == "BREAKOUT_VOLUME_BELOW_1_5"


def test_stage515_full_report_keeps_holdout_sealed_and_execution_off():
    report = run_stage515_loss_concentration_investigation(sample_bars(), requested_bars=12000)
    assert report["stage"] == "5.15"
    assert report["status"] == "TRAINING_LOSS_CONCENTRATION_INVESTIGATION_NOT_VALIDATED"
    assert report["training_bars"] == 7200
    assert report["candidate"]["investigation"]["summary"]["trades"] == report["candidate"]["backtest_metrics"]["trades"]
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False


def test_stage515_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage515_loss_concentration_investigation(sample_bars(3000), requested_bars=3000)
