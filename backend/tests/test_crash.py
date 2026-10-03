"""SQLite restore after a simulated process crash (close without reset)."""

import pytest

from app.config import AppConfig
from app.eval.market_day import count_stolen_windows
from app.sim.world import SimWorld


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sqlite_restore_after_simulated_crash(tmp_path):
    db = tmp_path / "crash.sqlite"
    cfg = AppConfig(db_path=db, persist=True, headless=True, scenario="mvp-thesis", log_json=False)
    w1 = SimWorld(cfg, restore=False)
    await w1.seek(250.0)
    res = await w1.submit_job(
        {
            "name": "hold",
            "tenant_id": "alpha",
            "input_bytes": 400_000,
            "output_bytes": 80_000,
            "work": 90.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 80_000,
        }
    )
    assert res.get("plan")
    job_id = res["job"]["id"]
    plan_id = res["plan"]["id"]
    start, end = res["plan"]["compute_start"], res["plan"]["compute_end"]
    clock = w1.settings.t
    n_res = len(w1.reservations)
    n_link = len(w1.link_reservations)
    # Simulated crash: persist then drop the process (close WAL owner).
    w1._persist_clock()
    w1.close()

    w2 = SimWorld(cfg, restore=True)
    assert w2.settings.t == pytest.approx(clock)
    assert job_id in w2.jobs
    assert w2.jobs[job_id].tenant_id == "alpha"
    assert plan_id in w2.plans
    assert len(w2.reservations) == n_res
    assert len(w2.link_reservations) == n_link
    steal = await w2.submit_job(
        {
            "name": "want-same-slot",
            "tenant_id": "beta",
            "input_bytes": 400_000,
            "output_bytes": 80_000,
            "work": 90.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 80_000,
        }
    )
    if steal.get("plan"):
        assert steal["plan"]["compute_start"] + 1e-6 >= end
        assert not (steal["plan"]["compute_start"] < end and start < steal["plan"]["compute_end"])
    assert count_stolen_windows(w2.reservations, w2.link_reservations) == 0
    w2.close()
