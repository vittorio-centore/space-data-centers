"""HTTP market-day metrics contract."""

import os

os.environ.setdefault("SDC_PERSIST", "0")
os.environ.setdefault("SDC_HEADLESS", "1")

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.integration
def test_market_day_http_contract():
    res = client.post(
        "/api/v1/evaluations/market-day",
        json={"seed": 11, "n_per_tenant": 2, "max_steps": 400},
    )
    assert res.status_code == 200
    row = res.json()
    assert row["stolen_windows"] == 0
    rates = row["deadline_hit_rate"]
    assert "alpha" in rates and "beta" in rates
    assert "gamma" in rates and "delta" in rates
    assert 0.0 <= rates["alpha"] <= 1.0
    assert 0.0 <= rates["beta"] <= 1.0
    assert row["cost_reservation_aware"] >= 0
    assert row["cost_global_cheapest_ignores_tenants"] >= 0
    assert row["seed"] == 11
    assert row["n_jobs"] == 8
    assert "hit_rate_equity" in row
    assert row["stolen_windows"] == 0


@pytest.mark.integration
def test_market_day_legacy_alias():
    res = client.post(
        "/evaluations/market-day",
        json={"seed": 5, "n_per_tenant": 1, "max_steps": 200},
    )
    assert res.status_code == 200
    assert res.json()["stolen_windows"] == 0
