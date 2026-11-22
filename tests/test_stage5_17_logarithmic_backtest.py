"""Stage 5.17 logarithmic return backtest tests; read-only only."""
from datetime import datetime, timedelta, timezone
from math import exp, sin

from backend.stage517 import build_stage517_log_signals, run_stage517_log_backtest


def sample_bars(count=6000, scale=1.0):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(count):
        # Deterministic trend/cycle mix with nonzero volatility.
        log_price = 10.8 + 0.000015 * i + 0.0015 * sin(i / 17) + 0.0007 * sin(i / 5)
        close = exp(log_price) * scale
        out.append({
            "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
            "o": close * 0.9998, "h": close * 1.0012,
            "l": close * 0.9988, "c": close,
            "v": 100 + (i % 17) * 3,
        })
    return out


def test_log_signals_are_scale_invariant():
    a = build_stage517_log_signals(sample_bars())
    b = build_stage517_log_signals(sample_bars(scale=7.0))
    assert a["signals"] == b["signals"]
    assert a["diagnostics"]["signals"] == b["diagnostics"]["signals"]


def test_log_signal_timing_is_only_completed_15m_close():
    bars = sample_bars()
    result = build_stage517_log_signals(bars)
    for i, signal in enumerate(result["signals"]):
        if signal:
            stamp = datetime.fromisoformat(bars[i]["t"].replace("Z", "+00:00"))
            assert int((stamp + timedelta(minutes=5)).timestamp()) % 900 == 0


def test_stage517_backtest_keeps_holdout_sealed_and_no_execution():
    bars = sample_bars()
    report = run_stage517_log_backtest(bars, requested_bars=len(bars))
    assert report["stage"] == "5.17"
    assert report["status"] == "TRAINING_LOG_RETURN_BACKTEST_NOT_VALIDATED"
    assert report["training_bars"] == 3600
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False
    assert report["strategy"]["parameter_search"] is False
    assert report["metrics"]["trades"] >= 0


def test_stage517_rejects_invalid_nonpositive_close():
    bars = sample_bars()
    bars[500]["c"] = 0
    import pytest
    with pytest.raises(ValueError, match="positive"):
        build_stage517_log_signals(bars)
