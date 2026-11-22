"""Stage 5.10 cost-edge diagnostics tests."""
from datetime import datetime, timedelta, timezone

from backend.stage510 import _trade_cost_profile, run_stage510_cost_edge_diagnostics


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


def test_stage510_counts_gross_winners_erased_by_fees_and_break_even_move():
    trades = [
        {
            "entry_time": "2026-01-01T00:05:00Z",
            "exit_time": "2026-01-01T00:10:00Z",
            "entry_price": 100.0, "exit_price": 100.2,
            "exit_reason": "TAKE_PROFIT",
        },
        {
            "entry_time": "2026-01-01T00:10:00Z",
            "exit_time": "2026-01-01T00:15:00Z",
            "entry_price": 100.0, "exit_price": 101.0,
            "exit_reason": "TAKE_PROFIT",
        },
        {
            "entry_time": "2026-01-01T00:15:00Z",
            "exit_time": "2026-01-01T00:20:00Z",
            "entry_price": 100.0, "exit_price": 99.0,
            "exit_reason": "STOP_LOSS",
        },
    ]
    bars = [
        {"t": "2026-01-01T00:00:00Z"},
        {"t": "2026-01-01T00:05:00Z"},
        {"t": "2026-01-01T00:10:00Z"},
        {"t": "2026-01-01T00:15:00Z"},
    ]
    profile = _trade_cost_profile(trades, [1.0] * 4, bars, 10.0, 0.0025)
    summary = profile["summary"]
    assert summary["trades"] == 3
    assert summary["gross_winning_trades"] == 2
    assert summary["gross_winners_erased_by_fees"] == 1
    assert summary["gross_winners_erased_share_percent"] == 50.0
    assert summary["gross_losing_trades"] == 1
    assert summary["median_break_even_price_move_bps"] > 0
    assert profile["gross_outcome_attribution"]["GROSS_WIN_ERASED_BY_FEES"]["trades"] == 1


def test_stage510_report_uses_training_only_and_keeps_execution_disabled():
    report = run_stage510_cost_edge_diagnostics(sample_bars(), requested_bars=6000)
    assert report["stage"] == "5.10"
    assert report["status"] == "TRAINING_COST_EDGE_DIAGNOSTIC_NOT_VALIDATED"
    assert report["training_bars"] == 3600
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["candidate"]["cost_edge"]["summary"]["trades"] == report["candidate"]["metrics"]["trades"]
    assert report["baseline"]["cost_edge"]["summary"]["trades"] == report["baseline"]["metrics"]["trades"]
    assert report["candidate"]["cost_edge"]["summary"]["estimated_slippage_is_embedded_in_fills"] is True
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False


def test_stage510_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage510_cost_edge_diagnostics(sample_bars(3000), requested_bars=3000)
