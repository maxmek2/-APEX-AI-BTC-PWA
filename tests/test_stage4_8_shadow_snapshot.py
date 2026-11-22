"""Stage 4.8 shadow snapshot tests; endpoint must remain read-only."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from backend import main


def _bars(count=3000):
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


def test_shadow_snapshot_never_submits_orders(monkeypatch):
    bars = _bars()

    async def fake_fetch(timeframe, limit):
        return bars[-limit:], False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/research/shadow-snapshot?limit=3000")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "READ_ONLY_SHADOW_SNAPSHOT"
    assert body["shadow_only"] is True
    assert body["paper_order_enabled"] is False
    assert body["order_submitted"] is False
    assert body["alpaca_write_api_called"] is False
