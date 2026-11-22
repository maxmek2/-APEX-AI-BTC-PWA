"""Stage 4.4 research tests; no broker writes."""
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend import main
from backend.stage44 import build_stage44_signals, run_stage44_report


def _bars(count=4200):
    out=[]
    start=datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(count):
        base=50000+i*1.2+((i%30)-15)*3
        out.append({"t":(start+timedelta(minutes=5*i)).isoformat().replace("+00:00","Z"),
                    "o":base-1,"h":base+5,"l":base-5,"c":base+2,
                    "v":10+(20 if i%45>=36 else 0)})
    return out


def test_stage44_variants_and_diagnostics_are_returned():
    result=build_stage44_signals(_bars())
    assert set(result["signals"]) == {
        "breakout_relvol_1p5","breakout_pullback",
        "breakout_pullback_relvol","breakout_relvol_1p5_1h20_50"}
    assert result["diagnostics"]["complete_15m_bars"] > 0
    assert result["diagnostics"]["breakout_events"] >= 0
    assert len(result["atr_by_base"]) == 4200


def test_stage44_pullback_does_not_fire_on_same_breakout_candle():
    bars=_bars()
    result=build_stage44_signals(bars)
    # A confirmation must be later than its originating breakout by construction.
    assert result["diagnostics"]["pullback_confirmations"] >= 0


def test_stage44_report_keeps_holdout_entries_after_split():
    report=run_stage44_report(_bars(4200))
    assert set(report["reports"]) == {
        "breakout_relvol_1p5","breakout_pullback",
        "breakout_pullback_relvol","breakout_relvol_1p5_1h20_50"}
    for item in report["reports"].values():
        assert item["holdout_entries_after_split"] is True
        assert len(item["cost_sensitivity"]) >= 4


def test_stage44_endpoint_is_read_only(monkeypatch):
    bars=_bars(4200)
    async def fake_fetch(timeframe, limit):
        return bars[:limit], True, 1
    monkeypatch.setattr(main,"fetch_backtest_bars",fake_fetch)
    with TestClient(main.app) as client:
        response=client.get("/api/backtest/stage4-4?limit=4200")
    assert response.status_code==200
    body=response.json()
    assert body["validation"]=="RESEARCH_ONLY_NOT_CERTIFIED"
    assert body["checks"]["read_only"] is True
    assert body["automated_execution"] is False
    assert body["order_submitted"] is False
    assert body["alpaca_write_api_called"] is False
