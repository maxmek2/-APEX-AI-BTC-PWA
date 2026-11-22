"""Stage 4.6 walk-forward tests; no broker writes."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from backend import main
from backend.stage46 import run_stage46_report


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


def test_stage46_has_non_overlapping_chronological_folds():
    bars = _bars()
    report = run_stage46_report(bars, folds=3)
    folds = report["folds"]
    assert len(folds) == 3
    assert folds[0]["start_index"] < folds[1]["start_index"] < folds[2]["start_index"]
    assert folds[0]["end_index_exclusive"] == folds[1]["start_index"]
    assert folds[1]["end_index_exclusive"] == folds[2]["start_index"]
    assert report["summary"]["all_entries_inside_fold"] is True
    assert report["selection_used_fold_results"] is False


def test_stage46_endpoint_is_read_only(monkeypatch):
    bars = _bars()

    async def fake_fetch(timeframe, limit):
        return bars[:limit], False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/stage4-6?limit=4200&folds=3")
    assert response.status_code == 200
    body = response.json()
    assert body["research"]["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert body["research"]["summary"]["folds"] == 3
    assert body["automated_execution"] is False
    assert body["order_submitted"] is False
    assert body["alpaca_write_api_called"] is False
