"""Concurrent batch submit + earliest-deadline-first ordering."""

import asyncio

import pytest


def _job(name, deadline, work=15.0, tenant="local"):
    return {
        "name": name,
        "tenant_id": tenant,
        "input_bytes": 300_000,
        "output_bytes": 60_000,
        "work": work,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
        "forced_node_id": "earth-us-east",
        "deadline_at": deadline,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_batch_is_earliest_deadline_first(world):
    rows = await world.submit_batch(
        [_job("late", 9000), _job("early", 4000), _job("mid", 6000)],
        policy="planner",
    )
    names = [r["job"]["name"] for r in rows if r.get("job")]
    assert names == ["early", "mid", "late"]
    starts = [r["plan"]["compute_start"] for r in rows if r.get("plan")]
    assert starts == sorted(starts)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_batches_no_double_book(world):
    left = [_job(f"a{i}", 10_000 + i * 100, work=80.0, tenant="alpha") for i in range(3)]
    right = [_job(f"b{i}", 10_050 + i * 100, work=80.0, tenant="beta") for i in range(3)]
    a_rows, b_rows = await asyncio.gather(
        world.submit_batch(left, policy="planner"),
        world.submit_batch(right, policy="planner"),
    )
    planned = [r for r in a_rows + b_rows if r.get("plan")]
    assert len(planned) >= 2
    slots = [(p["plan"]["compute_start"], p["plan"]["compute_end"], p["plan"]["compute_node_id"]) for p in planned]
    for i, (s0, e0, n0) in enumerate(slots):
        for s1, e1, n1 in slots[i + 1 :]:
            if n0 != n1:
                continue
            assert not (s0 < e1 - 1e-9 and s1 < e0 - 1e-9)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sim_clock_steps_without_wall_sleep(world):
    t0 = world.settings.t
    step = world.settings.sim_step_s
    await world.step()
    assert world.settings.t == pytest.approx(t0 + step)
    await world.seek(1234.0)
    assert world.settings.t == pytest.approx(1234.0)
    await world.step()
    assert world.settings.t == pytest.approx(1234.0 + step)
