from __future__ import annotations

import os

os.environ["SDC_PERSIST"] = "0"
os.environ["SDC_HEADLESS"] = "1"
os.environ["SDC_SCENARIO"] = "mvp-thesis"
os.environ["SDC_LOG_JSON"] = "0"
os.environ.pop("API_KEY", None)
os.environ.pop("SDC_TENANT_KEYS", None)

import pytest

from app.config import AppConfig
from app.sim.world import SimWorld

# Filename → default marker when a test does not declare one.
_INTEGRATION_FILES = {
    "test_api.py",
    "test_api_aliases.py",
    "test_auth.py",
    "test_auth_tenants.py",
    "test_crash.py",
    "test_market_day_api.py",
    "test_persist.py",
    "test_tenant_api.py",
    "test_ws.py",
}
_E2E_FILES = {
    "test_e2e_platform.py",
}
_E2E_NAMES = {
    "test_market_day_metrics",
    "test_case_a_b_per_tenant",
}


def pytest_collection_modifyitems(items):
    for item in items:
        names = {m.name for m in item.iter_markers()}
        fname = item.path.name if hasattr(item, "path") else item.fspath.basename
        if "e2e" not in names and (fname in _E2E_FILES or item.name in _E2E_NAMES):
            item.add_marker(pytest.mark.e2e)
            names.add("e2e")
        if "integration" not in names and fname in _INTEGRATION_FILES:
            item.add_marker(pytest.mark.integration)
            names.add("integration")
        if "unit" not in names and "integration" not in names and "e2e" not in names:
            item.add_marker(pytest.mark.unit)


@pytest.fixture
def world(tmp_path):
    cfg = AppConfig(db_path=tmp_path / "t.sqlite", persist=False, headless=True, scenario="mvp-thesis", log_json=False)
    return SimWorld(cfg, restore=False)


def earth_job(**extra):
    body = {
        "input_bytes": 400_000,
        "output_bytes": 80_000,
        "work": 20.0,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
        "forced_node_id": "earth-us-east",
        "deadline_at": 50_000,
    }
    body.update(extra)
    return body
