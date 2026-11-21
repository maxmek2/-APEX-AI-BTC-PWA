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
            return {"equity": "98.00"}
        raise AssertionError(f"Unexpected broker request: {method} {path}")

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    asyncio.run(main._auto_entry_tick())

    assert main._auto_entry["enabled"] is False
    assert main._auto_entry["last_event"] == "AUTO_DISABLED_DAILY_LOSS_LIMIT"
    assert calls == [("GET", "/v2/account", None, None)]


def test_auto_entry_daily_loss_guard_is_two_percent():
    assert main._auto_entry["daily_loss_limit_fraction"] == 0.02
