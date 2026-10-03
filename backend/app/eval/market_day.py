"""Market-day replay: several tenants, one shared sky, tight overload.

Reservation-aware per-tenant planning vs cheapest with tenant ids stripped.
Stolen-window must be zero for every reserved compute and link interval.

Fairness: hit-rate equity (1 − range of per-tenant hit rates) and min-tenant
hit rate. Reservation-aware should beat global-cheapest-ignores-tenants on
those metrics for the documented seeds (default seed 7).
"""

from __future__ import annotations

import random
from typing import Any, Iterable, Optional

from app.models.types import JobState, MarketDayReport
from app.tenants import DEFAULT_TENANT_ID

MARKET_TENANTS = ("alpha", "beta", "gamma", "delta")


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


def overload_script(
    seed: int,
    t0: float,
    n_per_tenant: int = 4,
    tenants: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    """Tight mixed-deadline batch. Later tenants get later deadlines so
    cheapest-ISS (ignore tenants) starves them more than reservation-aware."""
    names = tuple(tenants) if tenants else MARKET_TENANTS
    rng = random.Random(seed)
    jobs: list[dict[str, Any]] = []
    for i, tenant in enumerate(names):
        for j in range(n_per_tenant):
            # Tighter than the original 1200–7200 / 40–120 wave.
            slack = float(rng.choice([380, 520, 700, 900, 1100]))
            jobs.append(
                {
                    "name": f"{tenant}-load-{j}",
                    "tenant_id": tenant,
                    "input_bytes": int(rng.choice([800_000, 1_600_000, 2_400_000])),
                    "output_bytes": int(rng.choice([80_000, 160_000, 240_000])),
                    "work": float(rng.choice([90.0, 140.0, 200.0, 260.0])),
                    "deadline_at": t0 + slack + float(i * 90),
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


def hit_rate_equity(rates: dict[str, float]) -> float:
    """1 is perfectly even; 0 means one tenant at 1.0 and another at 0.0."""
    vals = [float(v) for v in rates.values()]
    if not vals:
        return 1.0
    return 1.0 - (max(vals) - min(vals))


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
    seed: int = 7,
    n_per_tenant: int = 4,
    max_steps: int = 2500,
    tenants: Optional[Iterable[str]] = None,
) -> MarketDayReport:
    names = tuple(tenants) if tenants else MARKET_TENANTS
    t0 = 0.0
    await world.reset()
    await world.seek(t0)
    script = overload_script(seed, t0, n_per_tenant=n_per_tenant, tenants=names)

    aware_bodies = [dict(j) for j in script]
    await _run_wave(world, aware_bodies, policy="planner", max_steps=max_steps)
    stolen = count_stolen_windows(world.reservations, world.link_reservations)
    world.stolen_windows = stolen
    cost_aware = _total_cost(world)
    rates_aware: dict[str, float] = {}
    for tid in names:
        _, _, hit = _deadline_hits(world, tid)
        rates_aware[tid] = hit
    _, _, hit_aware = _deadline_hits(world, None)
    rates_aware["reservation_aware"] = hit_aware

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

    # Reconstruct ignore-tenants per original tenant from the same EDF order.
    ignore_by_origin: dict[str, list] = {tid: [] for tid in names}

    def _edf_body(b: dict[str, Any]):
        d = b.get("deadline_at")
        return (float(d) if d is not None else 1e18, float(b.get("work") or 0))

    for body, job in zip(
        sorted(script, key=_edf_body),
        sorted(world.jobs.values(), key=lambda j: (j.deadline_at or 1e18, j.work, j.id)),
    ):
        ignore_by_origin.setdefault(body["tenant_id"], []).append(job)

    # submit_batch is EDF on the ignore wave too; pair by the same EDF key.
    rates_ignore_origin: dict[str, float] = {}
    for tid in names:
        rows = ignore_by_origin.get(tid) or []
        n = len(rows)
        hits = 0
        for j in rows:
            if j.deadline_at is None and j.state == JobState.completed:
                hits += 1
            elif (
                j.deadline_at is not None
                and j.state == JobState.completed
                and j.actual_completion is not None
                and j.actual_completion <= j.deadline_at
            ):
                hits += 1
        rates_ignore_origin[tid] = hits / n if n else 0.0

    tenant_rates = {tid: rates_aware[tid] for tid in names}
    equity = hit_rate_equity(tenant_rates)
    equity_ignore = hit_rate_equity(rates_ignore_origin)
    min_hit = min(tenant_rates.values()) if tenant_rates else 0.0
    min_hit_ignore = min(rates_ignore_origin.values()) if rates_ignore_origin else 0.0
    rng = max(tenant_rates.values()) - min(tenant_rates.values()) if tenant_rates else 0.0
    rng_ignore = (
        max(rates_ignore_origin.values()) - min(rates_ignore_origin.values()) if rates_ignore_origin else 0.0
    )
    beats = (min_hit > min_hit_ignore + 1e-12) or (
        equity > equity_ignore + 1e-12 and hit_aware + 1e-12 >= hit_ignore
    )

    report = MarketDayReport(
        id=world.ids.next("mkt"),
        scenario_id=world.settings.scenario_id,
        seed=seed,
        created_t=world.settings.t,
        n_jobs=len(script),
        deadline_hit_rate=rates_aware,
        stolen_windows=stolen,
        stolen_windows_ignore_tenants=stolen_ignore,
        cost_reservation_aware=cost_aware,
        cost_global_cheapest_ignores_tenants=cost_ignore,
        deadline_hit_rate_ignores_tenants=hit_ignore,
        delta_cost=cost_aware - cost_ignore,
        delta_deadline_hit_rate=hit_aware - hit_ignore,
        job_script=script,
        tenants=list(names),
        hit_rate_equity=equity,
        hit_rate_equity_ignores_tenants=equity_ignore,
        min_tenant_hit_rate=min_hit,
        min_tenant_hit_rate_ignores_tenants=min_hit_ignore,
        hit_rate_range=rng,
        hit_rate_range_ignores_tenants=rng_ignore,
        fairness_beats_ignore_tenants=beats,
    )
    dumped = report.model_dump()
    world.evaluations[report.id] = dumped
    if world.store:
        world.store.put_evaluation(dumped)
    return report
