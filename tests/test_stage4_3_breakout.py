"""Stage 4.3 breakout research tests; all broker access is mocked."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from backend import main
from backend.stage43 import aggregate_complete_5m, build_breakout_signals


def _bars(count=4200):
    result = []
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(count):
        # Persistent rising market with deterministic pullbacks and volume pulses.
        base = 50000 + i * 1.8 + ((i % 24) - 12) * 5
        volume = 10 + (25 if i % 36 >= 30 else 0)
        result.append({
            "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
            "o": base - 2, "h": base + 8, "l": base - 8,
            "c": base + 3, "v": volume,
        })
    return result


def test_aggregate_complete_5m_discards_partial_groups():
    bars = _bars(25)
    assert len(aggregate_complete_5m(bars, 15)) == 8
    assert len(aggregate_complete_5m(bars, 60)) == 2


def test_stage43_signal_is_causal_inside_unfinished_higher_timeframe_buckets():
    bars = _bars()
    before = build_breakout_signals(bars)
    changed = [dict(x) for x in bars]
    # Modify a 5m candle that is not the close of its 15m or 1h bucket.
    index = 4000
    assert (index + 1) % 3 != 0
    changed[index]["c"] += 100000
    changed[index]["h"] += 100000
    after = build_breakout_signals(changed)
    assert before["signals"]["breakout_volume_1h"][index] == after["signals"]["breakout_volume_1h"][index]


def test_stage43_endpoint_is_read_only_and_reports_chronological_holdout(monkeypatch):
    bars = _bars(4200)

    async def fake_fetch(timeframe, limit):
        return bars[:limit], True, 1

    monkeypatch.setattr(main, "fetch_backtest_bars", fake_fetch)
    with TestClient(main.app) as client:
        response = client.get("/api/backtest/stage4-3?limit=4200")

    assert response.status_code == 200
    report = response.json()
    assert report["validation"] == "RESEARCH_ONLY_NOT_CERTIFIED"
    assert set(report["reports"]) == {
        "breakout_only", "breakout_volume", "breakout_volume_1h",
    }
    assert report["checks"]["chronological_split"] is True
    assert report["checks"]["15m_signals_only_after_candle_close"] is True
    assert report["checks"]["1h_trend_uses_completed_candles_only"] is True
    assert report["checks"]["current_15m_candle_excluded_from_breakout_channel"] is True
    assert report["checks"]["holdout_entries_after_split"] is True
    assert report["automated_execution"] is False
    assert report["order_submitted"] is False
    assert report["alpaca_write_api_called"] is False
