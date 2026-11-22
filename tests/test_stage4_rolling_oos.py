"""Offline tests for rolling out-of-sample Stage 4 research; no broker writes."""
from fastapi.testclient import TestClient
from backend import main


def _bars(count=720):
    bars = []
    for i in range(count):
        price = 60000 + i * 2
        bars.append({
            "t": f"2026-10-{1 + i // 288:02d}T{(i // 12) % 24:02d}:{(i % 12) * 5:02d}:00Z",
            "o": price, "h": price + 8, "l": price - 5,
            "c": price + 3, "v": 1,
        })
    return bars


def test_rolling_oos_returns_sequential_fixed_parameter_windows(monkeypatch):
    bars = _bars()

    async def fake_fetch(timeframe, limit):
        return bars[:limit], False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/rolling-oos?limit=720&windows=4")

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "rolling_out_of_sample_research"
    assert report["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert len(report["window_reports"]) == 4
    assert report["method"]["chronological_non_overlapping"] is True
    assert report["method"]["fixed_parameters_no_test_optimization"] is True
    assert all(w["test_starts_flat"] for w in report["window_reports"])
    assert all(w["entries_inside_window"] for w in report["window_reports"])
    assert report["automated_execution"] is False
    assert report["order_submitted"] is False
    assert report["alpaca_write_api_called"] is False


def test_rolling_oos_rejects_too_few_candles(monkeypatch):
    async def fake_fetch(timeframe, limit):
        return _bars(599), False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/rolling-oos?limit=600")

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert response.json()["order_submitted"] is False
