"""Deterministic tests for OHLC backtest entry and exit semantics."""
from backend.main import _backtest_exit_for_candle, run_ema_atr_backtest


def test_stop_gap_fills_at_open_not_better_stop_price():
    position = {"stop": 98.0, "target": 112.0}
    assert _backtest_exit_for_candle(position, {
        "o": 96.0, "h": 99.0, "l": 95.0
    }) == (96.0, "STOP_LOSS_GAP")


def test_both_stop_and_target_touched_assumes_stop_first():
    position = {"stop": 98.0, "target": 112.0}
    assert _backtest_exit_for_candle(position, {
        "o": 100.0, "h": 113.0, "l": 97.0
    }) == (98.0, "STOP_LOSS")


def test_target_gap_fills_at_open():
    position = {"stop": 98.0, "target": 112.0}
    assert _backtest_exit_for_candle(position, {
        "o": 114.0, "h": 116.0, "l": 113.0
    }) == (114.0, "TAKE_PROFIT_GAP")


def test_entry_candle_is_checked_for_stop_or_target():
    bars = []
    for i in range(22):
        price = 100.0 + i * 0.5
        bars.append({
            "t": f"2026-11-01T00:{i:02d}:00Z",
            "o": price, "h": price + 0.6, "l": price - 0.6,
            "c": price + 0.4, "v": 1,
        })
    # The signal is known at bar 21 close; the fill is bar 22 open.
    bars.append({
        "t": "2026-11-01T00:22:00Z",
        "o": 111.0, "h": 112.0, "l": 100.0, "c": 111.5, "v": 1,
    })
    for i in range(23, 60):
        price = 111.0
        bars.append({
            "t": f"2026-11-01T01:{i:02d}:00Z",
            "o": price, "h": price + 0.2, "l": price - 0.2,
            "c": price, "v": 1,
        })

    result = run_ema_atr_backtest(bars, starting_equity=100, notional_usd=10)
    assert result["trades"]
    first = result["trades"][0]
    assert first["entry_time"] == "2026-11-01T00:22:00Z"
    assert first["exit_time"] == first["entry_time"]
    assert first["exit_reason"] == "STOP_LOSS"



def test_slippage_is_charged_adversely_on_entry_and_exit():
    bars = []
    for i in range(22):
        price = 100.0 + i * 0.5
        bars.append({
            "t": f"2026-11-01T00:{i:02d}:00Z",
            "o": price, "h": price + 0.6, "l": price - 0.6,
            "c": price + 0.4, "v": 1,
        })
    bars.append({
        "t": "2026-11-01T00:22:00Z",
        "o": 111.0, "h": 112.0, "l": 100.0, "c": 111.5, "v": 1,
    })
    for i in range(23, 60):
        bars.append({
            "t": f"2026-11-01T01:{i:02d}:00Z",
            "o": 111.0, "h": 111.2, "l": 110.8, "c": 111.0, "v": 1,
        })

    baseline = run_ema_atr_backtest(bars, fee_rate=0.0, slippage_bps=0)
    slipped = run_ema_atr_backtest(bars, fee_rate=0.0, slippage_bps=10)
    assert baseline["trades"]
    assert slipped["metrics"]["estimated_slippage_usd"] > 0
    assert slipped["metrics"]["net_pnl_usd"] < baseline["metrics"]["net_pnl_usd"]
    assert "exit_breakdown" in slipped["metrics"]



def test_out_of_sample_start_index_blocks_training_period_entries():
    bars = []
    for i in range(100):
        price = 100.0 + i * 0.5
        bars.append({
            "t": f"2026-11-01T{i // 60:02d}:{i % 60:02d}:00Z",
            "o": price, "h": price + 0.6, "l": price - 0.6,
            "c": price + 0.4, "v": 1,
        })

    split = 70
    result = run_ema_atr_backtest(bars, start_index=split)
    first_possible_fill = bars[split + 1]["t"]
    assert result["trades"]
    assert all(trade["entry_time"] >= first_possible_fill for trade in result["trades"])


def test_out_of_sample_start_index_must_leave_a_fill_candle():
    import pytest

    bars = []
    for i in range(60):
        price = 100.0 + i * 0.5
        bars.append({
            "t": f"2026-11-01T{i // 60:02d}:{i % 60:02d}:00Z",
            "o": price, "h": price + 0.6, "l": price - 0.6,
            "c": price + 0.4, "v": 1,
        })

    with pytest.raises(ValueError, match="start_index"):
        run_ema_atr_backtest(bars, start_index=len(bars) - 1)
