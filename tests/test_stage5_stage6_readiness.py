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


def test_stage6_readiness_reports_gates_and_remains_hard_locked():
    with TestClient(main.app) as client:
        response = client.get("/api/live/readiness")

    assert response.status_code == 200
    report = response.json()
    assert report["stage"] == 6
    assert report["result"] == "NOT_READY"
    assert report["mode"] == "READINESS_ASSESSMENT_ONLY"
    assert report["live_trading_supported"] is False
    assert report["live_orders_enabled"] is False
    assert report["readiness_percent"] == 14
    assert report["gates_passed"] == 1
    assert report["gates_total"] == 7
    assert report["paper_auto_entry_enabled"] is False
    assert report["paper_exit_manager_armed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert len(report["next_actions"]) == 5
    gates = {item["gate"]: item["passed"] for item in report["gates"]}
    assert gates["paper_execution_controls_safe"] is True
    assert all(not passed for key, passed in gates.items() if key != "paper_execution_controls_safe")


def test_stage6_blocks_when_paper_execution_controls_are_not_safe(monkeypatch):
    with TestClient(main.app) as client:
        monkeypatch.setitem(main._auto_entry, "enabled", True)
        monkeypatch.setitem(main._exit_manager, "armed", False)
        response = client.get("/api/live/readiness")

    assert response.status_code == 200
    report = response.json()
    gates = {item["gate"]: item for item in report["gates"]}
    assert gates["paper_execution_controls_safe"]["passed"] is False
    assert report["result"] == "NOT_READY"
    assert report["live_orders_enabled"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    monkeypatch.setitem(main._auto_entry, "enabled", False)


def test_stage5_validation_requires_token(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "stage5-test-token")
    with TestClient(main.app) as client:
        response = client.get("/api/paper/validation")
    assert response.status_code == 401


def test_stage5_validation_flags_open_btc_order(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "stage5-test-token")
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._exit_manager, "armed", False)

    async def fake_paper_request(method, path, params=None, body=None):
        if path == "/v2/account":
            return {"status": "ACTIVE", "equity": "100"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders":
            return [{"symbol": "BTC/USD", "status": "new"}]
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
    assert checks["no_open_btc_orders"] is False


def test_stage5_lifecycle_simulation_covers_stop_and_take_profit_without_broker_calls(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "stage5-test-token")
    with TestClient(main.app) as client:
        headers = {"Authorization": "Bearer stage5-test-token"}
        stop = client.post("/api/paper/lifecycle/simulate", headers=headers, json={
            "entry_price": 100000, "atr_14": 1000,
            "simulated_prices": [100100, 98500], "notional_usd": 10,
        })
        target = client.post("/api/paper/lifecycle/simulate", headers=headers, json={
            "entry_price": 100000, "atr_14": 1000,
            "simulated_prices": [101000, 103000], "notional_usd": 10,
        })
    assert stop.status_code == 200
    assert target.status_code == 200
    assert stop.json()["final_event"] == "SIMULATED_STOP_LOSS_EXIT"
    assert target.json()["final_event"] == "SIMULATED_TAKE_PROFIT_EXIT"
    for report in (stop.json(), target.json()):
        assert report["order_submitted"] is False
        assert report["alpaca_api_called"] is False
        assert report["live_or_paper_positions_changed"] is False
