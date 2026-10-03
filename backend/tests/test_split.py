"""Partitioned jobs: planner may split when it beats single-node."""

import pytest

from app.eval.market_day import count_stolen_windows
from app.models.types import Reservation


def _occupy(world, node_id: str, start: float, end: float, job_id: str) -> None:
    world.reservations.append(
        Reservation(job_id=job_id, tenant_id="local", node_id=node_id, start=start, end=end)
    )
    if node_id in world.node_by_id:
        world.node_by_id[node_id].available_at = max(world.node_by_id[node_id].available_at, end)


@pytest.mark.asyncio
async def test_split_beats_blocked_single_node_and_no_overlap(world):
    """Short early gaps on two nodes cannot fit the full job but can fit shards."""
    for n in world.nodes:
        _occupy(world, n.id, 80.0, 20_000.0, f"block-{n.id}")

    # Earth + CSS: leave only ~55s free after typical terrestrial delivery.
    world.reservations = [r for r in world.reservations if r.node_id not in ("earth-us-east", "orbital-css")]
    world.node_by_id["earth-us-east"].available_at = 0.0
    world.node_by_id["orbital-css"].available_at = 0.0
    _occupy(world, "earth-us-east", 55.0, 20_000.0, "gap-earth")
    _occupy(world, "orbital-css", 55.0, 20_000.0, "gap-css")

    r = await world.submit_job(
        {
            "name": "shard-me",
            "input_bytes": 200_000,
            "output_bytes": 40_000,
            "work": 3600.0,
            "deadline_at": 70.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "allow_split": True,
        }
    )
    plan = r.get("plan")
    assert plan is not None, r.get("error")
    assert plan["is_split"] is True
    nodes = [p["node_id"] for p in plan["partitions"]]
    assert len(nodes) >= 2
    assert len(set(nodes)) == len(nodes)
    assert "chose_partition" in plan["baseline_comparison"]["reason_codes"]
    assert plan["split_assumptions"]
    assert any("store_and_forward" in a for a in plan["split_assumptions"])

    mine = [res for res in world.reservations if res.job_id == r["job"]["id"]]
    assert len(mine) >= 2
    assert count_stolen_windows(world.reservations, world.link_reservations) == 0
    # Shards of this job must not overlap each other on the same node.
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
    assert r["job"]["assigned_node_id"]
