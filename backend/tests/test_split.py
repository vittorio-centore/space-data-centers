"""Partitioned jobs: planner may split when it beats single-node."""

import pytest

from app.eval.market_day import count_stolen_windows
from app.models.types import (
    Job,
    JobState,
    Plan,
    PlanPartition,
    Reservation,
)


def test_apply_split_plan_books_distinct_nodes_without_overlap(world):
    job = Job(
        id="job-split",
        submitted_at=0.0,
        input_bytes=1000,
        output_bytes=100,
        work=100.0,
        source_id="gs-ashburn",
        destination_id="gs-ashburn",
        allow_split=True,
    )
    world.jobs[job.id] = job
    plan = Plan(
        id="plan-split",
        job_id=job.id,
        compute_node_id="earth-us-east",
        input_route=[],
        output_route=[],
        compute_start=10.0,
        compute_end=40.0,
        estimated_cost=1.0,
        estimated_completion=40.0,
        is_split=True,
        partitions=[
            PlanPartition(
                node_id="earth-us-east",
                work=50.0,
                input_bytes=500,
                output_bytes=50,
                compute_start=10.0,
                compute_end=30.0,
                estimated_cost=0.5,
                estimated_completion=30.0,
            ),
            PlanPartition(
                node_id="orbital-css",
                work=50.0,
                input_bytes=500,
                output_bytes=50,
                compute_start=12.0,
                compute_end=40.0,
                estimated_cost=0.5,
                estimated_completion=40.0,
            ),
        ],
    )
    world._apply_reservations(job, plan)
    mine = [r for r in world.reservations if r.job_id == job.id]
    assert {r.node_id for r in mine} == {"earth-us-east", "orbital-css"}
    assert count_stolen_windows(world.reservations, world.link_reservations) == 0
    # Same job, different nodes — intervals may overlap in time.
    assert mine[0].node_id != mine[1].node_id


@pytest.mark.asyncio
async def test_split_beats_short_gaps_during_css_contact(world):
    windows = world._contact_windows("gs-ashburn", "orbital-css", 0.0, 86400.0)
    assert windows, "need a CSS–Ashburn window"
    t0 = windows[0][0] + 5.0
    await world.seek(t0)

    world.reservations.clear()
    world.tenants["local"].quota_reserved_s = 1_000_000.0
    for n in world.nodes:
        n.available_at = 0.0
        world.reservations.append(
            Reservation(
                job_id=f"block-{n.id}",
                tenant_id="local",
                node_id=n.id,
                start=t0 + 48.0,
                end=t0 + 30_000.0,
            )
        )
        n.available_at = t0 + 48.0

    r = await world.submit_job(
        {
            "name": "shard-me",
            "input_bytes": 80_000,
            "output_bytes": 8_000,
            "work": 3600.0,
            "deadline_at": t0 + 55.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "allow_split": True,
        }
    )
    plan = r.get("plan")
    assert plan is not None, r.get("error")
    assert plan["is_split"] is True, plan.get("baseline_comparison")
    nodes = [p["node_id"] for p in plan["partitions"]]
    assert len(set(nodes)) == len(nodes) >= 2
    assert "chose_partition" in plan["baseline_comparison"]["reason_codes"]
    assert any("store_and_forward" in a for a in plan["split_assumptions"])
    assert count_stolen_windows(world.reservations, world.link_reservations) == 0
    mine = [res for res in world.reservations if res.job_id == r["job"]["id"]]
    by_node: dict[str, list] = {}
    for res in mine:
        by_node.setdefault(res.node_id, []).append(res)
    for rows in by_node.values():
        rows.sort(key=lambda x: x.start)
        for a, b in zip(rows, rows[1:]):
            assert a.end <= b.start + 1e-9


@pytest.mark.asyncio
async def test_split_off_keeps_single_node(world):
    r = await world.submit_job(
        {
            "input_bytes": 200_000,
            "output_bytes": 40_000,
            "work": 40.0,
            "deadline_at": 20_000,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "allow_split": False,
        }
    )
    assert r["plan"] is not None
    assert r["plan"]["is_split"] is False
    assert r["plan"]["partitions"] == []
    assert r["job"]["state"] == JobState.planned.value or r["job"]["assigned_node_id"]
