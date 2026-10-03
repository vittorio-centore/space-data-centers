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
