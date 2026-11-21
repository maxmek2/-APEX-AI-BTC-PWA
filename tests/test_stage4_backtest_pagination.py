"""Deterministic tests for paginated historical BTC backtest data retrieval."""
from fastapi.testclient import TestClient

from backend import main


def _bar(index: int) -> dict:
    stamp = f"2026-11-{7 + index // 144:02d}T{(index // 12) % 24:02d}:{(index % 12) * 5:02d}:00Z"
    price = 60000 + index
    return {
        "t": stamp,
        "o": price,
        "h": price + 5,
        "l": price - 5,
        "c": price + 1,
        "v": 1,
    }


def test_backtest_fetches_multiple_pages_and_returns_chronological_bars(monkeypatch):
    calls = []

    async def fake_get_json(url, params):
        calls.append(dict(params))
        if params.get("page_token") == "page-2":
            return {
                "bars": {"BTC/USD": [_bar(i) for i in range(39, -1, -1)]},
                "next_page_token": None,
            }
        return {
            "bars": {"BTC/USD": [_bar(i) for i in range(99, 39, -1)]},
            "next_page_token": "page-2",
        }

    monkeypatch.setattr(main, "get_json", fake_get_json)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest?timeframe=5Min&limit=100")

    assert response.status_code == 200
    result = response.json()
    assert result["bars_used"] == 100
    assert result["requested_bars"] == 100
    assert result["history_complete_for_request"] is True
    assert result["data_pages_fetched"] == 2
    assert result["has_more_data"] is False
    assert calls[0]["limit"] == 100
    assert calls[1]["page_token"] == "page-2"
    assert result["period"]["from"] == _bar(0)["t"]
    assert result["period"]["to"] == _bar(99)["t"]


def test_backtest_reports_when_more_history_exists_after_requested_limit(monkeypatch):
    async def fake_get_json(url, params):
        return {
            "bars": {"BTC/USD": [_bar(i) for i in range(99, -1, -1)]},
            "next_page_token": "more-history",
        }

    monkeypatch.setattr(main, "get_json", fake_get_json)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest?timeframe=5Min&limit=100")

    assert response.status_code == 200
    result = response.json()
    assert result["bars_used"] == 100
    assert result["history_complete_for_request"] is True
    assert result["has_more_data"] is True
    assert result["data_pages_fetched"] == 1
