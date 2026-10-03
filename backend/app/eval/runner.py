"""Headless multi-policy evaluation. Planner itself is deterministic; seed only builds the job list."""

from __future__ import annotations

import random
from typing import Any

from app.models.types import EvaluationPolicyRow, EvaluationReport, JobState


POLICIES = ("planner", "cheapest", "earliest", "earth_only", "round_robin")


def seeded_jobs(seed: int, n: int, t0: float, source_id: str, dest_id: str) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    jobs: list[dict[str, Any]] = []
    for _i in range(n):
        jobs.append(
            {
                "input_bytes": int(rng.choice([2_000_000, 4_000_000, 8_000_000])),
                "output_bytes": int(rng.choice([400_000, 1_000_000])),
                "work": float(rng.choice([80.0, 120.0, 180.0])),
                "deadline_at": t0 + float(rng.choice([900, 1800, 3600, 5400])),
                "source_id": source_id,
                "destination_id": dest_id,
            }
        )
    return jobs


async def run_evaluation(world, *, seed: int = 1, n_jobs: int = 6, policies: list[str] | None = None, max_steps: int = 2500) -> EvaluationReport:
    policies = policies or list(POLICIES)
    t0 = world.settings.t
    source = world.stations[0].id if world.stations else "gs-ashburn"
    dest = source
    template_jobs = seeded_jobs(seed, n_jobs, t0, source, dest)
    earths = [n.id for n in world.nodes if n.kind.value == "earth"]
    rows: list[EvaluationPolicyRow] = []

    for policy in policies:
        await world.reset()
        await world.seek(t0)
        world.settings.headless = True
        bodies = [dict(j) for j in template_jobs]
        if policy == "round_robin":
            results = []
            for i, body in enumerate(sorted(bodies, key=lambda b: (b.get("deadline_at") is None, b.get("deadline_at") or 0))):
                body["policy"] = "planner"
                if earths:
                    body["forced_node_id"] = earths[i % len(earths)]
                results.append(await world.submit_job(body))
        else:
            results = await world.submit_batch(bodies, policy=policy)

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

        costs, comps, waits, c_err, k_err = [], [], [], [], []
        hits = 0
        failed = 0
        n = 0
        for j in world.jobs.values():
            n += 1
            plan = world.plans.get(j.plan_id or "")
            if j.state == JobState.failed:
                failed += 1
            if j.deadline_at is not None and j.state == JobState.completed and j.actual_completion is not None:
                if j.actual_completion <= j.deadline_at:
                    hits += 1
            elif j.deadline_at is None and j.state == JobState.completed:
                hits += 1
            if plan and j.state == JobState.completed:
                costs.append(plan.estimated_cost)
                comps.append(j.actual_completion or plan.estimated_completion)
                waits.append(max(0.0, plan.compute_start - j.submitted_at))
                if j.actual_completion is not None:
                    c_err.append(abs(j.actual_completion - plan.estimated_completion))
                if j.actual_cost is not None:
                    k_err.append(abs(j.actual_cost - plan.estimated_cost))
        denom = max(n, 1)
        rows.append(
            EvaluationPolicyRow(
                policy=policy,
                n_jobs=n,
                deadline_hit_rate=hits / denom,
                mean_cost=sum(costs) / len(costs) if costs else 0.0,
                mean_completion=sum(comps) / len(comps) if comps else 0.0,
                mean_compute_wait_s=sum(waits) / len(waits) if waits else 0.0,
                completion_prediction_mae=sum(c_err) / len(c_err) if c_err else 0.0,
                cost_prediction_mae=sum(k_err) / len(k_err) if k_err else 0.0,
                n_failed=failed,
            )
        )

    report = EvaluationReport(
        id=world.ids.next("eval"),
        scenario_id=world.settings.scenario_id,
        seed=seed,
        created_t=world.settings.t,
        policies=rows,
        job_template={"n": n_jobs, "t0": t0, "jobs": template_jobs},
    )
    dumped = report.model_dump()
    world.evaluations[report.id] = dumped
    if world.store:
        world.store.put_evaluation(dumped)
    return report
