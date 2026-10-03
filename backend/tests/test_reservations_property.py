"""Reservation exclusivity: no double-book on compute or reserved link-time."""

import pytest

from app.eval.market_day import count_stolen_windows, intervals_overlap


def _intervals(reservations):
    by = {}
    for r in reservations:
        by.setdefault(r.node_id, []).append((r.start, r.end, r.job_id))
    return by


@pytest.mark.unit
@pytest.mark.asyncio
async def test_many_jobs_never_overlap_same_node(world):
    for i in range(6):
        r = await world.submit_job(
            {
                "name": f"n{i}",
                "input_bytes": 250_000,
                "output_bytes": 50_000,
                "work": 180.0,
                "source_id": "gs-ashburn",
                "destination_id": "gs-ashburn",
                "forced_node_id": "earth-us-east",
                "deadline_at": 80_000,
            }
        )
        assert r.get("plan") or r.get("code") in {"quota_exceeded", "reservation_conflict"}

    planned = [p for p in world.plans.values() if p.compute_node_id == "earth-us-east"]
    assert len(planned) >= 2
    for i, a in enumerate(planned):
        for b in planned[i + 1 :]:
            assert not intervals_overlap(a.compute_start, a.compute_end, b.compute_start, b.compute_end)

    by_node = _intervals(world.reservations)
    for _node, rows in by_node.items():
        for i, (s0, e0, j0) in enumerate(rows):
            for s1, e1, j1 in rows[i + 1 :]:
                assert not intervals_overlap(s0, e0, s1, e1), (j0, j1, s0, e0, s1, e1)

    assert count_stolen_windows(world.reservations, world.link_reservations) == 0
    assert world.stolen_windows == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_link_reservations_exclusive_across_jobs(world):
    a = await world.submit_job(
        {
            "input_bytes": 2_000_000,
            "output_bytes": 200_000,
            "work": 30.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 40_000,
        }
    )
    b = await world.submit_job(
        {
            "input_bytes": 2_000_000,
            "output_bytes": 200_000,
            "work": 30.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 40_000,
        }
    )
    assert a.get("plan") and b.get("plan")
    by_link = {}
    for r in world.link_reservations:
        by_link.setdefault(r.link_id, []).append(r)
    for _lid, rows in by_link.items():
        ordered = sorted(rows, key=lambda x: (x.start, x.job_id))
        for i, later in enumerate(ordered):
            for earlier in ordered[:i]:
                assert not intervals_overlap(later.start, later.end, earlier.start, earlier.end)
