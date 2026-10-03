"""Market-day replay: two tenants, one shared sky, overload arrivals.

Reservation-aware per-tenant planning vs cheapest with tenant ids stripped.
Stolen-window must be zero for every reserved compute and link interval.
"""

from __future__ import annotations

import random
from typing import Any

from app.models.types import JobState, MarketDayReport
from app.tenants import DEFAULT_TENANT_ID


def intervals_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - 1e-9 and b0 < a1 - 1e-9


def count_stolen_windows(reservations: list, link_reservations: list) -> int:
    """Count later accepts that intersect an earlier reservation on the same resource."""
    stolen = 0
    by_node: dict[str, list] = {}
    for r in reservations:
        by_node.setdefault(r.node_id, []).append(r)
    for _node, rows in by_node.items():
        ordered = sorted(rows, key=lambda x: (x.start, x.job_id))
        for i, later in enumerate(ordered):
            for earlier in ordered[:i]:
                if intervals_overlap(later.start, later.end, earlier.start, earlier.end):
                    stolen += 1
    by_link: dict[str, list] = {}
    for r in link_reservations:
        by_link.setdefault(r.link_id, []).append(r)
    for _lid, rows in by_link.items():
        ordered = sorted(rows, key=lambda x: (x.start, x.job_id))
        for i, later in enumerate(ordered):
            for earlier in ordered[:i]:
                if intervals_overlap(later.start, later.end, earlier.start, earlier.end):
                    stolen += 1
    return stolen


def overload_script(seed: int, t0: float, n_per_tenant: int = 5) -> list[dict[str, Any]]:
    """Fixed mixed-deadline batch for alpha and beta (EDF order applied at submit)."""
    rng = random.Random(seed)
    jobs: list[dict[str, Any]] = []
    for i, tenant in enumerate(("alpha", "beta")):
        for j in range(n_per_tenant):
            jobs.append(
                {
                    "name": f"{tenant}-load-{j}",
                    "tenant_id": tenant,
                    "input_bytes": int(rng.choice([400_000, 800_000, 1_600_000])),
                    "output_bytes": int(rng.choice([80_000, 200_000])),
                    "work": float(rng.choice([40.0, 80.0, 120.0])),
                    "deadline_at": t0 + float(rng.choice([1200, 2400, 3600, 5400, 7200])),
                    "source_id": "gs-ashburn",
                    "destination_id": "gs-ashburn",
                    "seq_hint": i * n_per_tenant + j,
                }
            )
    return jobs


def _deadline_hits(world, tenant_id: str | None = None) -> tuple[int, int, float]:
    jobs = [
        j
        for j in world.jobs.values()
        if tenant_id is None or j.tenant_id == tenant_id
    ]
    n = len(jobs)
    hits = 0
    for j in jobs:
        if j.deadline_at is None and j.state == JobState.completed:
            hits += 1
        elif (
            j.deadline_at is not None
            and j.state == JobState.completed
            and j.actual_completion is not None
            and j.actual_completion <= j.deadline_at
        ):
            hits += 1
    return hits, n, (hits / n if n else 0.0)


def _total_cost(world) -> float:
    total = 0.0
    for j in world.jobs.values():
        plan = world.plans.get(j.plan_id or "")
        if plan:
            total += float(plan.estimated_cost)
    return total


async def _run_wave(world, bodies: list[dict[str, Any]], *, policy: str, max_steps: int) -> None:
    world.settings.headless = True
    await world.submit_batch(bodies, policy=policy)
    steps = 0
    while steps < max_steps:
        open_jobs = [
            j
            for j in world.jobs.values()
            if j.state not in (JobState.completed, JobState.failed, JobState.canceled)
        ]
        if not open_jobs:
            break
        await world.step()
        steps += 1


async def run_market_day(
    world,
    *,
    seed: int = 11,
    n_per_tenant: int = 5,
    max_steps: int = 2500,
) -> MarketDayReport:
    t0 = 0.0
    await world.reset()
    await world.seek(t0)
    script = overload_script(seed, t0, n_per_tenant=n_per_tenant)

    aware_bodies = [dict(j) for j in script]
    await _run_wave(world, aware_bodies, policy="planner", max_steps=max_steps)
    stolen = count_stolen_windows(world.reservations, world.link_reservations)
    world.stolen_windows = stolen
    cost_aware = _total_cost(world)
    _, _, hit_a = _deadline_hits(world, "alpha")
    _, _, hit_b = _deadline_hits(world, "beta")
    _, _, hit_aware = _deadline_hits(world, None)

    ignore_bodies = []
    for j in script:
        row = dict(j)
        row["tenant_id"] = DEFAULT_TENANT_ID
        row.pop("name", None)
        ignore_bodies.append(row)

    await world.reset()
    await world.seek(t0)
    await _run_wave(world, ignore_bodies, policy="cheapest", max_steps=max_steps)
    cost_ignore = _total_cost(world)
    _, _, hit_ignore = _deadline_hits(world, None)
    stolen_ignore = count_stolen_windows(world.reservations, world.link_reservations)

    report = MarketDayReport(
        id=world.ids.next("mkt"),
        scenario_id=world.settings.scenario_id,
        seed=seed,
        created_t=world.settings.t,
        n_jobs=len(script),
        deadline_hit_rate={"alpha": hit_a, "beta": hit_b, "reservation_aware": hit_aware},
        stolen_windows=stolen,
        stolen_windows_ignore_tenants=stolen_ignore,
        cost_reservation_aware=cost_aware,
        cost_global_cheapest_ignores_tenants=cost_ignore,
        deadline_hit_rate_ignores_tenants=hit_ignore,
        delta_cost=cost_aware - cost_ignore,
        delta_deadline_hit_rate=hit_aware - hit_ignore,
        job_script=script,
    )
    dumped = report.model_dump()
    world.evaluations[report.id] = dumped
    if world.store:
        world.store.put_evaluation(dumped)
    return report
