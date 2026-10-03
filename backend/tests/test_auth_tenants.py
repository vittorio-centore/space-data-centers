"""Per-tenant API keys and default-open isolation."""

import os

os.environ.setdefault("SDC_PERSIST", "0")
os.environ.setdefault("SDC_HEADLESS", "1")

import pytest
from fastapi.testclient import TestClient

from app.auth import extract_key, key_ok, resolve_tenant_id
from app.main import app
from app.tenants import parse_tenant_key_map, tenant_for_key


@pytest.mark.unit
def test_parse_tenant_key_map():
    m = parse_tenant_key_map("sdc-alpha:alpha,sdc-beta:beta")
    assert m["sdc-alpha"] == "alpha"
    assert m["sdc-beta"] == "beta"
    assert tenant_for_key("sdc-alpha", m) == "alpha"
    assert tenant_for_key("nope", m) is None
    assert tenant_for_key("", m) is None


@pytest.mark.unit
def test_extract_key_header_and_bearer():
    assert extract_key({"X-API-Key": "abc"}) == "abc"
    assert extract_key({"authorization": "Bearer xyz"}) == "xyz"
    assert extract_key({}, "from-query") == "from-query"


@pytest.mark.unit
def test_open_mode_resolves_default(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("SDC_TENANT_KEYS", raising=False)
    assert resolve_tenant_id("") == "local"
    assert key_ok("") is True


@pytest.mark.integration
def test_per_tenant_keys_scope_jobs(monkeypatch):
    monkeypatch.setenv("SDC_TENANT_KEYS", "sdc-alpha:alpha,sdc-beta:beta")
    monkeypatch.setenv("API_KEY", "sdc-local")
    client = TestClient(app)
    denied = client.get("/api/v1/jobs")
    assert denied.status_code == 401
    assert client.get("/api/v1/health").status_code == 200

    client.post("/api/v1/sim/reset", headers={"X-API-Key": "sdc-alpha"})
    a = client.post(
        "/api/v1/jobs",
        headers={"X-API-Key": "sdc-alpha"},
        json={
            "name": "alpha-only",
            "input_bytes": 300_000,
            "output_bytes": 60_000,
            "work": 12.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "policy": "earth_only",
        },
    )
    assert a.status_code == 200
    aid = a.json()["job"]["id"]
    as_beta = client.get(f"/api/v1/jobs/{aid}", headers={"X-API-Key": "sdc-beta"})
    assert as_beta.status_code == 404
    listed = client.get("/api/v1/jobs", headers={"X-API-Key": "sdc-beta"}).json()
    assert all(j["id"] != aid for j in listed)
    mine = client.get("/api/v1/jobs", headers={"X-API-Key": "sdc-alpha"}).json()
    assert any(j["id"] == aid for j in mine)


@pytest.mark.integration
def test_wrong_key_rejected(monkeypatch):
    monkeypatch.setenv("API_KEY", "sdc-demo")
    client = TestClient(app)
    bad = client.get("/api/v1/topology", headers={"X-API-Key": "nope"})
    assert bad.status_code == 401
    assert bad.json()["code"] == "unauthorized"
