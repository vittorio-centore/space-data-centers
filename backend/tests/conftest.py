from __future__ import annotations

import os

os.environ["SDC_PERSIST"] = "0"
os.environ["SDC_HEADLESS"] = "1"
os.environ["SDC_SCENARIO"] = "mvp-thesis"
os.environ["SDC_LOG_JSON"] = "0"

import pytest

from app.config import AppConfig
from app.sim.world import SimWorld


@pytest.fixture
def world(tmp_path):
    cfg = AppConfig(db_path=tmp_path / "t.sqlite", persist=False, headless=True, scenario="mvp-thesis", log_json=False)
    return SimWorld(cfg, restore=False)
