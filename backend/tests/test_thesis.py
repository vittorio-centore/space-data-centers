import pytest


@pytest.mark.asyncio
async def test_case_a_cheap_loses(world):
    result = await world.submit_thesis("a")
    plan = result["plan"]
    assert plan is not None
    assert plan["compute_node_id"] == "earth-us-east"
    reasons = plan["baseline_comparison"]["reason_codes"]
    assert "baseline_misses_deadline" in reasons or "chose_non_cheapest" in reasons


@pytest.mark.asyncio
async def test_case_b_cheap_wins(world):
    result = await world.submit_thesis("b")
    plan = result["plan"]
    assert plan is not None
    assert plan["compute_node_id"] == "orbital-iss-cheap"
    reasons = plan["baseline_comparison"]["reason_codes"]
    assert "chose_cheapest_node" in reasons
