from backend.stage48 import build_stage48_diagnostics


def test_stage48_empty_trades_is_safe_and_explicit():
    bars = [{"t": "2026-01-01T00:00:00Z", "c": 100.0}]
    report = build_stage48_diagnostics(bars, [], [False], [None])
    assert report["trade_count"] == 0
    assert report["cost_attribution"]["net_pnl_usd"] == 0
    assert report["holding_time_minutes"]["median"] is None


def test_stage48_attributes_exit_costs_and_trade_duration():
    bars = [
        {"t": "2026-01-01T00:00:00Z", "c": 100.0},
        {"t": "2026-01-01T00:05:00Z", "c": 101.0},
        {"t": "2026-01-01T00:10:00Z", "c": 102.0},
    ]
    trades = [{
        "entry_time": "2026-01-01T00:05:00Z",
        "exit_time": "2026-01-01T00:10:00Z",
        "exit_reason": "STOP_LOSS",
        "gross_pnl_usd": 0.02,
        "estimated_fees_usd": 0.04,
        "estimated_slippage_usd": 0.01,
        "net_pnl_usd": -0.02,
    }]
    report = build_stage48_diagnostics(
        bars, trades, [False, True, False], [None, 0.5, None]
    )
    assert report["trade_count"] == 1
    assert report["cost_attribution"]["gross_positive_but_net_nonpositive_trades"] == 1
    assert report["cost_attribution"]["net_pnl_usd"] == -0.02
    assert report["exit_reason_breakdown"]["STOP_LOSS"]["trades"] == 1
    assert report["trades"][0]["holding_minutes"] == 5.0
