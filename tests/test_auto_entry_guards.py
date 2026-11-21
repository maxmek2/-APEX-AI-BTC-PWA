"""Regression tests for the Paper Auto Entry daily loss circuit breaker."""
import asyncio

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
            return {"equity": "98.00", "buying_power": "100.00"}
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
            return {"equity": "100", "buying_power": "100"}
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
            return {"equity": "100", "buying_power": "2"}
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
