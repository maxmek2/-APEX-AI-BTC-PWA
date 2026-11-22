"""Stage 4.5 train-only parameter research tests; no broker writes."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from backend import main
from backend.stage44 import run_stage44_report
from backend.stage45 import run_stage45_report


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


def test_stage45_uses_predeclared_grid_and_training_only_selection():
    report = run_stage45_report(_bars())
    assert report["grid_size"] == 27
    assert report["diagnostics"]["selection_used_holdout"] is False
    assert len(report["all_candidates_training_only"]) == 27
    assert report["qualified_candidates"] >= 0
    if report["selected_parameters"] is None:
        assert report["holdout"] is None
    else:
        assert report["holdout"]["entries_after_split"] is True


def test_stage45_endpoint_is_read_only(monkeypatch):
    bars = _bars(4200)

    async def fake_fetch(timeframe, limit):
        return bars[:limit], True, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/stage4-5?limit=4200")
    assert response.status_code == 200
    body = response.json()
    assert body["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert body["research"]["grid_size"] == 27
    assert body["research"]["diagnostics"]["selection_used_holdout"] is False
    assert body["automated_execution"] is False
    assert body["order_submitted"] is False
    assert body["alpaca_write_api_called"] is False


def test_stage44_training_segment_excludes_first_holdout_bar(monkeypatch):
    import backend.stage44 as stage44

    bars = _bars(4200)
    original = stage44.run_breakout_backtest
    seen = []

    def capture(data, mask, atrs, *args, **kwargs):
        seen.append(len(data))
        return original(data, mask, atrs, *args, **kwargs)

    monkeypatch.setattr(stage44, "run_breakout_backtest", capture)
    stage44.run_stage44_report(bars)
    assert seen[0] == int(len(bars) * 0.60)
