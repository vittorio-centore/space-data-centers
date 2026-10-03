"""Mid-compute migrate is opt-in; default stays node-fixed."""

import pytest

from app.models.types import DISRUPTION_MIGRATE, DISRUPTION_NODE_FIXED, JobState


def _earth_job(**extra):
    body = {
        "input_bytes": 400_000,
        "output_bytes": 80_000,
        "work": 2000.0,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
        "forced_node_id": "earth-us-east",
        "deadline_at": 20_000,
    }
    body.update(extra)
    return body


async def _run_until(world, job_id: str, state: JobState, max_steps: int = 80):
    for _ in range(max_steps):
        if world.jobs[job_id].state == state:
            return
        if world.jobs[job_id].state in (JobState.failed, JobState.canceled, JobState.completed):
            return
        await world.step()


@pytest.mark.asyncio
async def test_default_node_fixed_refuses_mid_compute_migrate(world):
    r = await world.submit_job(_earth_job())
    job_id = r["job"]["id"]
    await _run_until(world, job_id, JobState.running)
    assert world.jobs[job_id].state == JobState.running
    assert world.jobs[job_id].disruption_policy == DISRUPTION_NODE_FIXED
    world.set_outage("earth-us-east", down=True, reason="test")
    out = await world.try_replan(job_id)
    job = world.jobs[job_id]
    assert out.get("ok") is False
    assert out.get("migrated") is not True
    assert job.state == JobState.failed
    assert job.assigned_node_id == "earth-us-east"
    assert "node_fixed" in (job.fail_reason or "")


@pytest.mark.asyncio
async def test_migrate_on_disruption_restarts_checkpointable_image_batch(world):
    r = await world.submit_job(_earth_job(disruption_policy=DISRUPTION_MIGRATE))
    job_id = r["job"]["id"]
    await _run_until(world, job_id, JobState.running)
    assert world.jobs[job_id].state == JobState.running
    assert world.jobs[job_id].checkpointable is True
    world.set_outage("earth-us-east", down=True, reason="test")
    out = await world.try_replan(job_id)
    job = world.jobs[job_id]
    assert out.get("ok") is True
    assert out.get("migrated") is True
    assert job.assigned_node_id != "earth-us-east"
    assert world.plans[job.plan_id].migrated_from_node_id == "earth-us-east"


@pytest.mark.asyncio
async def test_migrate_policy_refuses_non_checkpointable_mid_run(world):
    r = await world.submit_job(
        _earth_job(
            disruption_policy=DISRUPTION_MIGRATE,
            workload_kind="opaque_mpi",
            checkpointable=False,
        )
    )
    job_id = r["job"]["id"]
    await _run_until(world, job_id, JobState.running)
    assert world.jobs[job_id].state == JobState.running
    world.set_outage("earth-us-east", down=True, reason="test")
    out = await world.try_replan(job_id)
    job = world.jobs[job_id]
    assert out.get("ok") is False
    assert job.state == JobState.failed
    assert job.assigned_node_id == "earth-us-east"
    assert "checkpointable" in (job.fail_reason or "")


@pytest.mark.asyncio
async def test_settings_disruption_policy_is_exposed(world):
    assert world.settings.disruption_policy == DISRUPTION_NODE_FIXED
    world.settings.disruption_policy = DISRUPTION_MIGRATE
    r = await world.submit_job(_earth_job())
    assert r["job"]["disruption_policy"] == DISRUPTION_MIGRATE
