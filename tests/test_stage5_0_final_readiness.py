"""Stage 5.0 final readiness review remains assessment-only."""
from fastapi.testclient import TestClient
from backend import main


def test_final_readiness_is_not_ready_and_never_calls_broker(monkeypatch):
    monkeypatch.setitem(main._auto_entry, "enabled", False)
    monkeypatch.setitem(main._exit_manager, "armed", False)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Final readiness must not call broker APIs")

    monkeypatch.setattr(main, "_paper_request", forbidden)
    with TestClient(main.app) as client:
        response = client.get("/api/research/final-readiness")
    assert response.status_code == 200
    report = response.json()
    assert report["stage"] == "5.0"
    assert report["result"] == "NOT_READY"
    assert report["live_trading_supported"] is False
    assert report["live_orders_enabled"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    research = report["research_validation"]
    assert research["strategy_validation"] == "FAILED_CURRENT_OBSERVED_RUNS"
    assert research["stage4_5"]["qualified_candidates"] == 0
    assert research["stage4_6"]["positive_net_pnl_folds"] == 0
    assert research["stage4_7"]["positive_path_probability_percent"] == 0.0
    assert research["stage4_8"]["net_pnl_usd"] < 0
    assert "not fetched dynamically" in research["note"]
