"""Stage 4.7 bootstrap tests; no broker writes."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from backend import main
from backend.stage47 import run_stage47_report, _quantile


def _bars(count=4200):
    result = []
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(count):
        base = 50000 + i * 1.2 + ((i % 30) - 15) * 3
        result.append({
            "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
            "o": base - 1, "h": base + 5, "l": base - 5,
            "c": base + 2, "v": 10 + (20 if i % 45 >= 36 else 0),
        })
    return result


def test_stage47_quantile_is_deterministic():
    assert _quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


def test_stage47_bootstrap_is_reproducible_and_labeled_research_only():
    first = run_stage47_report(_bars(), simulations=200, seed=47)
    second = run_stage47_report(_bars(), simulations=200, seed=47)
    assert first["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert first["observed_trade_count"] == second["observed_trade_count"]
    assert first["bootstrap"] == second["bootstrap"]


def test_stage47_endpoint_is_read_only(monkeypatch):
    bars = _bars()

    async def fake_fetch(timeframe, limit):
        return bars[:limit], False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/stage4-7?limit=4200&simulations=100")
    assert response.status_code == 200
    body = response.json()
    assert body["research"]["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert body["automated_execution"] is False
    assert body["order_submitted"] is False
    assert body["alpaca_write_api_called"] is False
