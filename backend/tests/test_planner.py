import pytest


@pytest.mark.asyncio
async def test_planner_deterministic(world):
    body = {
        "input_bytes": 1_000_000,
        "output_bytes": 200_000,
        "work": 50.0,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
        "deadline_at": 5000,
    }
    a = await world.submit_job(body)
    await world.reset()
    b = await world.submit_job(body)
    assert a["plan"]["compute_node_id"] == b["plan"]["compute_node_id"]
    assert a["plan"]["estimated_cost"] == b["plan"]["estimated_cost"]
    assert a["plan"]["estimated_completion"] == b["plan"]["estimated_completion"]
    assert a["plan"]["input_route"] == b["plan"]["input_route"]


@pytest.mark.asyncio
async def test_baseline_fields_present(world):
    r = await world.submit_job(
        {
            "input_bytes": 1_000_000,
            "output_bytes": 200_000,
            "work": 50.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
        }
    )
    bc = r["baseline_comparison"]
    assert bc["baseline_node_id"]
    assert "chosen_node_id" in bc
    assert isinstance(bc["reason_codes"], list)


@pytest.mark.asyncio
async def test_earth_only_policy(world):
    r = await world.submit_job(
        {
            "input_bytes": 500_000,
            "output_bytes": 100_000,
            "work": 30.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "policy": "earth_only",
        }
    )
    assert r["plan"]["compute_node_id"].startswith("earth-")
