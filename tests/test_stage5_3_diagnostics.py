"""Stage 5.3 diagnostics/optimization tests; strictly read-only."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend import main
from backend.stage53 import run_stage53_report


def _bars(count=3000):
    out = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(count):
        base = 50000 + i * 0.15 + ((i % 17) - 8) * 2.0
        out.append({
            "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
            "o": base - 0.5, "h": base + 2.0, "l": base - 2.0,
            "c": base + 0.5, "v": 10 + (20 if i % 45 >= 36 else 0),
        })
    return out


def test_stage53_returns_train_only_grid_and_diagnostics():
    report = run_stage53_report(_bars(), minimum_training_trades=30)
    assert report["stage"] == "5.3"
    assert report["optimization"]["grid_size"] == 72
    assert report["optimization"]["selection_used_holdout"] is False
    assert len(report["optimization"]["top_training_candidates"]) == 10
    assert "exit_reason_breakdown" in report["baseline_diagnostics"]["training"]
    assert "exit_reason_breakdown" in report["baseline_diagnostics"]["holdout"]
    assert report["order_submitted"] is False
    assert report["alpaca_write_api_called"] is False
    assert report["automated_execution"] is False


def test_stage53_does_not_touch_holdout_when_no_training_candidate_qualifies():
    report = run_stage53_report(_bars(), minimum_training_trades=500)
    assert report["optimization"]["qualified_training_candidates"] == 0
    assert report["optimization"]["holdout"] is None
    assert report["optimization"]["holdout_evaluated_once"] is False
    assert report["result"] == "NO_TRAINING_QUALIFIED_CANDIDATE"


def test_stage53_endpoint_is_read_only(monkeypatch):
    bars = _bars()

    async def fake_fetch(timeframe, limit):
        return bars[:limit], True, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/research/stage5-3/run?limit=3000&minimum_training_trades=30")
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "5.3"
    assert body["market_data_api_read"] is True
    assert body["order_submitted"] is False
    assert body["alpaca_write_api_called"] is False
    assert body["automated_execution"] is False
