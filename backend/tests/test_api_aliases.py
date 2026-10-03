"""v1 paths and legacy root aliases stay in lockstep."""

import os

os.environ.setdefault("SDC_PERSIST", "0")
os.environ.setdefault("SDC_HEADLESS", "1")

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ALIASES = (
    ("/api/v1/health", "/health"),
    ("/api/v1/ready", "/ready"),
    ("/api/v1/topology", "/topology"),
    ("/api/v1/tenants", "/tenants"),
    ("/api/v1/scenarios", "/scenarios"),
    ("/api/v1/settings", "/settings"),
    ("/api/v1/snapshot", "/snapshot"),
)


@pytest.mark.integration
def test_v1_and_legacy_get_parity():
    for v1, legacy in ALIASES:
        a = client.get(v1)
        b = client.get(legacy)
        assert a.status_code == 200, v1
        assert b.status_code == 200, legacy
        ja, jb = a.json(), b.json()
        if isinstance(ja, dict) and "ok" in ja:
            assert ja["ok"] is True and jb["ok"] is True
        elif isinstance(ja, list):
            assert len(ja) == len(jb)
        else:
            assert set(ja.keys()) == set(jb.keys())


@pytest.mark.integration
def test_thesis_preset_aliases():
    client.post("/api/v1/sim/reset")
    a = client.post("/api/v1/presets/thesis/a")
    assert a.status_code == 200
    body = a.json()
    assert body["plan"]["compute_node_id"] == "earth-us-east"
    client.post("/sim/reset")
    b = client.post("/presets/thesis/b")
    assert b.status_code == 200
    assert b.json()["plan"]["compute_node_id"] == "orbital-iss-cheap"


@pytest.mark.integration
def test_play_pause_step_seek_legacy():
    client.post("/api/v1/sim/reset")
    seek = client.post("/api/v1/sim/seek", json={"t": 42})
    assert seek.status_code == 200
    assert seek.json()["t"] == pytest.approx(42)
    step = client.post("/sim/step")
    assert step.status_code == 200
    assert step.json()["t"] > 42
    pause = client.post("/api/v1/sim/pause")
    assert pause.json()["playing"] is False
    play = client.post("/sim/play")
    assert play.json()["playing"] is True
    client.post("/api/v1/sim/pause")
