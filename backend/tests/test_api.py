import os

os.environ.setdefault("SDC_PERSIST", "0")
os.environ.setdefault("SDC_HEADLESS", "1")

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_and_ready():
    h = client.get("/api/v1/health")
    assert h.status_code == 200
    assert h.json()["ok"] is True
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_legacy_health_hidden_alias():
    h = client.get("/health")
    assert h.status_code == 200


def test_validation_error_envelope():
    res = client.post("/api/v1/jobs", json={"input_bytes": -1})
    assert res.status_code == 422
    body = res.json()
    assert body["error"] is True
    assert body["code"] == "validation_error"


def test_openapi_has_v1():
    spec = client.get("/openapi.json").json()
    assert "/api/v1/jobs" in spec["paths"]
    assert "/health" not in spec["paths"] or spec["paths"].get("/health", {}).get("get", {}).get("includeInSchema", True)


def test_topology_power_labels():
    topo = client.get("/api/v1/topology").json()
    assert topo["reality"]["power_thermal"] == "labelled_assumption_not_telemetry"
    assert any(n["id"] == "orbital-iss-cheap" for n in topo["nodes"])
