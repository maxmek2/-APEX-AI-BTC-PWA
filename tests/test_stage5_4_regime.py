"""Stage 5.4 regime and fold validation tests."""
from datetime import datetime, timedelta, timezone

from backend.stage54 import build_market_regimes, run_stage54_report


def bars(count=6000):
    out=[]
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    for i in range(count):
        # Deterministic changing price/volatility regimes and enough history.
        phase=(i//900)%4
        drift=(0.7 if phase==0 else -0.55 if phase==1 else 0.03 if phase==2 else 0.12)
        close=50000 + i*drift + ((i%19)-9)*(2.5 if phase in (0,1) else 0.8)
        op=close-0.5
        out.append({
            "t":(start+timedelta(minutes=5*i)).isoformat().replace("+00:00","Z"),
            "o":op,"h":close+2.5,"l":close-2.5,"c":close,"v":100+(i%11)*4
        })
    return out


def test_stage54_regimes_are_complete_and_aligned():
    data=bars()
    result=build_market_regimes(data)
    assert len(result["regime_by_base"])==len(data)
    assert len(result["trend_by_base"])==len(data)
    assert set(result["trend_by_base"]) <= {
        "TREND_UNAVAILABLE","BULL_TREND","BEAR_TREND","MIXED_TREND"
    }


def test_stage54_report_is_fixed_parameter_and_read_only():
    report=run_stage54_report(bars(),folds=4,minimum_trades_per_fold=3)
    assert report["stage"]=="5.4"
    assert report["frozen_strategy"]["selection_or_optimization"] is False
    assert report["decision_gates"]["walk_forward_gate"] in (True,False)
    assert len(report["walk_forward_folds"])==4
    assert report["market_data_api_read"] is True
    assert report["order_submitted"] is False
    assert report["alpaca_write_api_called"] is False
    assert report["automated_execution"] is False
    assert report["split"]["holdout_entries_after_split"] is True


def test_stage54_requires_enough_data():
    import pytest
    with pytest.raises(ValueError,match="5000 bars"):
        run_stage54_report(bars(3000))



def test_stage54_fold_ledgers_do_not_cross_boundaries():
    data=bars()
    report=run_stage54_report(data,folds=4,minimum_trades_per_fold=3)
    assert len(report["walk_forward_folds"])==4
    for fold in report["walk_forward_folds"]:
        assert fold["metrics"]["trades"] >= 0
        assert fold["entries_after_fold_start"] is True
        for trade in fold["regime_attribution"].values():
            assert trade["ending_equity_usd"] >= 0
