"""Stage 4.9 local safety audit tests; no broker calls."""
from fastapi.testclient import TestClient
from backend import main


def test_stage49_audit_is_read_only_and_reports_safe_defaults(monkeypatch):
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._exit_manager, "armed", False)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Safety audit must not call broker APIs")

    monkeypatch.setattr(main, "_paper_request", forbidden)
    with TestClient(main.app) as client:
        response = client.get("/api/research/safety-audit")
    assert response.status_code == 200
    report = response.json()
    assert report["stage"] == "4.9"
    assert report["result"] == "SAFE_FOR_READ_ONLY_RESEARCH"
    assert report["checks"]["live_trading_supported"] is False
    assert report["checks"]["live_orders_enabled"] is False
    assert report["broker_api_called"] is False
    assert report["broker_write_api_called"] is False
    assert report["order_submitted"] is False


def test_stage49_audit_flags_enabled_paper_control(monkeypatch):
    monkeypatch.setattr(main, "_paper_only_configured", lambda: True)
    monkeypatch.setitem(main._exit_manager, "armed", False)
    with TestClient(main.app) as client:
        monkeypatch.setitem(main._auto_entry, "enabled", True)
        report = client.get("/api/research/safety-audit").json()
    assert report["result"] == "REQUIRES_REVIEW"
    assert report["paper_auto_entry_enabled"] is True
    monkeypatch.setitem(main._auto_entry, "enabled", False)
