"""Read-only paper risk preview tests; no broker order writes are permitted."""
from fastapi.testclient import TestClient

from backend import main


def test_paper_preview_uses_risk_budget_and_never_submits_order(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "test-secret")
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)

    calls = []

    async def fake_get_json(url, params=None):
        calls.append((url, params))
        if url.endswith("/v2/account"):
            return {"equity": "100.00"}
        if url.endswith("/v2/positions"):
            return []
        raise AssertionError(f"Unexpected broker request: {url}")

    async def fake_signal(timeframe):
        return {
            "signal": "LONG_SETUP", "last_close": 100000.0,
            "atr_14": 10000.0, "timeframe": timeframe,
        }

    monkeypatch.setattr(main, "get_json", fake_get_json)
    monkeypatch.setattr(main, "signal", fake_signal)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/paper/preview",
            headers={"Authorization": "Bearer test-secret"},
            json={
                "timeframe": "1Min", "risk_percent": 0.5,
                "max_notional_usd": 10, "stop_atr_multiple": 1.5,
                "reward_risk": 2,
            },
        )

    assert response.status_code == 200
    result = response.json()
    assert result["approved"] is True
    assert result["risk_budget_usd"] == 0.5
    assert result["proposed_notional_usd"] == 3.33
    assert result["proposed_stop_price"] == 85000.0
    assert result["order_submitted"] is False
    assert result["execution_status"] == "PREVIEW_ONLY"
    assert len(calls) == 2  # Account and positions reads only; no order POST.
