"""Product-path e2e: Case A/B for both tenants + market-day contract."""

import pytest

from app.eval.market_day import run_market_day


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_case_a_b_both_tenants_and_market_day(world):
    for tenant in ("alpha", "beta"):
        a = await world.submit_thesis("a", tenant_id=tenant, reset=True)
        assert a["plan"]["compute_node_id"] == "earth-us-east"
        assert a["job"]["tenant_id"] == tenant
        b = await world.submit_thesis("b", tenant_id=tenant, reset=True)
        assert b["plan"]["compute_node_id"] == "orbital-iss-cheap"
        assert "chose_cheapest_node" in b["plan"]["baseline_comparison"]["reason_codes"]

    report = await run_market_day(world, seed=11, n_per_tenant=2, max_steps=500)
    assert report.stolen_windows == 0
    assert set(report.deadline_hit_rate) >= {"alpha", "beta"}
    again = await run_market_day(world, seed=11, n_per_tenant=2, max_steps=500)
    assert again.deadline_hit_rate == report.deadline_hit_rate
    assert again.cost_reservation_aware == report.cost_reservation_aware
