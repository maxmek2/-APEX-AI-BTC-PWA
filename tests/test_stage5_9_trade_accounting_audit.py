"""Stage 5.9 independent trade-accounting audit tests."""
from datetime import datetime, timedelta, timezone

from backend.stage59 import audit_trade_ledger, run_stage59_accounting_audit


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


def test_stage59_recomputes_fill_fees_slippage_and_net_pnl():
    entry, exit_price, notional, fee, slip = 100.1, 102.0, 10.0, 0.0025, 5.0
    qty = notional / entry
    gross = (exit_price - entry) * qty
    fees = (entry + exit_price) * qty * fee
    slip_rate = slip / 10000
    reference_entry = entry / (1 + slip_rate)
    raw_exit = exit_price / (1 - slip_rate)
    slippage_cost = (entry - reference_entry) * qty + (raw_exit - exit_price) * qty
    trade = {
        "entry_time": "2026-01-01T00:05:00Z",
        "exit_time": "2026-01-01T00:10:00Z",
        "entry_price": entry, "exit_price": exit_price,
        "exit_reason": "TAKE_PROFIT",
        "gross_pnl_usd": round(gross, 4),
        "estimated_fees_usd": round(fees, 4),
        "estimated_slippage_usd": round(slippage_cost, 4),
        "net_pnl_usd": round(gross - fees, 4),
    }
    bars = [
        {"t": "2026-01-01T00:00:00Z"},
        {"t": "2026-01-01T00:05:00Z"},
    ]
    result = audit_trade_ledger([trade], [2.0, 2.0], bars, notional, fee, slip)
    assert result["status"] == "PASS"
    assert result["discrepancy_count"] == 0
    assert result["summary"]["trades_audited"] == 1


def test_stage59_flags_accounting_discrepancy():
    trade = {
        "entry_time": "2026-01-01T00:05:00Z",
        "exit_time": "2026-01-01T00:10:00Z",
        "entry_price": 100.0, "exit_price": 102.0,
        "exit_reason": "TAKE_PROFIT",
        "gross_pnl_usd": 999.0,
        "estimated_fees_usd": 0.05,
        "estimated_slippage_usd": 0.01,
        "net_pnl_usd": 998.95,
    }
    bars = [
        {"t": "2026-01-01T00:00:00Z"},
        {"t": "2026-01-01T00:05:00Z"},
    ]
    result = audit_trade_ledger([trade], [2.0, 2.0], bars, 10.0, 0.0025, 5.0)
    assert result["status"] == "FAIL"
    assert result["discrepancy_count"] > 0


def test_stage59_report_keeps_holdout_sealed_and_execution_off():
    report = run_stage59_accounting_audit(sample_bars(), requested_bars=6000)
    assert report["stage"] == "5.9"
    assert report["status"] == "TRAINING_ACCOUNTING_AUDIT_COMPLETE"
    assert report["training_bars"] == 3600
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False


def test_stage59_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage59_accounting_audit(sample_bars(3000), requested_bars=3000)
