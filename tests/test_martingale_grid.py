from backend.martingale_grid import build_signal, run_backtest


def bars_up(count=80):
    out=[]
    price=100.0
    for i in range(count):
        old=price
        price += 0.20
        out.append({"t":f"2026-11-01T{i//12:02d}:{(i%12)*5:02d}:00Z",
                    "o":old,"h":price+0.05,"l":old-0.05,"c":price,"v":1})
    return out


def test_signal_requires_rsi_above_55_and_latest_bearish_candle():
    bars=bars_up(40)
    bars[-1]["o"]=bars[-1]["c"]+0.05
    bars[-1]["c"]=bars[-1]["o"]-0.02
    result=build_signal(bars)
    assert result["rsi14"] > 55
    assert result["signal"] == "SHORT_GRID_SETUP"
    assert result["broker_orders_enabled"] is False


def test_grid_adds_second_leg_and_closes_basket():
    bars=bars_up(40)
    bars[-1]["o"]=bars[-1]["c"]+0.05
    bars[-1]["c"]=bars[-1]["o"]-0.02
    entry=bars[-1]["c"]+0.03
    bars.append({"t":"2026-11-01T04:00:00Z","o":entry,"h":entry*1.006,
                 "l":entry*0.985,"c":entry*0.99,"v":1})
    result=run_backtest(bars,fee_rate=0,slippage_bps=0)
    assert result["metrics"]["max_exposure_usd"] == 6.0
    assert result["metrics"]["closed_baskets"] == 1
    assert result["trades"][0]["legs"] == 2
    assert result["trades"][0]["exit_reason"] == "TAKE_PROFIT"


def test_backtest_never_submits_broker_orders():
    result=run_backtest(bars_up(60))
    assert result["order_submitted"] is False
    assert result["alpaca_write_api_called"] is False
    assert result["automated_execution"] is False


def test_rejects_invalid_history_and_costs():
    import pytest
    with pytest.raises(ValueError):
        run_backtest(bars_up(30))
    with pytest.raises(ValueError):
        run_backtest(bars_up(60),slippage_bps=10000)
    with pytest.raises(ValueError):
        run_backtest(bars_up(60),start_index=59)
