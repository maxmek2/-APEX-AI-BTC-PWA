"""Stage 5.6 training-only strategy failure attribution tests."""
from datetime import datetime, timedelta, timezone

from backend.stage56 import _group_summary, _longest_losing_streak, run_stage56_failure_report


def sample_bars(count=6000):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    out=[]
    for i in range(count):
        phase=(i//900)%4
        drift=(0.7 if phase==0 else -0.55 if phase==1 else 0.03 if phase==2 else 0.12)
        close=50000+i*drift+((i%19)-9)*(2.5 if phase in (0,1) else 0.8)
        out.append({
            "t":(start+timedelta(minutes=5*i)).isoformat().replace("+00:00","Z"),
            "o":close-0.5,"h":close+2.5,"l":close-2.5,"c":close,
            "v":100+(i%11)*4,
        })
    return out


def test_stage56_group_summary_and_losing_streak():
    trades=[
        {"gross_pnl_usd":0.2,"estimated_fees_usd":0.05,"net_pnl_usd":0.15},
        {"gross_pnl_usd":-0.1,"estimated_fees_usd":0.05,"net_pnl_usd":-0.15},
        {"gross_pnl_usd":-0.1,"estimated_fees_usd":0.05,"net_pnl_usd":-0.15},
    ]
    summary=_group_summary(trades)
    assert summary["trades"]==3
    assert summary["net_pnl_usd"]==-0.15
    assert _longest_losing_streak(trades)==2


def test_stage56_is_training_only_and_never_uses_holdout():
    report=run_stage56_failure_report(sample_bars(),requested_bars=6000)
    assert report["stage"]=="5.6"
    assert report["holdout_accessed"] is False
    assert report["holdout"]["status"]=="SEALED_NOT_ACCESSED"
    assert report["frozen_strategy"]["selection_or_optimization"] is False
    assert report["order_submitted"] is False
    assert report["alpaca_write_api_called"] is False
    assert report["automated_execution"] is False
    assert report["training"]["training_bars"] if "training_bars" in report["training"] else report["training_bars"]==3600


def test_stage56_rejects_short_history():
    import pytest
    with pytest.raises(ValueError,match="5000 bars"):
        run_stage56_failure_report(sample_bars(3000),requested_bars=3000)
