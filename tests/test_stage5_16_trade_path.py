"""Stage 5.16 OHLC trade-path diagnostics tests."""
from backend.stage516 import _analyse_trade_path, _summarize


def test_stage516_flags_same_bar_threshold_order_as_ambiguous():
    bars = [
        {"t":"2026-01-01T00:00:00Z","o":100,"h":101,"l":99,"c":100},
        {"t":"2026-01-01T00:05:00Z","o":100,"h":104,"l":96,"c":101},
        {"t":"2026-01-01T00:10:00Z","o":101,"h":102,"l":98,"c":99},
    ]
    trade = {
        "entry_time": bars[1]["t"], "exit_time": bars[2]["t"],
        "entry_price":100,"exit_price":99,"exit_reason":"STOP_LOSS",
        "gross_pnl_usd":-0.1,"net_pnl_usd":-0.12,
    }
    row = _analyse_trade_path(trade,bars,[2.0,2.0,2.0],{x["t"]:i for i,x in enumerate(bars)})
    assert row["mfe_r"] == 1.3333
    assert row["mae_r"] == 1.3333
    assert row["half_r_threshold_order"] == "SAME_BAR_ORDER_UNKNOWN"
    assert row["same_bar_order_ambiguous"] is True
    assert row["pre_exit_bar_mfe_r"] == 1.3333
    assert row["exit_bar_mae_r"] == 0.6667


def test_stage516_detects_favourable_first_by_bar_not_intrabar():
    bars = [
        {"t":"2026-01-01T00:00:00Z","o":100,"h":100.2,"l":99.8,"c":100},
        {"t":"2026-01-01T00:05:00Z","o":100,"h":102,"l":99.5,"c":101.5},
        {"t":"2026-01-01T00:10:00Z","o":101.5,"h":101.6,"l":98,"c":99},
    ]
    trade = {
        "entry_time": bars[0]["t"], "exit_time": bars[2]["t"],
        "entry_price":100,"exit_price":99,"exit_reason":"STOP_LOSS",
        "gross_pnl_usd":-0.1,"net_pnl_usd":-0.12,
    }
    row = _analyse_trade_path(trade,bars,[2.0,2.0,2.0],{x["t"]:i for i,x in enumerate(bars)})
    assert row["half_r_threshold_order"] == "FAVORABLE_FIRST"
    assert row["first_favourable_half_r_bar"] == 1
    assert row["first_adverse_half_r_bar"] == 2
    assert row["same_bar_order_ambiguous"] is False


def test_stage516_summary_keeps_ohlc_order_ambiguity_visible():
    rows = [
        {"mfe_r":1.0,"mae_r":1.2,"pre_exit_bar_mfe_r":0.5,"pre_exit_bar_mae_r":0.8,
         "exit_close_progress_r":-1.0,"bars_held_including_entry":3,
         "half_r_threshold_order":"SAME_BAR_ORDER_UNKNOWN"},
        {"mfe_r":0.8,"mae_r":0.9,"pre_exit_bar_mfe_r":0.7,"pre_exit_bar_mae_r":0.4,
         "exit_close_progress_r":-0.9,"bars_held_including_entry":2,
         "half_r_threshold_order":"FAVORABLE_FIRST"},
    ]
    summary = _summarize(rows)
    assert summary["trades"] == 2
    assert summary["same_bar_order_ambiguous_trades"] == 1
    assert summary["favourable_first_trades"] == 1
    assert "intrabar order" in summary["order_unknown_warning"]
