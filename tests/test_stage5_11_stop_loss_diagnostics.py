"""Stage 5.11 stop-loss and entry-quality diagnostic tests."""
from datetime import datetime, timedelta, timezone

from backend.stage511 import _analyse_trades, _prepare_entry_context, run_stage511_stop_loss_diagnostics


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


def test_stage511_reports_stop_loss_excursions_and_post_exit_recovery():
    bars = [
        {"t": f"2026-01-01T00:{i*5:02d}:00Z", "o": 100, "h": h, "l": lo, "c": close, "v": 100}
        for i, (h, lo, close) in enumerate([
            (100.5, 99.5, 100), (101, 99.8, 100.5),
            (101, 98.0, 99), (100.8, 99, 100.2),
            (101.5, 100, 101), (102, 100, 101.5),
        ])
    ]
    trades = [{
        "entry_time": bars[1]["t"], "exit_time": bars[2]["t"],
        "entry_price": 100, "exit_price": 98.5,
        "exit_reason": "STOP_LOSS", "gross_pnl_usd": -0.15,
        "net_pnl_usd": -0.20,
    }]
    contexts = [{"hourly_trend": "MIXED", "volatility": "NORMAL",
                 "momentum_bucket": "FLAT", "momentum_3_atr": 0.0,
                 "prior_12bar_range_atr": 1.0, "atr": 1.0} for _ in bars]
    result = _analyse_trades(trades, bars, [1.0] * len(bars), contexts)
    assert result["summary"]["stop_loss_trades"] == 1
    assert result["summary"]["unmapped_trades"] == 0
    row = result["trade_ledger"][0]
    assert row["mae_r"] is not None
    assert row["hourly_trend_before_entry"] == "MIXED"
    assert row["recovery_max_price_change_after_stop"][3] > 0


def test_stage511_context_uses_completed_pre_entry_bars():
    bars = sample_bars(300)
    contexts = _prepare_entry_context(bars, [2.0] * len(bars))
    assert len(contexts) == len(bars)
    assert contexts[100]["momentum_3_atr"] is not None
    assert contexts[0]["momentum_3_atr"] is None
    assert contexts[100]["hourly_trend"] in {"BULL", "BEAR", "MIXED", "UNAVAILABLE"}


def test_stage511_report_keeps_holdout_sealed_and_execution_off():
    report = run_stage511_stop_loss_diagnostics(sample_bars(), requested_bars=6000)
    assert report["stage"] == "5.11"
    assert report["status"] == "TRAINING_STOP_LOSS_DIAGNOSTIC_NOT_VALIDATED"
    assert report["training_bars"] == 3600
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False
    assert report["candidate"]["diagnostics"]["summary"]["unmapped_trades"] == 0


def test_stage511_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage511_stop_loss_diagnostics(sample_bars(3000), requested_bars=3000)
