"""Stage 5.12 entry timing and false-breakout tests."""
from datetime import datetime, timedelta, timezone

from backend.stage512 import (
    _analyse_entry_quality, _build_entry_features,
    run_stage512_entry_quality_diagnostics,
)


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


def test_stage512_labels_post_entry_breakout_failure_as_outcome_only():
    bars = [
        {"t": f"2026-01-01T00:{i*5:02d}:00Z", "o": 101, "h": h, "l": lo, "c": close, "v": 100}
        for i, (h, lo, close) in enumerate([
            (102, 100, 101), (103, 100.5, 102), (102.5, 99, 99.5),
            (101, 98.5, 99), (100, 98, 99), (102, 98.5, 101),
        ])
    ]
    features = [None] * len(bars)
    features[0] = {
        "breakout_level": 100.0, "signal_atr": 2.0,
        "breakout_displacement_atr": 0.5, "breakout_volume_ratio": 2.0,
        "pullback_reclaim_distance_atr": 0.5, "entry_candle_body_atr": 0.5,
        "entry_volume_ratio": 1.8, "breakout_age_15m_bars": 1,
    }
    trades = [{
        "entry_time": bars[1]["t"], "exit_reason": "STOP_LOSS",
        "entry_price": 101.0, "gross_pnl_usd": -0.1, "net_pnl_usd": -0.15,
    }]
    result = _analyse_entry_quality(trades, bars, features)
    row = result["trade_ledger"][0]
    assert row["false_breakout_within_3_or_6_bars"] is True
    assert result["summary"]["false_breakout_count"] == 1
    assert result["summary"]["feature_unavailable_trades"] == 0


def test_stage512_feature_builder_returns_aligned_feature_slots():
    bars = sample_bars(1200)
    features = _build_entry_features(bars, [2.0] * len(bars))
    assert len(features) == len(bars)
    assert all(x is None or "breakout_level" in x for x in features)


def test_stage512_report_keeps_holdout_sealed_and_execution_off():
    report = run_stage512_entry_quality_diagnostics(sample_bars(), requested_bars=6000)
    assert report["stage"] == "5.12"
    assert report["status"] == "TRAINING_ENTRY_QUALITY_DIAGNOSTIC_NOT_VALIDATED"
    assert report["training_bars"] == 3600
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False
    assert report["candidate"]["diagnostics"]["summary"]["trades"] == report["candidate"]["metrics"]["trades"]


def test_stage512_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage512_entry_quality_diagnostics(sample_bars(3000), requested_bars=3000)
