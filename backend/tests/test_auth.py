import os

os.environ.setdefault("SDC_PERSIST", "0")
os.environ.setdefault("SDC_HEADLESS", "1")

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_open_when_api_key_unset():
    os.environ.pop("API_KEY", None)
    assert client.get("/api/v1/topology").status_code == 200


def test_api_key_required_when_set(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-test")
    denied = client.get("/api/v1/topology")
    assert denied.status_code == 401
    body = denied.json()
    assert body["error"] is True
    assert body["code"] == "unauthorized"
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/ready").status_code == 200
    ok = client.get("/api/v1/topology", headers={"X-API-Key": "secret-test"})
    assert ok.status_code == 200
    bearer = client.get("/api/v1/topology", headers={"Authorization": "Bearer secret-test"})
    assert bearer.status_code == 200
    assistant = client.get("/assistant/status")
    assert assistant.status_code == 401
    assert client.get("/assistant/status", headers={"X-API-Key": "secret-test"}).status_code == 200
