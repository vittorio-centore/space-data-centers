import pytest

from app.models.types import JobState


@pytest.mark.asyncio
async def test_disruption_replan_or_migrate(world):
    r = await world.submit_job(
        {
            "input_bytes": 3_000_000,
            "output_bytes": 200_000,
            "work": 40.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 20_000,
            "disruption_policy": "migrate_on_disruption",
        }
    )
    job_id = r["job"]["id"]
    # Take down every terrestrial link so Earth route dies
    for L in world.links:
        if "earth-us-east" in (L.endpoint_a, L.endpoint_b):
            world.disrupt_link(L.id, down=True)
    out = await world.try_replan(job_id)
    job = world.jobs[job_id]
    assert out.get("ok") or job.state == JobState.failed
    if out.get("migrated"):
        assert job.assigned_node_id != "earth-us-east"


@pytest.mark.asyncio
async def test_safe_migrate_on_node_outage(world):
    r = await world.submit_job(
        {
            "input_bytes": 500_000,
            "output_bytes": 80_000,
            "work": 30.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 20_000,
            "disruption_policy": "migrate_on_disruption",
        }
    )
    job_id = r["job"]["id"]
    world.set_outage("earth-us-east", down=True, reason="test")
    out = await world.try_replan(job_id)
    job = world.jobs[job_id]
    if out.get("ok"):
        assert job.assigned_node_id != "earth-us-east"
        assert world.plans[job.plan_id].migrated_from_node_id == "earth-us-east"
    else:
        assert job.state.value == "failed"
