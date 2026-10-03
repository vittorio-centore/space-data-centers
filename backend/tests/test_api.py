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


def test_contacts_inspector_endpoint():
    client.post("/api/v1/sim/reset")
    res = client.get("/api/v1/contacts", params={"horizon_s": 600})
    assert res.status_code == 200
    body = res.json()
    assert body["grid"] == "sim_step_from_epoch"
    assert body["step_s"] == 5.0
    assert len(body["links"]) >= 3
    assert all("windows" in row and "link_id" in row for row in body["links"])


def test_job_submit_and_plan_history():
    client.post("/api/v1/sim/reset")
    res = client.post(
        "/api/v1/jobs",
        json={
            "input_bytes": 500_000,
            "output_bytes": 80_000,
            "work": 20.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "policy": "earth_only",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["plan"]["compute_node_id"].startswith("earth-")
    job_id = body["job"]["id"]
    hist = client.get(f"/api/v1/jobs/{job_id}/plans")
    assert hist.status_code == 200
    assert isinstance(hist.json(), list)
    detail = client.get(f"/api/v1/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["job"]["id"] == job_id


def test_batch_and_round_robin_api():
    client.post("/api/v1/sim/reset")
    res = client.post(
        "/api/v1/jobs/batch",
        json={
            "policy": "round_robin",
            "jobs": [
                {
                    "input_bytes": 400_000,
                    "output_bytes": 80_000,
                    "work": 15.0,
                    "source_id": "gs-ashburn",
                    "destination_id": "gs-ashburn",
                    "deadline_at": 4000,
                },
                {
                    "input_bytes": 400_000,
                    "output_bytes": 80_000,
                    "work": 15.0,
                    "source_id": "gs-ashburn",
                    "destination_id": "gs-ashburn",
                    "deadline_at": 5000,
                },
            ],
        },
    )
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 2
    nodes = [r["plan"]["compute_node_id"] for r in rows if r.get("plan")]
    assert len(nodes) >= 1


def test_outage_evaluations_scenarios():
    client.post("/api/v1/sim/reset")
    out = client.post("/api/v1/nodes/earth-us-east/outage", json={"down": True, "reason": "test"})
    assert out.status_code == 200
    pwr = client.get("/api/v1/nodes/earth-us-east/power")
    assert pwr.status_code == 200
    ev = client.post(
        "/api/v1/evaluations",
        json={"seed": 3, "n_jobs": 2, "policies": ["earth_only"], "max_steps": 80},
    )
    assert ev.status_code == 200
    eid = ev.json()["id"]
    listed = client.get("/api/v1/evaluations")
    assert listed.status_code == 200
    one = client.get(f"/api/v1/evaluations/{eid}")
    assert one.status_code == 200
    sc = client.get("/api/v1/scenarios")
    assert sc.status_code == 200
    names = {s["id"] if isinstance(s, dict) else s for s in sc.json()} if isinstance(sc.json(), list) else set()
    # catalog may be list of dicts or strings
    blob = str(sc.json())
    assert "mvp-thesis" in blob
