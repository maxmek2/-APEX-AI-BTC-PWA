"""Regression tests for the Paper Auto Entry daily loss circuit breaker."""
import asyncio

import pytest
from fastapi import HTTPException

from backend import main


def test_auto_entry_disables_at_two_percent_daily_equity_loss(monkeypatch):
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", True)
    monkeypatch.setitem(main._auto_entry, "day_key", main._utc_day_key())
    monkeypatch.setitem(main._auto_entry, "day_start_equity", 100.0)
    monkeypatch.setitem(main._auto_entry, "daily_loss_limit_fraction", 0.02)
    monkeypatch.setitem(main._auto_entry, "trades_today", 0)

    calls = []

    async def fake_paper_request(method, path, params=None, body=None):
        calls.append((method, path, params, body))
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": "98.00", "buying_power": "100.00"}
        raise AssertionError(f"Unexpected broker request: {method} {path}")

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    asyncio.run(main._auto_entry_tick())

    assert main._auto_entry["enabled"] is False
    assert main._auto_entry["last_event"] == "AUTO_DISABLED_DAILY_LOSS_LIMIT"
    assert calls == [("GET", "/v2/account", None, None)]


def test_auto_entry_daily_loss_guard_is_two_percent():
    assert main._auto_entry["daily_loss_limit_fraction"] == 0.02


def _enable_test_auto_entry(monkeypatch):
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", True)
    monkeypatch.setitem(main._auto_entry, "day_key", main._utc_day_key())
    monkeypatch.setitem(main._auto_entry, "day_start_equity", 100.0)
    monkeypatch.setitem(main._auto_entry, "trades_today", 0)
    monkeypatch.setitem(main._auto_entry, "last_entry_attempt", None)
    monkeypatch.setitem(main._auto_entry, "last_signal_bar", None)


def test_auto_entry_fails_closed_when_fresh_quote_has_no_ask(monkeypatch):
    from datetime import datetime, timezone

    _enable_test_auto_entry(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    broker_calls = []
    market_calls = []

    async def fake_paper_request(method, path, params=None, body=None):
        broker_calls.append((method, path, body))
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": "100", "buying_power": "100"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders":
            return []
        raise AssertionError(f"Unexpected broker request: {method} {path}")

    async def fake_signal(timeframe):
        return {"signal": "LONG_SETUP", "last_bar_time": now, "atr_14": 100.0}

    async def fake_get_json(url, params=None):
        market_calls.append(url)
        assert url.endswith("/latest/quotes")
        return {"quotes": {"BTC/USD": {"ap": 0, "t": now}}}

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    monkeypatch.setattr(main, "signal", fake_signal)
    monkeypatch.setattr(main, "get_json", fake_get_json)
    asyncio.run(main._auto_entry_tick())

    assert main._auto_entry["last_event"] == "BLOCKED_INVALID_OR_MISSING_ASK"
    assert not any(method == "POST" for method, _, _ in broker_calls)
    assert len(market_calls) == 1


def test_auto_entry_caps_order_notional_to_broker_buying_power(monkeypatch):
    from datetime import datetime, timezone

    _enable_test_auto_entry(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    submitted = []

    async def fake_paper_request(method, path, params=None, body=None):
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": "100", "buying_power": "2"}
        if path == "/v2/positions":
            return []
        if method == "POST" and path == "/v2/orders":
            submitted.append(body)
            return {"id": "paper-order", "status": "new"}
        if path == "/v2/orders":
            return []
        raise AssertionError(f"Unexpected broker request: {method} {path}")

    async def fake_signal(timeframe):
        return {"signal": "LONG_SETUP", "last_bar_time": now, "atr_14": 100.0}

    async def fake_get_json(url, params=None):
        return {"quotes": {"BTC/USD": {"ap": 50000.0, "t": now}}}

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    monkeypatch.setattr(main, "signal", fake_signal)
    monkeypatch.setattr(main, "get_json", fake_get_json)
    asyncio.run(main._auto_entry_tick())

    assert len(submitted) == 1
    assert submitted[0]["qty"] == "0.00004000"
    assert main._auto_entry["last_event"] == "PAPER_ENTRY_ORDER_SUBMITTED"


def test_completed_bar_filter_excludes_current_in_progress_five_minute_candle():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 11, 22, 12, 7, tzinfo=timezone.utc)
    bars = [
        {"t": (now - timedelta(minutes=7)).isoformat(), "c": 100},
        {"t": (now - timedelta(minutes=2)).isoformat(), "c": 101},
    ]
    completed = main._completed_bars(bars, "5Min", now=now)
    assert len(completed) == 1
    assert completed[0]["c"] == 100


def test_enable_auto_entry_rejects_existing_btc_open_order(monkeypatch):
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._exit_manager, "armed", False)

    async def fake_paper_request(method, path, params=None, body=None):
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": "100", "buying_power": "100"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders":
            return [{"symbol": "BTC/USD", "status": "new"}]
        raise AssertionError(path)

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.enable_auto_entry())
    assert exc.value.status_code == 409
    assert "order" in exc.value.detail.lower()
    assert main._auto_entry["enabled"] is False


