"""Cheap API-surface checks — no DB writes, no LLM calls."""
from app.main import app


def _paths():
    return {getattr(r, "path", None) for r in app.routes}


def test_core_routes_registered():
    paths = _paths()
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/sessions" in paths
    assert "/api/v1/feedback" in paths
    assert "/ws/stream/{message_id}" in paths


def test_health():
    from fastapi.testclient import TestClient
    # Exercise the stateless health route (lifespan does no table creation).
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
