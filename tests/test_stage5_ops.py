from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_stage51_requires_train_and_holdout_profitability():
    payload = {
        "training": [{"gross_pnl_usd": 2, "fees_usd": 0.1, "slippage_usd": 0.1} for _ in range(30)],
        "holdout": [{"gross_pnl_usd": 2, "fees_usd": 0.1, "slippage_usd": 0.1} for _ in range(30)],
    }
    result = client.post("/api/research/stage5-1/evaluate", json=payload).json()
    assert result["result"] == "RESEARCH_GATE_PASSED"
    assert result["order_submitted"] is False


def test_stage51_rejects_unprofitable_holdout():
    payload = {
        "training": [{"gross_pnl_usd": 2, "fees_usd": 0.1, "slippage_usd": 0.1} for _ in range(30)],
        "holdout": [{"gross_pnl_usd": -1, "fees_usd": 0.1, "slippage_usd": 0.1} for _ in range(30)],
    }
    result = client.post("/api/research/stage5-1/evaluate", json=payload).json()
    assert result["training_gate_passed"] is True
    assert result["holdout_gate_passed"] is False
    assert result["result"] == "NOT_VALIDATED"


def test_stage52_models_partial_fill_reject_and_restart(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "stage5-ops-test-token")
    headers = {"Authorization": "Bearer stage5-ops-test-token"}
    ok = client.post("/api/paper/stage5-2/lifecycle-simulate", headers=headers, json={
        "events": ["submitted", "partial_fill", "filled", "exit_requested", "closed"]
    }).json()
    assert ok["state"] == "CLOSED"
    assert ok["order_submitted"] is False
    bad = client.post("/api/paper/stage5-2/lifecycle-simulate", headers=headers, json={
        "events": ["submitted", "partial_fill", "restart", "closed"]
    }).json()
    assert bad["result"] == "INVALID_SEQUENCE"


def test_stage53_blocks_stale_or_overrisk_preflight():
    result = client.post("/api/risk/stage5-3/preflight", json={
        "equity_usd": 100, "proposed_notional_usd": 10, "risk_percent": 1,
        "entry_price": 50000, "stop_price": 49000,
        "quote_age_seconds": 45, "signal_age_seconds": 60,
        "has_open_position": False, "has_open_order": False, "daily_loss_percent": 0
    }).json()
    assert result["result"] == "BLOCKED"
    assert result["order_submitted"] is False


def test_stage54_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "x" * 40)
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
    result = client.get("/api/security/stage5-4/config-audit").json()
    assert result["result"] == "CONFIG_REVIEW_PASS"
    assert result["secret_values_exposed"] is False
    assert "x" * 40 not in str(result)


def test_stage51_real_run_uses_frozen_backtest_and_never_writes(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import backend.main as main_module

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = [{
        "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
        "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 10.0,
    } for i in range(3000)]
    async def fake_fetch(timeframe, limit):
        return bars[:limit], False, 1
    monkeypatch.setattr(main_module, "fetch_backtest_bars", fake_fetch)

    response = client.get("/api/research/stage5-1/run?limit=3000")
    assert response.status_code == 200
    result = response.json()
    assert result["stage"] == "5.1"
    assert result["bars_used"] == 3000
    assert result["validated_variant_count"] == 0
    assert result["result"] == "NOT_VALIDATED"
    assert result["market_data_api_read"] is True
    assert result["order_submitted"] is False
    assert set(result["variants"]) == {
        "breakout_relvol_1p5", "breakout_pullback",
        "breakout_pullback_relvol", "breakout_relvol_1p5_1h20_50",
    }
