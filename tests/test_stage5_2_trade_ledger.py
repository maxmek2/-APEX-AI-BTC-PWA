from backend import stage44


def test_stage44_report_exposes_training_and_holdout_trade_ledgers(monkeypatch):
    bars = [{"t": f"2026-01-01T00:{i % 60:02d}:00Z"} for i in range(3000)]

    monkeypatch.setattr(
        stage44,
        "build_stage44_signals",
        lambda _bars: {
            "signals": {"variant": [False] * len(_bars)},
            "atr_by_base": [1.0] * len(_bars),
            "diagnostics": {},
        },
    )

    def fake_backtest(run_bars, *_args, slippage_bps=5.0, **_kwargs):
        stamp = run_bars[-1]["t"] if run_bars else None
        trade = {
            "entry_time": stamp,
            "exit_time": stamp,
            "entry_price": 100.0,
            "exit_price": 101.0,
            "exit_reason": "TAKE_PROFIT",
            "gross_pnl_usd": 0.1,
            "estimated_fees_usd": 0.01,
            "estimated_slippage_usd": 0.0,
            "net_pnl_usd": 0.09,
            "slippage_bps_used": slippage_bps,
        }
        return {"metrics": {"trades": 1, "net_pnl_usd": 0.09}, "trades": [trade]}

    monkeypatch.setattr(stage44, "run_breakout_backtest", fake_backtest)
    report = stage44.run_stage44_report(bars, slippage_bps=5.0)
    item = report["reports"]["variant"]

    assert len(item["training_trades"]) == 1
    assert len(item["holdout_trades"]) == 1
    assert item["training_trades"][0]["exit_reason"] == "TAKE_PROFIT"
    assert item["holdout_trades"][0]["slippage_bps_used"] == 5.0
    assert item["holdout_entries_after_split"] is True
