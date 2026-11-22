"""Offline tests for Stage 4.1 parameter search and cost sensitivity."""
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


def test_optimizer_selects_only_from_training_and_reports_cost_sensitivity(monkeypatch):
    bars = _bars()

    async def fake_fetch(timeframe, limit):
        return bars[:limit], False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/optimize?limit=720")

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "train_selected_untouched_holdout_evaluation"
    assert report["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert report["search_space"]["candidate_count"] == 18
    assert report["search_space"]["holdout_used_for_selection"] is False
    assert report["checks"]["candidate_selection_used_training_only"] is True
    assert report["checks"]["holdout_parameters_untuned"] is True
    assert [x["slippage_bps_per_side"] for x in report["cost_sensitivity"]] == [0, 5, 10, 20]
    assert all(x["test_entries_after_split"] for x in report["cost_sensitivity"])
    assert report["automated_execution"] is False
    assert report["order_submitted"] is False
    assert report["alpaca_write_api_called"] is False


def test_optimizer_rejects_insufficient_history(monkeypatch):
    async def fake_fetch(timeframe, limit):
        return _bars(599), False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/optimize?limit=600")

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert response.json()["order_submitted"] is False


def test_backtest_rejects_invalid_ema_and_risk_parameters():
    import pytest

    bars = _bars()
    with pytest.raises(ValueError, match="EMA periods"):
        main.run_ema_atr_backtest(bars, fast_period=21, slow_period=9)
    with pytest.raises(ValueError, match="positive"):
        main.run_ema_atr_backtest(bars, stop_atr_multiple=0)
