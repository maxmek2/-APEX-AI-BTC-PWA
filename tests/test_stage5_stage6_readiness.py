"""Stage 5/6 readiness tests. All broker interactions are mocked and read-only."""
from fastapi.testclient import TestClient

from backend import main


def test_stage5_validation_is_read_only_and_checks_safe_paper_state(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "stage5-test-token")
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._exit_manager, "armed", False)
    calls = []

    async def fake_paper_request(method, path, params=None, body=None):
        calls.append((method, path, params, body))
        if path == "/v2/account":
            return {"status": "ACTIVE", "currency": "USD", "equity": "100", "buying_power": "100"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders":
            return []
        raise AssertionError(f"Unexpected broker request: {method} {path}")

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/paper/validation",
            headers={"Authorization": "Bearer stage5-test-token"},
        )

    assert response.status_code == 200
    report = response.json()
    assert report["stage"] == 5
    assert report["result"] == "CLEAN"
    assert report["checks_passed"] == report["checks_total"]
    assert report["broker_write_api_called"] is False
    assert report["order_submitted"] is False
    assert [call[0] for call in calls] == ["GET", "GET", "GET"]
    assert all(call[3] is None for call in calls)


def test_stage5_validation_flags_open_btc_position(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "stage5-test-token")
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._exit_manager, "armed", False)

    async def fake_paper_request(method, path, params=None, body=None):
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": "100"}
        if path == "/v2/positions":
            return [{"symbol": "BTC/USD", "qty": "0.001"}]
        if path == "/v2/orders":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(main, "_paper_request", fake_paper_request)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/paper/validation",
            headers={"Authorization": "Bearer stage5-test-token"},
        )

    assert response.status_code == 200
    report = response.json()
    assert report["result"] == "REQUIRES_REVIEW"
    checks = {item["check"]: item["passed"] for item in report["checks"]}
    assert checks["no_open_btc_positions"] is False


def test_stage6_readiness_is_hard_locked_and_never_enables_live_trading():
    with TestClient(main.app) as client:
        response = client.get("/api/live/readiness")

    assert response.status_code == 200
    report = response.json()
    assert report["stage"] == 6
    assert report["result"] == "NOT_READY"
    assert report["live_trading_supported"] is False
    assert report["live_orders_enabled"] is False
    assert report["gates_passed"] == 0
    assert report["order_submitted"] is False
