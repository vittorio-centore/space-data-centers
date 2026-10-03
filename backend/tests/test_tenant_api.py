import asyncio
import os

os.environ.setdefault("SDC_PERSIST", "0")
os.environ.setdefault("SDC_HEADLESS", "1")

from fastapi.testclient import TestClient

from app.main import app, world

client = TestClient(app)


def test_api_isolation_and_files():
    client.post("/api/v1/sim/reset")
    seeded = asyncio.run(
        world.submit_job(
            {
                "name": "probe",
                "tenant_id": "beta",
                "input_bytes": 300_000,
                "output_bytes": 60_000,
                "work": 12.0,
                "source_id": "gs-ashburn",
                "destination_id": "gs-ashburn",
                "forced_node_id": "earth-us-east",
            }
        )
    )
    beta_id = seeded["job"]["id"]
    listed = client.get("/api/v1/jobs").json()
    assert all(j["tenant_id"] == "local" for j in listed)
    assert all(j["id"] != beta_id for j in listed)
    assert client.get(f"/api/v1/jobs/{beta_id}").status_code == 404
    assert client.post(f"/api/v1/jobs/{beta_id}/cancel").status_code == 404

    world.put_file("beta", "workloads/probe.bin", b"secret-beta")
    put = client.put(
        "/api/v1/files",
        json={"path": "workloads/probe.bin", "content": "local-bytes", "content_type": "text/plain"},
    )
    assert put.status_code == 200
    got = client.get("/api/v1/files/workloads/probe.bin")
    assert got.status_code == 200
    assert got.json()["content"] == "local-bytes"
    assert world.get_file("beta", "workloads/probe.bin").nbytes == len(b"secret-beta")

    mine = client.post(
        "/api/v1/jobs",
        json={
            "name": "probe",
            "input_bytes": 300_000,
            "output_bytes": 60_000,
            "work": 12.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "policy": "earth_only",
        },
    )
    assert mine.status_code == 200
    assert mine.json()["job"]["name"] == "probe"
    assert mine.json()["job"]["id"] != beta_id
    tenants = client.get("/api/v1/tenants").json()
    ids = {t["id"] for t in tenants}
    assert {"local", "alpha", "beta"} <= ids


def test_topology_still_labels_simulated():
    topo = client.get("/api/v1/topology").json()
    assert topo["reality"]["compute"] == "simulated"
    assert topo["reality"]["bandwidth_pricing"] == "simulated"