def test_reenable_preserves_daily_count_cooldown_and_processed_candle(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._auto_entry, "day_key", main._utc_day_key())
    monkeypatch.setitem(main._auto_entry, "day_start_equity", 100.0)
    monkeypatch.setitem(main._auto_entry, "trades_today", 2)
    last_attempt = datetime.now(timezone.utc).isoformat()
    monkeypatch.setitem(main._auto_entry, "last_entry_attempt", last_attempt)
    monkeypatch.setitem(main._auto_entry, "last_signal_bar", "2026-11-22T12:00:00Z")
    monkeypatch.setitem(main._exit_manager, "armed", False)

    async def fake_paper_request(method, path, params=None, body=None):
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": "100", "buying_power": "100"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    result = asyncio.run(main.enable_auto_entry())

    assert result["enabled"] is True
    assert main._auto_entry["trades_today"] == 2
    assert main._auto_entry["last_entry_attempt"] == last_attempt
    assert main._auto_entry["last_signal_bar"] == "2026-11-22T12:00:00Z"
    monkeypatch.setitem(main._auto_entry, "enabled", False)


@pytest.mark.parametrize(
    ("equity", "trades", "expected_message"),
    [
        (98.0, 0, "Daily loss limit"),
        (100.0, 5, "Daily submitted-entry limit"),
    ],
)
def test_reenable_cannot_reset_daily_loss_or_trade_cap(monkeypatch, equity, trades, expected_message):
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._auto_entry, "day_key", main._utc_day_key())
    monkeypatch.setitem(main._auto_entry, "day_start_equity", 100.0)
    monkeypatch.setitem(main._auto_entry, "trades_today", trades)
    monkeypatch.setitem(main._exit_manager, "armed", False)

    async def fake_paper_request(method, path, params=None, body=None):
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": str(equity), "buying_power": "100"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.enable_auto_entry())
    assert exc.value.status_code == 409
    assert expected_message in exc.value.detail
    assert main._auto_entry["enabled"] is False


def test_auto_entry_tick_rechecks_enabled_after_acquiring_lock(monkeypatch):
    class DisableBeforeLockEntry:
        async def __aenter__(self):
            main._auto_entry["enabled"] = False
        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setattr(main, "_auto_entry_lock", DisableBeforeLockEntry())
    monkeypatch.setitem(main._auto_entry, "enabled", True)
    calls = []

    async def fake_paper_request(method, path, params=None, body=None):
        calls.append((method, path))
        raise AssertionError("Tick must stop before broker calls after Disable")

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    asyncio.run(main._auto_entry_tick())
    assert calls == []
    assert main._auto_entry["enabled"] is False


def test_disable_auto_entry_uses_execution_lock(monkeypatch):
    class TrackingLock:
        def __init__(self):
            self.acquired = False
        async def __aenter__(self):
            self.acquired = True
        async def __aexit__(self, exc_type, exc, tb):
            return False

    lock = TrackingLock()
    monkeypatch.setattr(main, "_auto_entry_lock", lock)
    monkeypatch.setitem(main._auto_entry, "enabled", True)
    result = asyncio.run(main.disable_auto_entry())
    assert lock.acquired is True
    assert result["enabled"] is False
    assert result["last_event"] == "DISABLED_BY_USER"
