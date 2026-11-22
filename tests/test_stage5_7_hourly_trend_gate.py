"""Stage 5.7 fixed hourly-trend-gate candidate tests."""
from datetime import datetime, timedelta, timezone

from backend.stage57 import (
    build_stage57_candidate_signals,
    run_stage57_candidate_report,
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


def test_stage57_candidate_is_subset_of_frozen_baseline():
    bars = sample_bars()
    from backend.stage44 import build_stage44_signals
    baseline = build_stage44_signals(bars)["signals"]["breakout_pullback_relvol"]
    candidate = build_stage57_candidate_signals(bars)
    assert len(candidate["signals"]) == len(bars)
    assert all(not signal or baseline[i] for i, signal in enumerate(candidate["signals"]))
    assert candidate["diagnostics"]["candidate_signals"] <= candidate["diagnostics"]["baseline_pullback_relvol_signals"]


def test_stage57_candidate_report_keeps_holdout_sealed():
    report = run_stage57_candidate_report(sample_bars(), requested_bars=6000)
    assert report["stage"] == "5.7"
    assert report["status"] == "TRAINING_CANDIDATE_DIAGNOSTIC_NOT_VALIDATED"
    assert report["training_bars"] == 3600
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["candidate"]["parameter_search"] is False
    assert report["candidate"]["holdout_based_selection"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False


def test_stage57_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage57_candidate_report(sample_bars(3000), requested_bars=3000)
