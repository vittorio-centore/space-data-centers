"""Link disruption advances the sim clock and triggers replan."""

import pytest

from app.models.types import JobState


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disruption_then_replan_uses_sim_clock(world):
    await world.reset()
    r = await world.submit_job(
        {
            "input_bytes": 3_000_000,
            "output_bytes": 200_000,
            "work": 40.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 20_000,
        }
    )
    job_id = r["job"]["id"]
    t_before = world.settings.t
    for L in world.links:
        if "earth-us-east" in (L.endpoint_a, L.endpoint_b):
            world.disrupt_link(L.id, down=True)
    await world.step()
    assert world.settings.t == pytest.approx(t_before + world.settings.sim_step_s)
    out = await world.try_replan(job_id)
    job = world.jobs[job_id]
    assert out.get("ok") or job.state == JobState.failed
    if out.get("ok"):
        assert job.plan_id
        hist = [p for p in world.plan_revisions if p.job_id == job_id]
        assert len(hist) >= 1
