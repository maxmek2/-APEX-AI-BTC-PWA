"""Stage 5.8 training-only execution diagnostics tests."""
from datetime import datetime, timedelta, timezone

from backend.stage58 import _session, run_stage58_execution_diagnostics


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


def test_stage58_session_boundaries_are_utc():
    assert _session("2026-01-01T00:00:00Z") == "ASIA_00_07_UTC"
    assert _session("2026-01-01T07:00:00Z") == "EUROPE_07_13_UTC"
    assert _session("2026-01-01T13:00:00Z") == "US_13_21_UTC"
    assert _session("2026-01-01T21:00:00Z") == "LATE_21_24_UTC"


def test_stage58_report_is_training_only_and_diagnoses_candidate():
    report = run_stage58_execution_diagnostics(sample_bars(), requested_bars=6000)
    assert report["stage"] == "5.8"
    assert report["status"] == "TRAINING_EXECUTION_DIAGNOSTIC_NOT_VALIDATED"
    assert report["training_bars"] == 3600
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["candidate"]["parameters_frozen"] is True
    assert report["candidate"]["parameter_search"] is False
    assert "exit_reason_attribution" in report["training"]
    assert "entry_session_attribution_utc" in report["training"]
    assert "entry_regime_attribution" in report["training"]
    assert "holding_duration_attribution" in report["training"]
    assert "entry_gap_attribution" in report["training"]
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False


def test_stage58_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage58_execution_diagnostics(sample_bars(3000), requested_bars=3000)
