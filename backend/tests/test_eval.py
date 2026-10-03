import pytest

from app.eval.runner import run_evaluation, seeded_jobs


def test_seeded_jobs_stable():
    assert seeded_jobs(7, 4, 0.0, "gs-ashburn", "gs-ashburn") == seeded_jobs(
        7, 4, 0.0, "gs-ashburn", "gs-ashburn"
    )


@pytest.mark.asyncio
async def test_evaluation_report(world):
    report = await run_evaluation(world, seed=2, n_jobs=3, policies=["planner", "earth_only"], max_steps=400)
    assert report.seed == 2
    assert len(report.policies) == 2
    names = {p.policy for p in report.policies}
    assert names == {"planner", "earth_only"}
    assert report.id.startswith("eval-")


@pytest.mark.asyncio
async def test_round_robin_cycles_all_compute_kinds(world):
    ids = world.compatible_compute_ids()
    assert any(i.startswith("earth-") for i in ids)
    assert any(i.startswith("orbital-") for i in ids)
    targets = []
    for _ in range(len(ids)):
        r = await world.submit_job(
            {
                "input_bytes": 300_000,
                "output_bytes": 60_000,
                "work": 12.0,
                "source_id": "gs-ashburn",
                "destination_id": "gs-ashburn",
                "deadline_at": 7000,
                "policy": "round_robin",
            }
        )
        if r.get("plan"):
            targets.append(r["plan"]["compute_node_id"])
        else:
            reason = (r.get("job") or {}).get("fail_reason") or ""
            targets.append(reason.split(":")[0])
    assert targets == ids
    assert any(t.startswith("earth-") for t in targets)
    assert any(t.startswith("orbital-") for t in targets)
