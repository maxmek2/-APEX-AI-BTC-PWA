"""API boundary tests; no broker calls or order writes are made."""
from fastapi.testclient import TestClient

from backend.main import app


def test_paper_api_rejects_missing_bearer_token(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "test-secret")
    with TestClient(app) as client:
        response = client.get("/api/paper/status")
    assert response.status_code == 401


def test_paper_api_rejects_when_server_token_is_not_configured(monkeypatch):
    monkeypatch.delenv("APEX_API_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/paper/status")
    assert response.status_code == 503


def test_paper_status_accepts_valid_bearer_without_enabling_execution(monkeypatch):
    monkeypatch.setenv("APEX_API_TOKEN", "test-secret")
    with TestClient(app) as client:
        response = client.get(
            "/api/paper/status",
            headers={"Authorization": "Bearer test-secret"},
        )
    assert response.status_code == 200
    assert response.json()["auto_enabled"] is False
    assert response.json()["order_submission_enabled"] is False


def test_public_health_remains_readable_without_paper_token(monkeypatch):
    monkeypatch.delenv("APEX_API_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
