"""Offline tests for Stage 4.2 multi-timeframe and momentum/volatility filters."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from backend import main


def _bars(count=720):
    bars = []
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(count):
        # Mild trend with repeatable pullbacks; timestamps are contiguous 5m bars.
        price = 60000 + i * 1.4 + ((i % 18) - 9) * 8
        bars.append({
            "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
            "o": price - 2, "h": price + 12, "l": price - 12,
            "c": price + 3, "v": 1,
        })
    return bars


def test_stage42_endpoint_compares_predeclared_filters_without_orders(monkeypatch):
    bars = _bars()

    async def fake_fetch(timeframe, limit):
        return bars[:limit], False, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/stage4-2?limit=720")

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "fixed_filter_comparison_train_and_untouched_holdout"
    assert report["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert set(report["reports"]) == {
        "baseline", "mtf_15m_1h", "rsi_50_70",
        "atr_pct_min_0_04", "combined_mtf_rsi_atr",
    }
    assert report["checks"]["higher_timeframe_uses_completed_candles_only"] is True
    assert report["checks"]["holdout_filters_predeclared_not_optimized"] is True
    assert report["checks"]["holdout_entries_after_split"] is True
    assert report["automated_execution"] is False
    assert report["order_submitted"] is False
    assert report["alpaca_write_api_called"] is False


def test_higher_timeframe_filter_does_not_use_partial_hour_candle():
    bars = _bars(299)
    before = main.higher_timeframe_bullish_by_index(bars, 60)
    changed = [dict(item) for item in bars]
    changed[-1]["c"] += 10000
    changed[-1]["h"] += 10000
    after = main.higher_timeframe_bullish_by_index(changed, 60)
    # Last 5m candle is inside an unfinished hourly bucket, so it cannot
    # alter the hourly trend used for its own signal.
    assert before[-1] == after[-1]


def test_rsi_series_is_causal_and_bounded():
    values = [100 + i + ((i % 5) - 2) for i in range(80)]
    rsi = main.rsi_series(values, 14)
    assert rsi[:14] == [None] * 14
    assert all(value is None or 0 <= value <= 100 for value in rsi)
    changed_future = values[:]
    changed_future[-1] += 500
    rsi_changed = main.rsi_series(changed_future, 14)
    assert rsi[:-1] == rsi_changed[:-1]
