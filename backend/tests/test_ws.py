"""WebSocket hello + sim-clock events (no wall-clock sleeps)."""

import os

os.environ.setdefault("SDC_PERSIST", "0")
os.environ.setdefault("SDC_HEADLESS", "1")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.integration
def test_ws_hello_and_step_event():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["payload"]["reality"].startswith("ephemeris")
        client.post("/api/v1/sim/step")
        ev = ws.receive_json()
        assert "type" in ev
        assert "t" in ev


@pytest.mark.integration
def test_ws_legacy_alias():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
